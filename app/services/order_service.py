from __future__ import annotations

from datetime import datetime, timezone

from app.models.order import Order, OrderStatus, SubstitutionResolution
from app.models.user import User
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.order_repository import OrderRepository
from app.services.order_status_communication_service import OrderStatusCommunicationService
from app.schemas.order import (
    OrderCancelResponse,
    OrderFulfillmentAssignmentHistoryResponse,
    OrderListResponse,
    OrderPaymentSummaryResponse,
    OrderPricingSummaryResponse,
    OrderResponse,
    OrderStatusHistoryResponse,
    OrderItemResponse,
)


class OrderNotFoundError(Exception):
    pass


class OrderTransitionError(Exception):
    pass


ALLOWED_ADMIN_ORDER_STATUS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING_PAYMENT: {
        OrderStatus.PAYMENT_PROCESSING,
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELED,
        OrderStatus.PAYMENT_FAILED,
    },
    OrderStatus.PAYMENT_PROCESSING: {
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELED,
        OrderStatus.PAYMENT_FAILED,
    },
    OrderStatus.CONFIRMED: {
        OrderStatus.PICKING,
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    },
    OrderStatus.PICKING: {
        OrderStatus.PACKED,
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    },
    OrderStatus.PACKED: {
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    },
    OrderStatus.OUT_FOR_DELIVERY: {
        OrderStatus.DELIVERED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    },
    OrderStatus.DELIVERED: {
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    },
    OrderStatus.PARTIALLY_REFUNDED: {
        OrderStatus.REFUNDED,
    },
    OrderStatus.REFUNDED: set(),
    OrderStatus.CANCELED: set(),
    OrderStatus.PAYMENT_FAILED: set(),
}


