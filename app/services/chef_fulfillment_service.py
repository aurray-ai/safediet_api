from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.fulfillment import ChefFulfillmentStatus
from app.models.meal_order import MealOrder
from app.models.order import OrderStatus
from app.models.user import User, UserType
from app.repositories.meal_order_repository import MealOrderRepository
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


CHEF_STATUS_ORDER = [
    ChefFulfillmentStatus.ASSIGNED,
    ChefFulfillmentStatus.PREPARING,
    ChefFulfillmentStatus.READY_FOR_DELIVERY,
]


class ChefFulfillmentService:
    def __init__(
        self,
        *,
        meal_order_repository: MealOrderRepository,
        user_repository: UserRepository,
        communication_service: OrderFulfillmentCommunicationService,
    ) -> None:
        self._meal_order_repository = meal_order_repository
        self._user_repository = user_repository
        self._communication_service = communication_service

    # Admin-facing

    def list_unassigned_for_admin(
        self, *, before: str | None, limit: int
    ) -> tuple[list[MealOrder], str | None]:
        return self._meal_order_repository.list_unassigned_for_admin(before=before, limit=limit)

    def get_for_admin(self, *, order_id: str) -> MealOrder:
        order = self._meal_order_repository.get_order(order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        return order

    def list_available_chefs(
        self, *, page: int, page_size: int, search: str | None = None
    ) -> tuple[list[User], int]:
        return self._user_repository.list_users(page=page, page_size=page_size, search=search, user_type=UserType.CHEF)

    def list_chef_roster(
        self, *, page: int, page_size: int, search: str | None = None
    ) -> tuple[list[dict], int]:
        chefs, total = self._user_repository.list_users(
            page=page, page_size=page_size, search=search, user_type=UserType.CHEF
        )
        workload = self._meal_order_repository.count_workload_by_worker(
            worker_ids=[chef.id for chef in chefs], since=_start_of_current_week()
        )
        roster = [
            {
                "user": chef,
                "active_count": workload.get(chef.id, {}).get("active", 0),
                "completed_this_week": workload.get(chef.id, {}).get("completed_this_week", 0),
            }
            for chef in chefs
        ]
        return roster, total

    def get_overview(self) -> dict[str, int]:
        return self._meal_order_repository.get_overview_counts(since=_start_of_current_week())

    async def assign(self, *, order_id: str, chef_id: str, actor_user_id: str | None, note: str) -> MealOrder:
        order = self._meal_order_repository.get_order(order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        if order.status != OrderStatus.CONFIRMED:
            raise FulfillmentStateError("Order must be confirmed before it can be assigned.")
        chef = self._user_repository.find_by_id(chef_id)
        if chef is None or UserType.CHEF not in chef.user_types:
            raise FulfillmentStateError("Target user is not a chef.")
        updated = self._meal_order_repository.assign_worker(
            order_id=order_id,
            worker_id=chef_id,
            actor_user_id=actor_user_id,
            note=note,
        )
        if updated is None:
            raise FulfillmentNotFoundError

        try:
            await self._communication_service.notify_worker_assigned(
                worker_user_id=chef_id,
                track="chef",
                order_id=updated.id,
                order_number=updated.order_number,
                idempotency_key=f"fulfillment_assigned:chef:{updated.id}:{updated.assigned_at.isoformat() if updated.assigned_at else uuid4().hex}",
            )
        except Exception:
            logger.exception("chef_fulfillment.assign_notify_failed order_id=%s chef_id=%s", order_id, chef_id)

        return updated

    # Chef-facing

    def list_mine(self, *, current_chef: User, before: str | None, limit: int) -> tuple[list[MealOrder], str | None]:
        return self._meal_order_repository.list_for_worker(worker_id=current_chef.id, before=before, limit=limit)

    def get_for_chef(self, *, current_chef: User, order_id: str) -> MealOrder:
        order = self._meal_order_repository.get_for_worker(worker_id=current_chef.id, order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        return order

    async def advance_status(
        self,
        *,
        current_chef: User,
        order_id: str,
        status: ChefFulfillmentStatus,
        note: str,
    ) -> MealOrder:
        order = self._meal_order_repository.get_for_worker(worker_id=current_chef.id, order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        _validate_chef_transition(current=order.fulfillment_status, target=status)
        updated = self._meal_order_repository.advance_fulfillment_status(
            order_id=order_id,
            status=status,
            actor_user_id=current_chef.id,
            note=note,
        )
        if updated is None:
            raise FulfillmentNotFoundError

        try:
            await realtime_delivery_service.deliver(
                user_id=current_chef.id,
                delivery_type="fulfillment_status",
                location="chef.orders",
                payload={"order_id": order_id, "status": status.value},
                channels=["websocket"],
            )
        except Exception:
            logger.exception("chef_fulfillment.status_notify_failed order_id=%s chef_id=%s", order_id, current_chef.id)

        return updated

    async def decline(self, *, current_chef: User, order_id: str, reason_code: str, note: str) -> MealOrder:
        order = self._meal_order_repository.get_for_worker(worker_id=current_chef.id, order_id=order_id)
        if order is None:
            raise FulfillmentNotFoundError
        updated = self._meal_order_repository.record_decline(
            order_id=order_id,
            actor_user_id=current_chef.id,
            reason_code=reason_code,
            note=note,
        )
        if updated is None:
            raise FulfillmentNotFoundError

        try:
            await self._communication_service.notify_admin_declined(
                track="chef",
                order_id=updated.id,
                order_number=updated.order_number,
                worker_user_id=current_chef.id,
                reason_code=reason_code,
                idempotency_key=f"fulfillment_declined:chef:{updated.id}:{updated.updated_at.isoformat()}",
            )
        except Exception:
            logger.exception("chef_fulfillment.decline_notify_failed order_id=%s chef_id=%s", order_id, current_chef.id)

        return updated


def _start_of_current_week() -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _validate_chef_transition(*, current: ChefFulfillmentStatus, target: ChefFulfillmentStatus) -> None:
    if current not in CHEF_STATUS_ORDER:
        raise FulfillmentTransitionError("Order is not in an assignable state.")
    if target not in CHEF_STATUS_ORDER:
        raise FulfillmentTransitionError("Invalid target status.")
    current_index = CHEF_STATUS_ORDER.index(current)
    target_index = CHEF_STATUS_ORDER.index(target)
    if target_index != current_index + 1:
        raise FulfillmentTransitionError("Status can only advance one step at a time.")
