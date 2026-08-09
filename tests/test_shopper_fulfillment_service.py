from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.fulfillment import AssignmentHistoryEntry, ShopperFulfillmentStatus
from app.models.order import Order, OrderPaymentSummary, OrderPricingSummary, OrderStatus
from app.models.user import User, UserType
from app.services import shopper_fulfillment_service as shopper_fulfillment_service_module
from app.services.shopper_fulfillment_service import (
    FulfillmentNotFoundError,
    FulfillmentStateError,
    FulfillmentTransitionError,
    ShopperFulfillmentService,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user(*, user_id: str, user_types: list[UserType]) -> User:
    return User(
        id=user_id,
        name=f"User {user_id}",
        email=f"{user_id}@example.com",
        password_hash="x",
        user_types=user_types,
        user_configuration={},
        created_at=utc_now(),
    )


def make_order(
    *,
    order_id: str,
    status: OrderStatus = OrderStatus.CONFIRMED,
    fulfillment_status: ShopperFulfillmentStatus = ShopperFulfillmentStatus.UNASSIGNED,
    assigned_worker_id: str | None = None,
) -> Order:
    now = utc_now()
    return Order(
        id=order_id,
        order_number=f"GO-{order_id}",
        user_id="customer-1",
        store_id="main_store",
        status=status,
        currency="GBP",
        items=[],
        pricing_summary=OrderPricingSummary(
            currency="GBP",
            subtotal_minor=1000,
            delivery_fee_minor=0,
            service_fee_minor=0,
            total_minor=1000,
            total_weight_grams=500,
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
        fulfillment_status=fulfillment_status,
        assigned_worker_id=assigned_worker_id,
        assigned_by=None,
        assigned_at=None,
        assignment_history=[],
    )


class StubOrderRepository:
    def __init__(self, orders: dict[str, Order] | None = None) -> None:
        self.orders: dict[str, Order] = dict(orders or {})
        self.assign_calls: list[dict] = []
        self.advance_calls: list[dict] = []
        self.decline_calls: list[dict] = []

    def get_order(self, *, order_id: str) -> Order | None:
        return self.orders.get(order_id)

    def list_unassigned_for_admin(self, *, before, limit):
        items = [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.CONFIRMED and order.assigned_worker_id is None
        ]
        return items[:limit], None

    def list_for_worker(self, *, worker_id, before, limit):
        items = [order for order in self.orders.values() if order.assigned_worker_id == worker_id]
        return items[:limit], None

    def get_for_worker(self, *, worker_id, order_id):
        order = self.orders.get(order_id)
        if order is None or order.assigned_worker_id != worker_id:
            return None
        return order

    def assign_worker(self, *, order_id, worker_id, actor_user_id, note):
        self.assign_calls.append({"order_id": order_id, "worker_id": worker_id, "actor_user_id": actor_user_id, "note": note})
        order = self.orders.get(order_id)
        if order is None:
            return None
        history = [
            *order.assignment_history,
            AssignmentHistoryEntry(action="assigned", worker_id=worker_id, actor_user_id=actor_user_id, note=note, created_at=utc_now()),
        ]
        updated = replace(
            order,
            fulfillment_status=ShopperFulfillmentStatus.ASSIGNED,
            assigned_worker_id=worker_id,
            assigned_by=actor_user_id,
            assigned_at=utc_now(),
            assignment_history=history,
        )
        self.orders[order_id] = updated
        return updated

    def advance_fulfillment_status(self, *, order_id, status, actor_user_id, note):
        self.advance_calls.append({"order_id": order_id, "status": status, "actor_user_id": actor_user_id, "note": note})
        order = self.orders.get(order_id)
        if order is None:
            return None
        history = [
            *order.assignment_history,
            AssignmentHistoryEntry(action="status_changed", worker_id=None, actor_user_id=actor_user_id, note=note, created_at=utc_now()),
        ]
        updated = replace(order, fulfillment_status=status, assignment_history=history)
        self.orders[order_id] = updated
        return updated

    def record_decline(self, *, order_id, actor_user_id, reason_code, note):
        self.decline_calls.append({"order_id": order_id, "actor_user_id": actor_user_id, "reason_code": reason_code, "note": note})
        order = self.orders.get(order_id)
        if order is None:
            return None
        history = [
            *order.assignment_history,
            AssignmentHistoryEntry(action="declined", worker_id=actor_user_id, actor_user_id=actor_user_id, note=note, created_at=utc_now()),
        ]
        updated = replace(
            order,
            fulfillment_status=ShopperFulfillmentStatus.UNASSIGNED,
            assigned_worker_id=None,
            assigned_by=None,
            assigned_at=None,
            assignment_history=history,
        )
        self.orders[order_id] = updated
        return updated

    def count_workload_by_worker(self, *, worker_ids, since):
        workload: dict[str, dict[str, int]] = {}
        for order in self.orders.values():
            if order.assigned_worker_id not in worker_ids:
                continue
            entry = workload.setdefault(order.assigned_worker_id, {"active": 0, "completed_this_week": 0})
            if order.fulfillment_status in (ShopperFulfillmentStatus.ASSIGNED, ShopperFulfillmentStatus.SHOPPING):
                entry["active"] += 1
            elif order.fulfillment_status == ShopperFulfillmentStatus.PACKED:
                entry["completed_this_week"] += 1
        return workload

    def get_overview_counts(self, *, since):
        unassigned = sum(
            1
            for order in self.orders.values()
            if order.status == OrderStatus.CONFIRMED and order.assigned_worker_id is None
        )
        in_progress = sum(
            1
            for order in self.orders.values()
            if order.fulfillment_status in (ShopperFulfillmentStatus.ASSIGNED, ShopperFulfillmentStatus.SHOPPING)
        )
        completed_this_week = sum(
            1 for order in self.orders.values() if order.fulfillment_status == ShopperFulfillmentStatus.PACKED
        )
        return {"unassigned": unassigned, "in_progress": in_progress, "completed_this_week": completed_this_week}


class StubUserRepository:
    def __init__(self, users: dict[str, User] | None = None) -> None:
        self.users: dict[str, User] = dict(users or {})

    def find_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def list_users(self, *, page, page_size, search=None, user_type=None):
        items = [user for user in self.users.values() if user_type is None or user_type in user.user_types]
        return items, len(items)


class StubCommunicationService:
    def __init__(self) -> None:
        self.assigned_calls: list[dict] = []
        self.declined_calls: list[dict] = []

    async def notify_worker_assigned(self, **kwargs) -> None:
        self.assigned_calls.append(kwargs)

    async def notify_admin_declined(self, **kwargs) -> None:
        self.declined_calls.append(kwargs)


class StubRealtimeDeliveryService:
    def __init__(self) -> None:
        self.deliveries: list[dict] = []

    async def deliver(self, **kwargs) -> None:
        self.deliveries.append(kwargs)


def build_service(
    *, orders=None, users=None
) -> tuple[ShopperFulfillmentService, StubOrderRepository, StubUserRepository, StubCommunicationService]:
    order_repository = StubOrderRepository(orders)
    user_repository = StubUserRepository(users)
    communication_service = StubCommunicationService()
    service = ShopperFulfillmentService(
        order_repository=order_repository,
        user_repository=user_repository,
        communication_service=communication_service,
    )
    return service, order_repository, user_repository, communication_service


class ShopperFulfillmentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_assign_requires_confirmed_order(self) -> None:
        order = make_order(order_id="order-1", status=OrderStatus.PENDING_PAYMENT)
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        service, _, _, _ = build_service(orders={"order-1": order}, users={"shopper-1": shopper})

        with self.assertRaises(FulfillmentStateError):
            await service.assign(order_id="order-1", shopper_id="shopper-1", actor_user_id="admin-1", note="")

    async def test_assign_requires_target_user_to_be_a_shopper(self) -> None:
        order = make_order(order_id="order-1")
        not_a_shopper = build_user(user_id="user-2", user_types=[UserType.CUSTOMER])
        service, _, _, _ = build_service(orders={"order-1": order}, users={"user-2": not_a_shopper})

        with self.assertRaises(FulfillmentStateError):
            await service.assign(order_id="order-1", shopper_id="user-2", actor_user_id="admin-1", note="")

    async def test_assign_succeeds_and_records_history(self) -> None:
        order = make_order(order_id="order-1")
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        service, repo, _, communication = build_service(orders={"order-1": order}, users={"shopper-1": shopper})

        updated = await service.assign(order_id="order-1", shopper_id="shopper-1", actor_user_id="admin-1", note="")

        self.assertEqual(ShopperFulfillmentStatus.ASSIGNED, updated.fulfillment_status)
        self.assertEqual("shopper-1", updated.assigned_worker_id)
        self.assertEqual(1, len(repo.assign_calls))
        self.assertEqual(1, len(communication.assigned_calls))

    async def test_get_for_shopper_raises_not_found_for_non_owner(self) -> None:
        order = make_order(order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.ASSIGNED, assigned_worker_id="shopper-1")
        shopper_two = build_user(user_id="shopper-2", user_types=[UserType.SHOPPER])
        service, _, _, _ = build_service(orders={"order-1": order})

        with self.assertRaises(FulfillmentNotFoundError):
            service.get_for_shopper(current_shopper=shopper_two, order_id="order-1")

    async def test_advance_status_allows_sequential_transition(self) -> None:
        order = make_order(order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.ASSIGNED, assigned_worker_id="shopper-1")
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        service, _, _, _ = build_service(orders={"order-1": order})
        realtime = StubRealtimeDeliveryService()

        with patch.object(shopper_fulfillment_service_module, "realtime_delivery_service", realtime):
            updated = await service.advance_status(current_shopper=shopper, order_id="order-1", status=ShopperFulfillmentStatus.SHOPPING, note="")

        self.assertEqual(ShopperFulfillmentStatus.SHOPPING, updated.fulfillment_status)
        self.assertEqual(1, len(realtime.deliveries))

    async def test_advance_status_rejects_skip_ahead(self) -> None:
        order = make_order(order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.ASSIGNED, assigned_worker_id="shopper-1")
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        service, _, _, _ = build_service(orders={"order-1": order})

        with self.assertRaises(FulfillmentTransitionError):
            await service.advance_status(current_shopper=shopper, order_id="order-1", status=ShopperFulfillmentStatus.PACKED, note="")

    async def test_advance_status_rejects_reverse_transition(self) -> None:
        order = make_order(order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.SHOPPING, assigned_worker_id="shopper-1")
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        service, _, _, _ = build_service(orders={"order-1": order})

        with self.assertRaises(FulfillmentTransitionError):
            await service.advance_status(current_shopper=shopper, order_id="order-1", status=ShopperFulfillmentStatus.ASSIGNED, note="")

    async def test_advance_status_rejects_non_owner(self) -> None:
        order = make_order(order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.ASSIGNED, assigned_worker_id="shopper-1")
        other_shopper = build_user(user_id="shopper-2", user_types=[UserType.SHOPPER])
        service, _, _, _ = build_service(orders={"order-1": order})

        with self.assertRaises(FulfillmentNotFoundError):
            await service.advance_status(current_shopper=other_shopper, order_id="order-1", status=ShopperFulfillmentStatus.SHOPPING, note="")

    async def test_decline_resets_to_unassigned(self) -> None:
        order = make_order(order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.ASSIGNED, assigned_worker_id="shopper-1")
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        service, repo, _, communication = build_service(orders={"order-1": order})

        updated = await service.decline(current_shopper=shopper, order_id="order-1", reason_code="fully_booked", note="")

        self.assertEqual(ShopperFulfillmentStatus.UNASSIGNED, updated.fulfillment_status)
        self.assertIsNone(updated.assigned_worker_id)
        self.assertEqual(1, len(repo.decline_calls))
        self.assertEqual(1, len(communication.declined_calls))

    async def test_list_available_shoppers_filters_by_user_type(self) -> None:
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        customer = build_user(user_id="cust-1", user_types=[UserType.CUSTOMER])
        service, _, _, _ = build_service(users={"shopper-1": shopper, "cust-1": customer})

        shoppers, total = service.list_available_shoppers(page=1, page_size=20)

        self.assertEqual(1, total)
        self.assertEqual("shopper-1", shoppers[0].id)

    async def test_list_shopper_roster_reports_workload_per_shopper(self) -> None:
        shopper = build_user(user_id="shopper-1", user_types=[UserType.SHOPPER])
        active_order = make_order(
            order_id="order-1", fulfillment_status=ShopperFulfillmentStatus.SHOPPING, assigned_worker_id="shopper-1"
        )
        completed_order = make_order(
            order_id="order-2", fulfillment_status=ShopperFulfillmentStatus.PACKED, assigned_worker_id="shopper-1"
        )
        service, _, _, _ = build_service(
            orders={"order-1": active_order, "order-2": completed_order}, users={"shopper-1": shopper}
        )

        roster, total = service.list_shopper_roster(page=1, page_size=20)

        self.assertEqual(1, total)
        self.assertEqual("shopper-1", roster[0]["user"].id)
        self.assertEqual(1, roster[0]["active_count"])
        self.assertEqual(1, roster[0]["completed_this_week"])

    async def test_get_overview_counts_unassigned_and_in_progress(self) -> None:
        unassigned_order = make_order(order_id="order-1")
        in_progress_order = make_order(
            order_id="order-2", fulfillment_status=ShopperFulfillmentStatus.ASSIGNED, assigned_worker_id="shopper-1"
        )
        service, _, _, _ = build_service(orders={"order-1": unassigned_order, "order-2": in_progress_order})

        overview = service.get_overview()

        self.assertEqual(1, overview["unassigned"])
        self.assertEqual(1, overview["in_progress"])


if __name__ == "__main__":
    unittest.main()