class OrderService:
    def __init__(
        self,
        *,
        order_repository: OrderRepository,
        grocery_repository: GroceryRepository,
        communication_service: OrderStatusCommunicationService | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._grocery_repository = grocery_repository
        self._communication_service = communication_service

    def list_user_orders(
        self,
        *,
        current_user: User,
        before: str | None,
        limit: int,
    ) -> OrderListResponse:
        items, next_cursor = self._order_repository.list_orders_for_user(
            user_id=current_user.id,
            before=before,
            limit=limit,
        )
        return OrderListResponse(items=[self._to_response(item) for item in items], next_cursor=next_cursor)

    def get_user_order(self, *, current_user: User, order_id: str) -> OrderResponse:
        order = self._order_repository.get_order_for_user(user_id=current_user.id, order_id=order_id)
        if order is None:
            raise OrderNotFoundError
        return self._to_response(order)

    def cancel_order(
        self,
        *,
        current_user: User,
        order_id: str,
        reason: str,
    ) -> OrderCancelResponse:
        order = self._order_repository.get_order_for_user(user_id=current_user.id, order_id=order_id)
        if order is None:
            raise OrderNotFoundError
        if order.status not in {
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.PAYMENT_PROCESSING,
            OrderStatus.CONFIRMED,
            OrderStatus.PICKING,
        }:
            raise OrderTransitionError("Order cannot be canceled in its current state.")
        if (
            order.cancellation_window_expires_at is not None
            and datetime.now(timezone.utc) > order.cancellation_window_expires_at
            and order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_PROCESSING}
        ):
            raise OrderTransitionError("The cancellation window has expired.")
        updated = self._order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.CANCELED,
            note=reason,
            actor_user_id=current_user.id,
        )
        if updated is None:
            raise OrderNotFoundError
        return OrderCancelResponse(order=self._to_response(updated), message="Order canceled.")

    def list_admin_orders(
        self,
        *,
        status: str | None,
        page: int,
        page_size: int,
    ) -> OrderListResponse:
        normalized_status = status.strip().lower() if status is not None else None
        items, total = self._order_repository.list_orders_admin(
            status=normalized_status,
            page=page,
            page_size=page_size,
        )
        return OrderListResponse(
            items=[self._to_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_admin_order(self, *, order_id: str) -> OrderResponse:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise OrderNotFoundError
        return self._to_response(order)

    def advance_order_status(
        self,
        *,
        order_id: str,
        status: OrderStatus,
        note: str,
        actor_user_id: str | None,
    ) -> OrderResponse:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise OrderNotFoundError
        self._validate_admin_status_transition(current=order.status, target=status)
        updated = self._order_repository.update_status(
            order_id=order.id,
            status=status,
            note=note or f"Order moved to {status.value}.",
            actor_user_id=actor_user_id,
        )
        if updated is None:
            raise OrderNotFoundError
        if self._communication_service is not None:
            self._communication_service.notify_customer_order_status_changed(
                order=updated,
                idempotency_key=f"order_status_customer:{updated.id}:{updated.status.value}:{updated.updated_at.isoformat()}",
            )
        return self._to_response(updated)

    @staticmethod
    def _validate_admin_status_transition(*, current: OrderStatus, target: OrderStatus) -> None:
        if current == target:
            raise OrderTransitionError(f"Order is already marked as {current.value}.")

        allowed_targets = ALLOWED_ADMIN_ORDER_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed_targets:
            allowed_labels = ", ".join(option.value for option in sorted(allowed_targets, key=lambda item: item.value))
            if allowed_labels:
                raise OrderTransitionError(
                    f"Cannot move order from {current.value} to {target.value}. Allowed next statuses: {allowed_labels}."
                )
            raise OrderTransitionError(f"Cannot move order from {current.value} to {target.value}.")

    def apply_substitution_decision(
        self,
        *,
        order_id: str,
        item_id: str,
        replacement_product_id: str | None,
        note: str,
        actor_user_id: str | None,
    ) -> OrderResponse:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise OrderNotFoundError
        replacement_product = (
            self._grocery_repository.get_product(replacement_product_id)
            if replacement_product_id
            else None
        )
        updated_items = []
        found = False
        for item in order.items:
            if item.id != item_id:
                updated_items.append(
                    {
                        "id": item.id,
                        "product_id": item.product_id,
                        "category_id": item.category_id,
                        "product_name": item.product_name,
                        "img_url": item.img_url,
                        "quantity": item.quantity,
                        "unit_label": item.unit_label,
                        "unit_weight_grams": item.unit_weight_grams,
                        "unit_price_minor": item.unit_price_minor,
                        "line_total_minor": item.line_total_minor,
                        "currency": item.currency,
                        "allow_substitutions": item.allow_substitutions,
                        "substitution_resolution": item.substitution_resolution.value,
                        "substituted_product_id": item.substituted_product_id,
                    }
                )
                continue
            found = True
            updated_items.append(
                {
                    "id": item.id,
                    "product_id": replacement_product_id or item.product_id,
                    "category_id": (
                        replacement_product.category_id if replacement_product is not None else item.category_id
                    ),
                    "product_name": replacement_product.product if replacement_product is not None else item.product_name,
                    "img_url": replacement_product.img_url if replacement_product is not None else item.img_url,
                    "quantity": item.quantity,
                    "unit_label": item.unit_label,
                    "unit_weight_grams": item.unit_weight_grams,
                    "unit_price_minor": item.unit_price_minor,
                    "line_total_minor": item.line_total_minor,
                    "currency": item.currency,
                    "allow_substitutions": item.allow_substitutions,
                    "substitution_resolution": (
                        SubstitutionResolution.ADMIN_REPLACED.value
                        if replacement_product_id
                        else SubstitutionResolution.REMOVED.value
                    ),
                    "substituted_product_id": replacement_product_id,
                }
            )
        if not found:
            raise OrderNotFoundError
        updated_order = self._order_repository.replace_items(order_id=order.id, items=updated_items)
        if updated_order is None:
            raise OrderNotFoundError
        updated_order = self._order_repository.update_status(
            order_id=order.id,
            status=updated_order.status,
            note=note or "Substitution decision applied.",
            actor_user_id=actor_user_id,
        )
        if updated_order is None:
            raise OrderNotFoundError
        return self._to_response(updated_order)

    @staticmethod
    def _to_response(order: Order) -> OrderResponse:
        return OrderResponse(
            id=order.id,
            order_number=order.order_number,
            user_id=order.user_id,
            store_id=order.store_id,
            status=order.status.value,
            currency=order.currency,
            items=[
                OrderItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    category_id=item.category_id,
                    product_name=item.product_name,
                    img_url=item.img_url,
                    quantity=item.quantity,
                    unit_label=item.unit_label,
                    unit_weight_grams=item.unit_weight_grams,
                    unit_price_minor=item.unit_price_minor,
                    line_total_minor=item.line_total_minor,
                    base_price_minor=item.base_price_minor,
                    discount_percent_applied=item.discount_percent_applied,
                    currency=item.currency,
                    allow_substitutions=item.allow_substitutions,
                    substitution_resolution=item.substitution_resolution.value,
                    substituted_product_id=item.substituted_product_id,
                )
                for item in order.items
            ],
            pricing_summary=OrderPricingSummaryResponse(
                currency=order.pricing_summary.currency,
                subtotal_minor=order.pricing_summary.subtotal_minor,
                delivery_fee_minor=order.pricing_summary.delivery_fee_minor,
                service_fee_minor=order.pricing_summary.service_fee_minor,
                total_minor=order.pricing_summary.total_minor,
                total_weight_grams=order.pricing_summary.total_weight_grams,
            ),
            address_snapshot=order.address_snapshot,
            substitution_policy=order.substitution_policy,
            payment_summary=OrderPaymentSummaryResponse(
                currency=order.payment_summary.currency,
                wallet_amount_minor=order.payment_summary.wallet_amount_minor,
                card_amount_minor=order.payment_summary.card_amount_minor,
                total_paid_minor=order.payment_summary.total_paid_minor,
                provider=order.payment_summary.provider,
                provider_payment_intent_id=order.payment_summary.provider_payment_intent_id,
            ),
            cancellation_window_expires_at=order.cancellation_window_expires_at,
            status_history=[
                OrderStatusHistoryResponse(
                    status=entry.status.value,
                    note=entry.note,
                    actor_user_id=entry.actor_user_id,
                    created_at=entry.created_at,
                )
                for entry in order.status_history
            ],
            metadata=order.metadata,
            created_at=order.created_at,
            updated_at=order.updated_at,
            fulfillment_status=order.fulfillment_status.value,
            assigned_worker_id=order.assigned_worker_id,
            assigned_by=order.assigned_by,
            assigned_at=order.assigned_at,
            assignment_history=[
                OrderFulfillmentAssignmentHistoryResponse(
                    action=entry.action,
                    worker_id=entry.worker_id,
                    actor_user_id=entry.actor_user_id,
                    note=entry.note,
                    created_at=entry.created_at,
                )
                for entry in order.assignment_history
            ],
        )
