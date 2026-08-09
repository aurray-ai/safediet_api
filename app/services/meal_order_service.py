from __future__ import annotations

from datetime import datetime, timezone

from app.models.meal_order import MealOrder, MealOrderItemSnapshot
from app.models.order import OrderStatus
from app.models.user import User
from app.repositories.meal_order_repository import MealOrderRepository
from app.schemas.meal_order import (
    MealOrderCancelResponse,
    MealOrderItemResponse,
    MealOrderListResponse,
    MealOrderPaymentSummaryResponse,
    MealOrderPricingSummaryResponse,
    MealOrderResponse,
    MealOrderStatusHistoryResponse,
)


class MealOrderNotFoundError(Exception):
    pass


class MealOrderTransitionError(Exception):
    pass


class MealOrderService:
    def __init__(self, *, meal_order_repository: MealOrderRepository) -> None:
        self._meal_order_repository = meal_order_repository

    def list_user_orders(
        self,
        *,
        current_user: User,
        before: str | None,
        limit: int,
    ) -> MealOrderListResponse:
        items, next_cursor = self._meal_order_repository.list_orders_for_user(
            user_id=current_user.id,
            before=before,
            limit=limit,
        )
        return MealOrderListResponse(items=[self._to_response(item) for item in items], next_cursor=next_cursor)

    def get_user_order(self, *, current_user: User, order_id: str) -> MealOrderResponse:
        order = self._meal_order_repository.get_order_for_user(user_id=current_user.id, order_id=order_id)
        if order is None:
            raise MealOrderNotFoundError
        return self._to_response(order)

    def cancel_order(
        self,
        *,
        current_user: User,
        order_id: str,
        reason: str,
    ) -> MealOrderCancelResponse:
        order = self._meal_order_repository.get_order_for_user(user_id=current_user.id, order_id=order_id)
        if order is None:
            raise MealOrderNotFoundError
        if order.status not in {
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.PAYMENT_PROCESSING,
            OrderStatus.CONFIRMED,
            OrderStatus.PICKING,
        }:
            raise MealOrderTransitionError("Order cannot be canceled in its current state.")
        if (
            order.cancellation_window_expires_at is not None
            and datetime.now(timezone.utc) > order.cancellation_window_expires_at
            and order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_PROCESSING}
        ):
            raise MealOrderTransitionError("The cancellation window has expired.")
        updated = self._meal_order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.CANCELED,
            note=reason,
            actor_user_id=current_user.id,
        )
        if updated is None:
            raise MealOrderNotFoundError
        return MealOrderCancelResponse(order=self._to_response(updated), message="Order canceled.")

    @staticmethod
    def _estimated_status(item: MealOrderItemSnapshot, *, order_status: OrderStatus) -> str:
        if order_status in {
            OrderStatus.CANCELED,
            OrderStatus.REFUNDED,
            OrderStatus.PARTIALLY_REFUNDED,
            OrderStatus.PAYMENT_FAILED,
        }:
            return "canceled"
        if order_status in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_PROCESSING}:
            return "upcoming"
        if item.delivery_date is None:
            return "upcoming"

        today = datetime.now(timezone.utc).date()
        if item.delivery_date < today:
            return "delivered"
        if item.delivery_date == today:
            return "out_for_delivery"
        return "upcoming"

    @staticmethod
    def _to_response(order: MealOrder) -> MealOrderResponse:
        return MealOrderResponse(
            id=order.id,
            order_number=order.order_number,
            user_id=order.user_id,
            status=order.status.value,
            currency=order.currency,
            delivery_type=order.delivery_type.value,
            items=[
                MealOrderItemResponse(
                    id=item.id,
                    meal_id=item.meal_id,
                    meal_name=item.meal_name,
                    img_url=item.img_url,
                    servings=item.servings,
                    unit_price_minor=item.unit_price_minor,
                    line_total_minor=item.line_total_minor,
                    currency=item.currency,
                    delivery_date=item.delivery_date,
                    slot=item.slot,
                    estimated_status=MealOrderService._estimated_status(item, order_status=order.status),
                )
                for item in order.items
            ],
            pricing_summary=MealOrderPricingSummaryResponse(
                currency=order.pricing_summary.currency,
                subtotal_minor=order.pricing_summary.subtotal_minor,
                delivery_fee_minor=order.pricing_summary.delivery_fee_minor,
                service_fee_minor=order.pricing_summary.service_fee_minor,
                total_minor=order.pricing_summary.total_minor,
            ),
            address_snapshot=order.address_snapshot,
            payment_summary=MealOrderPaymentSummaryResponse(
                currency=order.payment_summary.currency,
                wallet_amount_minor=order.payment_summary.wallet_amount_minor,
                card_amount_minor=order.payment_summary.card_amount_minor,
                total_paid_minor=order.payment_summary.total_paid_minor,
                provider=order.payment_summary.provider,
                provider_payment_intent_id=order.payment_summary.provider_payment_intent_id,
            ),
            cancellation_window_expires_at=order.cancellation_window_expires_at,
            status_history=[
                MealOrderStatusHistoryResponse(
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
        )
