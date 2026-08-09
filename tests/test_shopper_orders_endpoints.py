from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.shopper_orders import (
    decline_my_grocery_order,
    get_my_grocery_order,
    list_my_grocery_orders,
    update_my_grocery_order_status,
)
from app.models.fulfillment import ShopperFulfillmentStatus
from app.models.order import Order, OrderPaymentSummary, OrderPricingSummary, OrderStatus
from app.models.user import User, UserType
from app.schemas.fulfillment import DeclineRequest, FulfillmentStatusUpdateRequest
from app.services.shopper_fulfillment_service import FulfillmentNotFoundError, FulfillmentTransitionError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_shopper() -> User:
    return User(
        id="shopper-1",
        name="Shopper One",
        email="shopper@example.com",
        password_hash="x",
        user_types=[UserType.SHOPPER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_order(*, order_id: str = "order-1") -> Order:
    now = utc_now()
    return Order(
        id=order_id,
        order_number=f"GO-{order_id}",
        user_id="customer-1",
        store_id="main_store",
        status=OrderStatus.CONFIRMED,
        currency="GBP",
        items=[],
        pricing_summary=OrderPricingSummary(
            currency="GBP", subtotal_minor=1000, delivery_fee_minor=0, service_fee_minor=0, total_minor=1000, total_weight_grams=500
        ),
        address_snapshot={},
        substitution_policy={},
        payment_summary=OrderPaymentSummary(
            currency="GBP",
            wallet_amount_minor=0,
            card_amount_minor=1000,
            total_paid_minor=1000,
            provider="stripe",
            provider_payment_intent_id=None,
        ),
        cancellation_window_expires_at=None,
        status_history=[],
        metadata={},
        created_at=now,
        updated_at=now,
        fulfillment_status=ShopperFulfillmentStatus.ASSIGNED,
        assigned_worker_id="shopper-1",
    )


class StubShopperFulfillmentService:
    def __init__(self, *, order: Order | None = None, error: Exception | None = None) -> None:
        self._order = order
        self._error = error
        self.advance_calls: list[dict] = []
        self.decline_calls: list[dict] = []

    def list_mine(self, *, current_shopper, before, limit):
        return ([self._order] if self._order is not None else []), None

    def get_for_shopper(self, *, current_shopper, order_id):
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    async def advance_status(self, *, current_shopper, order_id, status, note):
        self.advance_calls.append({"order_id": order_id, "status": status, "note": note})
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    async def decline(self, *, current_shopper, order_id, reason_code, note):
        self.decline_calls.append({"order_id": order_id, "reason_code": reason_code, "note": note})
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order


class ShopperOrdersEndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_list_my_grocery_orders_returns_items(self) -> None:
        order = make_order()
        service = StubShopperFulfillmentService(order=order)

        response = list_my_grocery_orders(before=None, limit=20, current_shopper=make_shopper(), shopper_fulfillment_service=service)

        self.assertEqual(1, len(response.items))

    def test_get_my_grocery_order_maps_not_found_to_404(self) -> None:
        service = StubShopperFulfillmentService(error=FulfillmentNotFoundError())

        with self.assertRaises(HTTPException) as context:
            get_my_grocery_order(order_id="missing", current_shopper=make_shopper(), shopper_fulfillment_service=service)

        self.assertEqual(404, context.exception.status_code)

    async def test_update_status_rejects_invalid_status_value(self) -> None:
        service = StubShopperFulfillmentService(order=make_order())
        payload = FulfillmentStatusUpdateRequest(status="not_a_real_status")

        with self.assertRaises(HTTPException) as context:
            await update_my_grocery_order_status(order_id="order-1", payload=payload, current_shopper=make_shopper(), shopper_fulfillment_service=service)

        self.assertEqual(422, context.exception.status_code)

    async def test_update_status_passes_payload_through(self) -> None:
        order = make_order()
        service = StubShopperFulfillmentService(order=order)
        payload = FulfillmentStatusUpdateRequest(status="shopping", note="on my way")

        response = await update_my_grocery_order_status(
            order_id="order-1", payload=payload, current_shopper=make_shopper(), shopper_fulfillment_service=service
        )

        self.assertEqual("order-1", response.id)
        self.assertEqual(1, len(service.advance_calls))
        self.assertEqual(ShopperFulfillmentStatus.SHOPPING, service.advance_calls[0]["status"])

    async def test_update_status_maps_transition_error_to_400(self) -> None:
        service = StubShopperFulfillmentService(
            order=make_order(), error=FulfillmentTransitionError("Status can only advance one step at a time.")
        )
        payload = FulfillmentStatusUpdateRequest(status="packed")

        with self.assertRaises(HTTPException) as context:
            await update_my_grocery_order_status(order_id="order-1", payload=payload, current_shopper=make_shopper(), shopper_fulfillment_service=service)

        self.assertEqual(400, context.exception.status_code)

    async def test_decline_passes_payload_through(self) -> None:
        order = make_order()
        service = StubShopperFulfillmentService(order=order)
        payload = DeclineRequest(reason_code="fully_booked", note="")

        response = await decline_my_grocery_order(order_id="order-1", payload=payload, current_shopper=make_shopper(), shopper_fulfillment_service=service)

        self.assertEqual("order-1", response.id)
        self.assertEqual(1, len(service.decline_calls))
        self.assertEqual("fully_booked", service.decline_calls[0]["reason_code"])


if __name__ == "__main__":
    unittest.main()
