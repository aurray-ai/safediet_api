from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class NotificationCategory(StrEnum):
    PLANNER = "planner"
    ORDER = "order"
    COACH = "coach"
    SYSTEM = "system"
    FULFILLMENT = "fulfillment"
    BILLING = "billing"


class NotificationType(StrEnum):
    UNSAVED_MEAL_PLAN_REMINDER = "unsaved_meal_plan_reminder"
    MEAL_PLAN_APPROVED = "meal_plan_approved"
    MEAL_SLOT_REMINDER = "meal_slot_reminder"
    ORDER_STATUS_UPDATE = "order_status_update"
    COACH_CHECK_IN = "coach_check_in"
    GENERAL = "general"
    ORDER_ASSIGNED_TO_WORKER = "order_assigned_to_worker"
    ORDER_DECLINED_BY_WORKER = "order_declined_by_worker"
    SUBSCRIPTION_STARTED = "subscription_started"
    SUBSCRIPTION_CANCELED = "subscription_canceled"


class NotificationNavigationMode(StrEnum):
    DIRECT = "direct"
    DETAIL = "detail"


@dataclass(frozen=True, slots=True)
class AppNotification:
    id: str
    category: NotificationCategory
    notification_type: NotificationType
    title: str
    message: str
    navigation_mode: NotificationNavigationMode
    recipient_user_ids: list[str]
    read_by_user_ids: list[str]
    target: dict[str, Any]
    details: dict[str, Any]
    metadata: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime
