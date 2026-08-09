from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.admin_meal_orders import (
    assign_meal_order_to_chef,
    get_meal_order_for_admin,
    list_available_chefs,
    list_chef_roster,
    list_unassigned_meal_orders,
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
from app.schemas.fulfillment import AssignWorkerRequest
from app.services.chef_fulfillment_service import FulfillmentNotFoundError, FulfillmentStateError


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
    )


class StubChefFulfillmentService:
    def __init__(self, *, order: MealOrder | None = None, error: Exception | None = None) -> None:
        self._order = order
        self._error = error
        self.assign_calls: list[dict] = []

    def list_unassigned_for_admin(self, *, before, limit):
        return ([self._order] if self._order is not None else []), None

    def get_for_admin(self, *, order_id):
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order

    def list_available_chefs(self, *, page, page_size, search=None):
        chef = User(
            id="chef-1",
            name="Chef One",
            email="chef@example.com",
            password_hash="x",
            user_types=[UserType.CHEF],
            user_configuration={},
            created_at=utc_now(),
        )
        return [chef], 1

    def list_chef_roster(self, *, page, page_size, search=None):
        chef = User(
            id="chef-1",
            name="Chef One",
            email="chef@example.com",
            password_hash="x",
            user_types=[UserType.CHEF],
            user_configuration={},
            created_at=utc_now(),
        )
        return [{"user": chef, "active_count": 2, "completed_this_week": 5}], 1

    async def assign(self, *, order_id, chef_id, actor_user_id, note):
        self.assign_calls.append({"order_id": order_id, "chef_id": chef_id, "actor_user_id": actor_user_id, "note": note})
        if self._error is not None:
            raise self._error
        assert self._order is not None
        return self._order


class AdminMealOrdersEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_unassigned_meal_orders_returns_items(self) -> None:
        order = make_meal_order()
        service = StubChefFulfillmentService(order=order)

        response = list_unassigned_meal_orders(
            before=None, limit=20, _=make_user(), chef_fulfillment_service=service
        )

        self.assertEqual(1, len(response.items))
        self.assertEqual("order-1", response.items[0].id)

    def test_list_available_chefs_returns_workers(self) -> None:
        response = list_available_chefs(
            page=1, page_size=20, search=None, _=make_user(), chef_fulfillment_service=StubChefFulfillmentService()
        )

        self.assertEqual(1, response.total)
        self.assertEqual("chef-1", response.items[0].id)

    def test_list_chef_roster_returns_workload(self) -> None:
        response = list_chef_roster(
            page=1, page_size=20, search=None, _=make_user(), chef_fulfillment_service=StubChefFulfillmentService()
        )

        self.assertEqual(1, response.total)
        self.assertEqual("chef-1", response.items[0].id)
        self.assertEqual(2, response.items[0].active_count)
        self.assertEqual(5, response.items[0].completed_this_week)

    def test_get_meal_order_for_admin_maps_not_found_to_404(self) -> None:
        service = StubChefFulfillmentService(error=FulfillmentNotFoundError())

        with self.assertRaises(HTTPException) as context:
            get_meal_order_for_admin(order_id="missing", _=make_user(), chef_fulfillment_service=service)

        self.assertEqual(404, context.exception.status_code)

    async def test_assign_meal_order_to_chef_passes_payload_through(self) -> None:
        order = make_meal_order()
        service = StubChefFulfillmentService(order=order)
        payload = AssignWorkerRequest(worker_id="chef-1", note="please rush")

        response = await assign_meal_order_to_chef(
            order_id="order-1", payload=payload, current_admin=make_user(), chef_fulfillment_service=service
        )

        self.assertEqual("order-1", response.id)
        self.assertEqual(1, len(service.assign_calls))
        self.assertEqual("chef-1", service.assign_calls[0]["chef_id"])
        self.assertEqual("admin-1", service.assign_calls[0]["actor_user_id"])

    async def test_assign_meal_order_to_chef_maps_state_error_to_400(self) -> None:
        service = StubChefFulfillmentService(error=FulfillmentStateError("Order must be confirmed."))
        payload = AssignWorkerRequest(worker_id="chef-1")

        with self.assertRaises(HTTPException) as context:
            await assign_meal_order_to_chef(
                order_id="order-1", payload=payload, current_admin=make_user(), chef_fulfillment_service=service
            )

        self.assertEqual(400, context.exception.status_code)
        self.assertEqual("Order must be confirmed.", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
