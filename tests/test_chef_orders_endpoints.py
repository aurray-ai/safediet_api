from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.chef_orders import (
    decline_my_meal_order,
    get_my_meal_order,
    list_my_meal_orders,
    update_my_meal_order_status,
)
from app.models.fulfillment import ChefFulfillmentStatus
from app.models.meal_order import (
    MealDeliveryType,
    MealOrder,
    MealOrderPaymentSummary,
    MealOrderPricingSummary,
)
from app.models.order import OrderStatus
from app.models.user import User, UserType
from app.schemas.fulfillment import DeclineRequest, FulfillmentStatusUpdateRequest
from app.services.chef_fulfillment_service import FulfillmentNotFoundError, FulfillmentTransitionError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_chef() -> User:
    return User(
        id="chef-1",
        name="Chef One",
        email="chef@example.com",
        password_hash="x",
        user_types=[UserType.CHEF],
        user_configuration={},
        created_at=utc_now(),
    )


def make_meal_order(*, order_id: str = "order-1") -> MealOrder:
    now = utc_now()
    return MealOrder(
        id=order_id,
        order_number=f"MO-{order_id}",
        user_id="customer-1",
        status=OrderStatus.CONFIRMED,
        currency="GBP",
        delivery_type=MealDeliveryType.STANDARD,
        items=[],
        pricing_summary=MealOrderPricingSummary(
            currency="GBP", subtotal_minor=1000, delivery_fee_minor=0, service_fee_minor=0, total_minor=1000
        ),
        address_snapshot={},
        payment_summary=MealOrderPaymentSummary(
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
        fulfillment_status=ChefFulfillmentStatus.ASSIGNED,
        assigned_worker_id="chef-1",
    )


class StubChefFulfillmentService:
    def __init__(self, *, order: MealOrder | None = None, error: Exception | None = None) -> None:
        self._order = order
        self._error = error
        self.advance_calls: list[dict] = []
        self.decline_calls: list[dict] = []

    def list_mine(self, *, current_chef, before, limit):
        return ([self._order] if self._order is not None else []), None

    def get_for_chef(self, *, current_chef, order_id):
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    async def advance_status(self, *, current_chef, order_id, status, note):
        self.advance_calls.append({"order_id": order_id, "status": status, "note": note})
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    async def decline(self, *, current_chef, order_id, reason_code, note):
        self.decline_calls.append({"order_id": order_id, "reason_code": reason_code, "note": note})
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order


class ChefOrdersEndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_list_my_meal_orders_returns_items(self) -> None:
        order = make_meal_order()
        service = StubChefFulfillmentService(order=order)

        response = list_my_meal_orders(before=None, limit=20, current_chef=make_chef(), chef_fulfillment_service=service)

        self.assertEqual(1, len(response.items))

    def test_get_my_meal_order_maps_not_found_to_404(self) -> None:
        service = StubChefFulfillmentService(error=FulfillmentNotFoundError())

        with self.assertRaises(HTTPException) as context:
            get_my_meal_order(order_id="missing", current_chef=make_chef(), chef_fulfillment_service=service)

        self.assertEqual(404, context.exception.status_code)

    async def test_update_status_rejects_invalid_status_value(self) -> None:
        service = StubChefFulfillmentService(order=make_meal_order())
        payload = FulfillmentStatusUpdateRequest(status="not_a_real_status")

        with self.assertRaises(HTTPException) as context:
            await update_my_meal_order_status(order_id="order-1", payload=payload, current_chef=make_chef(), chef_fulfillment_service=service)

        self.assertEqual(422, context.exception.status_code)

    async def test_update_status_passes_payload_through(self) -> None:
        order = make_meal_order()
        service = StubChefFulfillmentService(order=order)
        payload = FulfillmentStatusUpdateRequest(status="preparing", note="on it")

        response = await update_my_meal_order_status(
            order_id="order-1", payload=payload, current_chef=make_chef(), chef_fulfillment_service=service
        )

        self.assertEqual("order-1", response.id)
        self.assertEqual(1, len(service.advance_calls))
        self.assertEqual(ChefFulfillmentStatus.PREPARING, service.advance_calls[0]["status"])

    async def test_update_status_maps_transition_error_to_400(self) -> None:
        service = StubChefFulfillmentService(
            order=make_meal_order(), error=FulfillmentTransitionError("Status can only advance one step at a time.")
        )
        payload = FulfillmentStatusUpdateRequest(status="ready_for_delivery")

        with self.assertRaises(HTTPException) as context:
            await update_my_meal_order_status(order_id="order-1", payload=payload, current_chef=make_chef(), chef_fulfillment_service=service)

        self.assertEqual(400, context.exception.status_code)

    async def test_decline_passes_payload_through(self) -> None:
        order = make_meal_order()
        service = StubChefFulfillmentService(order=order)
        payload = DeclineRequest(reason_code="too_busy", note="fully booked")

        response = await decline_my_meal_order(order_id="order-1", payload=payload, current_chef=make_chef(), chef_fulfillment_service=service)

        self.assertEqual("order-1", response.id)
        self.assertEqual(1, len(service.decline_calls))
        self.assertEqual("too_busy", service.decline_calls[0]["reason_code"])


if __name__ == "__main__":
    unittest.main()
