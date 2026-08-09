from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.admin_grocery_orders import (
    assign_grocery_order_to_shopper,
    list_available_shoppers,
    list_shopper_roster,
)
from app.models.order import Order, OrderPaymentSummary, OrderPricingSummary, OrderStatus
from app.models.user import User, UserType
from app.schemas.fulfillment import AssignWorkerRequest
from app.services.shopper_fulfillment_service import FulfillmentNotFoundError, FulfillmentStateError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_user() -> User:
    return User(
        id="admin-1",
        name="Admin",
        email="admin@example.com",
        password_hash="x",
        user_types=[UserType.PLATFORM_USER],
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
    )


class StubShopperFulfillmentService:
    def __init__(self, *, order: Order | None = None, error: Exception | None = None) -> None:
        self._order = order
        self._error = error
        self.assign_calls: list[dict] = []

    def list_available_shoppers(self, *, page, page_size, search=None):
        shopper = User(
            id="shopper-1",
            name="Shopper One",
            email="shopper@example.com",
            password_hash="x",
            user_types=[UserType.SHOPPER],
            user_configuration={},
            created_at=utc_now(),
        )
        return [shopper], 1

    def list_shopper_roster(self, *, page, page_size, search=None):
        shopper = User(
            id="shopper-1",
            name="Shopper One",
            email="shopper@example.com",
            password_hash="x",
            user_types=[UserType.SHOPPER],
            user_configuration={},
            created_at=utc_now(),
        )
        return [{"user": shopper, "active_count": 3, "completed_this_week": 7}], 1

    async def assign(self, *, order_id, shopper_id, actor_user_id, note):
        self.assign_calls.append({"order_id": order_id, "shopper_id": shopper_id, "actor_user_id": actor_user_id, "note": note})
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order


class AdminGroceryOrderAssignmentEndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_list_available_shoppers_returns_workers(self) -> None:
        response = list_available_shoppers(
            page=1, page_size=20, search=None, _=make_user(), shopper_fulfillment_service=StubShopperFulfillmentService()
        )

        self.assertEqual(1, response.total)
        self.assertEqual("shopper-1", response.items[0].id)

    def test_list_shopper_roster_returns_workload(self) -> None:
        response = list_shopper_roster(
            page=1, page_size=20, search=None, _=make_user(), shopper_fulfillment_service=StubShopperFulfillmentService()
        )

        self.assertEqual(1, response.total)
        self.assertEqual("shopper-1", response.items[0].id)
        self.assertEqual(3, response.items[0].active_count)
        self.assertEqual(7, response.items[0].completed_this_week)

    async def test_assign_grocery_order_to_shopper_passes_payload_through(self) -> None:
        order = make_order()
        service = StubShopperFulfillmentService(order=order)
        payload = AssignWorkerRequest(worker_id="shopper-1", note="urgent")

        response = await assign_grocery_order_to_shopper(
            order_id="order-1", payload=payload, current_admin=make_user(), shopper_fulfillment_service=service
        )

        self.assertEqual("order-1", response.id)
        self.assertEqual(1, len(service.assign_calls))
        self.assertEqual("shopper-1", service.assign_calls[0]["shopper_id"])

    async def test_assign_grocery_order_to_shopper_maps_not_found_to_404(self) -> None:
        service = StubShopperFulfillmentService(error=FulfillmentNotFoundError())
        payload = AssignWorkerRequest(worker_id="shopper-1")

        with self.assertRaises(HTTPException) as context:
            await assign_grocery_order_to_shopper(
                order_id="order-1", payload=payload, current_admin=make_user(), shopper_fulfillment_service=service
            )

        self.assertEqual(404, context.exception.status_code)

    async def test_assign_grocery_order_to_shopper_maps_state_error_to_400(self) -> None:
        service = StubShopperFulfillmentService(error=FulfillmentStateError("Order must be confirmed."))
        payload = AssignWorkerRequest(worker_id="shopper-1")

        with self.assertRaises(HTTPException) as context:
            await assign_grocery_order_to_shopper(
                order_id="order-1", payload=payload, current_admin=make_user(), shopper_fulfillment_service=service
            )

        self.assertEqual(400, context.exception.status_code)


if __name__ == "__main__":
    unittest.main()
