from __future__ import annotations

from app.models.order import OrderStatus, RefundStatus
from app.models.user import User
from app.repositories.order_repository import OrderRepository
from app.repositories.refund_repository import RefundRepository
from app.schemas.order import RefundCreateRequest, RefundListResponse, RefundResponse
from app.services.billing_service import BillingService
from app.services.stripe_billing_gateway import StripeBillingGateway


class RefundError(Exception):
    pass


class RefundService:
    def __init__(
        self,
        *,
        order_repository: OrderRepository,
        refund_repository: RefundRepository,
        billing_service: BillingService,
        stripe_gateway: StripeBillingGateway,
    ) -> None:
        self._order_repository = order_repository
        self._refund_repository = refund_repository
        self._billing_service = billing_service
        self._stripe_gateway = stripe_gateway

    def create_refund(
        self,
        *,
        current_user: User,
        order_id: str,
        payload: RefundCreateRequest,
    ) -> RefundResponse:
        order = self._order_repository.get_order_for_user(user_id=current_user.id, order_id=order_id)
        if order is None:
            raise RefundError("Order not found.")
        return self._create_refund_for_order(order=order, payload=payload)

    def create_admin_refund(
        self,
        *,
        order_id: str,
        payload: RefundCreateRequest,
    ) -> RefundResponse:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise RefundError("Order not found.")
        return self._create_refund_for_order(order=order, payload=payload)

    def list_refunds(self, *, current_user: User, order_id: str) -> RefundListResponse:
        order = self._order_repository.get_order_for_user(user_id=current_user.id, order_id=order_id)
        if order is None:
            raise RefundError("Order not found.")
        items = self._refund_repository.list_for_user_order(user_id=current_user.id, order_id=order_id)
        return RefundListResponse(items=[self._to_response(item) for item in items])

    def list_admin_refunds(self, *, order_id: str) -> RefundListResponse:
        items = self._refund_repository.list_for_order(order_id=order_id)
        return RefundListResponse(items=[self._to_response(item) for item in items])

    def _create_refund_for_order(self, *, order, payload: RefundCreateRequest) -> RefundResponse:
        existing = self._refund_repository.get_by_idempotency_key(idempotency_key=payload.idempotency_key)
        if existing is not None:
            return self._to_response(existing)

        refunded_so_far = int((order.metadata or {}).get("refunded_total_minor") or 0)
        refundable_minor = max(order.payment_summary.total_paid_minor - refunded_so_far, 0)
        if refundable_minor <= 0:
            raise RefundError("Order has no refundable balance remaining.")

        requested_minor = payload.amount_minor
        if requested_minor is None:
            if payload.line_items:
                line_map = {item.id: item for item in order.items}
                requested_minor = 0
                for line_item in payload.line_items:
                    matched = line_map.get(line_item.item_id)
                    if matched is None:
                        raise RefundError(f"Order item {line_item.item_id} was not found.")
                    if line_item.quantity > matched.quantity:
                        raise RefundError("Refund quantity exceeds ordered quantity.")
                    requested_minor += matched.unit_price_minor * line_item.quantity
            else:
                requested_minor = refundable_minor
        requested_minor = min(requested_minor, refundable_minor)
        if requested_minor <= 0:
            raise RefundError("Refund amount must be greater than zero.")

        total_paid_minor = max(order.payment_summary.total_paid_minor, 1)
        wallet_ratio = order.payment_summary.wallet_amount_minor / total_paid_minor
        wallet_refund_minor = min(int(round(requested_minor * wallet_ratio)), order.payment_summary.wallet_amount_minor)
        card_refund_minor = max(requested_minor - wallet_refund_minor, 0)

        if wallet_refund_minor > 0:
            self._billing_service.refund_to_wallet(
                user_id=order.user_id,
                amount_minor=wallet_refund_minor,
                currency=order.currency,
                reference_type="grocery_refund",
                reference_id=order.id,
                metadata={"reason": payload.reason},
            )
        provider_refund_id = None
        if card_refund_minor > 0 and order.payment_summary.provider_payment_intent_id:
            provider_refund_id = self._stripe_gateway.refund_payment_intent(
                payment_intent_id=order.payment_summary.provider_payment_intent_id,
                amount_minor=card_refund_minor,
                idempotency_key=payload.idempotency_key,
                metadata={"order_id": order.id, "reason": payload.reason},
            )

        refund = self._refund_repository.create_refund(
            order_id=order.id,
            user_id=order.user_id,
            status=RefundStatus.COMPLETED,
            currency=order.currency,
            refund_type="partial" if requested_minor < refundable_minor else "full",
            reason=payload.reason,
            wallet_refund_minor=wallet_refund_minor,
            card_refund_minor=card_refund_minor,
            line_items=[entry.model_dump() for entry in payload.line_items],
            provider="stripe" if card_refund_minor > 0 else "wallet",
            provider_refund_id=provider_refund_id,
            idempotency_key=payload.idempotency_key,
            metadata={"requested_minor": requested_minor},
        )
        updated_metadata = dict(order.metadata or {})
        updated_metadata["refunded_total_minor"] = refunded_so_far + requested_minor
        new_status = (
            OrderStatus.REFUNDED
            if updated_metadata["refunded_total_minor"] >= order.payment_summary.total_paid_minor
            else OrderStatus.PARTIALLY_REFUNDED
        )
        self._order_repository.apply_refund_state(
            order_id=order.id,
            status=new_status,
            metadata=updated_metadata,
        )
        return self._to_response(refund)

    @staticmethod
    def _to_response(item) -> RefundResponse:
        return RefundResponse(
            id=item.id,
            order_id=item.order_id,
            user_id=item.user_id,
            status=item.status.value,
            currency=item.currency,
            refund_type=item.refund_type,
            reason=item.reason,
            wallet_refund_minor=item.wallet_refund_minor,
            card_refund_minor=item.card_refund_minor,
            line_items=item.line_items,
            provider=item.provider,
            provider_refund_id=item.provider_refund_id,
            idempotency_key=item.idempotency_key,
            metadata=item.metadata,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
