from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.fulfillment import ShopperFulfillmentStatus
from app.models.order import Order, OrderStatus
from app.models.user import User, UserType
from app.repositories.order_repository import OrderRepository
from app.repositories.user_repository import UserRepository
from app.services.order_fulfillment_communication_service import OrderFulfillmentCommunicationService
from app.services.realtime_delivery_service import realtime_delivery_service

logger = logging.getLogger(__name__)


class FulfillmentNotFoundError(Exception):
    pass


class FulfillmentStateError(Exception):
    pass


class FulfillmentTransitionError(Exception):
    pass


SHOPPER_STATUS_ORDER = [
    ShopperFulfillmentStatus.ASSIGNED,
    ShopperFulfillmentStatus.SHOPPING,
    ShopperFulfillmentStatus.PACKED,
]


class ShopperFulfillmentService:
    def __init__(
        self,
        *,
        order_repository: OrderRepository,
        user_repository: UserRepository,
        communication_service: OrderFulfillmentCommunicationService,
    ) -> None:
        self._order_repository = order_repository
        self._user_repository = user_repository
        self._communication_service = communication_service

    # Admin-facing

    def list_unassigned_for_admin(self, *, before: str | None, limit: int) -> tuple[list[Order], str | None]:
        return self._order_repository.list_unassigned_for_admin(before=before, limit=limit)

    def get_for_admin(self, *, order_id: str) -> Order:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        return order

    def list_available_shoppers(
        self, *, page: int, page_size: int, search: str | None = None
    ) -> tuple[list[User], int]:
        return self._user_repository.list_users(page=page, page_size=page_size, search=search, user_type=UserType.SHOPPER)

    def list_shopper_roster(
        self, *, page: int, page_size: int, search: str | None = None
    ) -> tuple[list[dict], int]:
        shoppers, total = self._user_repository.list_users(
            page=page, page_size=page_size, search=search, user_type=UserType.SHOPPER
        )
        workload = self._order_repository.count_workload_by_worker(
            worker_ids=[shopper.id for shopper in shoppers], since=_start_of_current_week()
        )
        roster = [
            {
                "user": shopper,
                "active_count": workload.get(shopper.id, {}).get("active", 0),
                "completed_this_week": workload.get(shopper.id, {}).get("completed_this_week", 0),
            }
            for shopper in shoppers
        ]
        return roster, total

    def get_overview(self) -> dict[str, int]:
        return self._order_repository.get_overview_counts(since=_start_of_current_week())

    async def assign(self, *, order_id: str, shopper_id: str, actor_user_id: str | None, note: str) -> Order:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        if order.status != OrderStatus.CONFIRMED:
            raise FulfillmentStateError("Order must be confirmed before it can be assigned.")
        shopper = self._user_repository.find_by_id(shopper_id)
        if shopper is None or UserType.SHOPPER not in shopper.user_types:
            raise FulfillmentStateError("Target user is not a shopper.")
        updated = self._order_repository.assign_worker(
            order_id=order_id,
            worker_id=shopper_id,
            actor_user_id=actor_user_id,
            note=note,
        )
        if updated is None:
            raise FulfillmentNotFoundError

        try:
            await self._communication_service.notify_worker_assigned(
                worker_user_id=shopper_id,
                track="shopper",
                order_id=updated.id,
                order_number=updated.order_number,
                idempotency_key=f"fulfillment_assigned:shopper:{updated.id}:{updated.assigned_at.isoformat() if updated.assigned_at else uuid4().hex}",
            )
        except Exception:
            logger.exception("shopper_fulfillment.assign_notify_failed order_id=%s shopper_id=%s", order_id, shopper_id)

        return updated

    # Shopper-facing

    def list_mine(self, *, current_shopper: User, before: str | None, limit: int) -> tuple[list[Order], str | None]:
        return self._order_repository.list_for_worker(worker_id=current_shopper.id, before=before, limit=limit)

    def get_for_shopper(self, *, current_shopper: User, order_id: str) -> Order:
        order = self._order_repository.get_for_worker(worker_id=current_shopper.id, order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        return order

    async def advance_status(
        self,
        *,
        current_shopper: User,
        order_id: str,
        status: ShopperFulfillmentStatus,
        note: str,
    ) -> Order:
        order = self._order_repository.get_for_worker(worker_id=current_shopper.id, order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        _validate_shopper_transition(current=order.fulfillment_status, target=status)
        updated = self._order_repository.advance_fulfillment_status(
            order_id=order_id,
            status=status,
            actor_user_id=current_shopper.id,
            note=note,
        )
        if updated is None:
            raise FulfillmentNotFoundError

        try:
            await realtime_delivery_service.deliver(
                user_id=current_shopper.id,
                delivery_type="fulfillment_status",
                location="shopper.orders",
                payload={"order_id": order_id, "status": status.value},
                channels=["websocket"],
            )
        except Exception:
            logger.exception("shopper_fulfillment.status_notify_failed order_id=%s shopper_id=%s", order_id, current_shopper.id)

        return updated

    async def decline(self, *, current_shopper: User, order_id: str, reason_code: str, note: str) -> Order:
        order = self._order_repository.get_for_worker(worker_id=current_shopper.id, order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        updated = self._order_repository.record_decline(
            order_id=order_id,
            actor_user_id=current_shopper.id,
            reason_code=reason_code,
            note=note,
        )
        if updated is None:
            raise FulfillmentNotFoundError

        try:
            await self._communication_service.notify_admin_declined(
                track="shopper",
                order_id=updated.id,
                order_number=updated.order_number,
                worker_user_id=current_shopper.id,
                reason_code=reason_code,
                idempotency_key=f"fulfillment_declined:shopper:{updated.id}:{updated.updated_at.isoformat()}",
            )
        except Exception:
            logger.exception("shopper_fulfillment.decline_notify_failed order_id=%s shopper_id=%s", order_id, current_shopper.id)

        return updated


def _start_of_current_week() -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _validate_shopper_transition(*, current: ShopperFulfillmentStatus, target: ShopperFulfillmentStatus) -> None:
    if current not in SHOPPER_STATUS_ORDER:
        raise FulfillmentTransitionError("Order is not in an assignable state.")
    if target not in SHOPPER_STATUS_ORDER:
        raise FulfillmentTransitionError("Invalid target status.")
    current_index = SHOPPER_STATUS_ORDER.index(current)
    target_index = SHOPPER_STATUS_ORDER.index(target)
    if target_index != current_index + 1:
        raise FulfillmentTransitionError("Status can only advance one step at a time.")
