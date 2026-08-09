from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from app.models.notification import (
    AppNotification,
    NotificationCategory,
    NotificationNavigationMode,
    NotificationType,
)
from app.models.saved_meal_plan import SavedMealPlan
from app.services import notification_service as notification_service_module
from app.services.notification_service import NotificationService


@dataclass
class StubRealtimeDeliveryService:
    deliveries: list[dict]

    async def deliver(self, **kwargs) -> None:
        self.deliveries.append(kwargs)


class StubNotificationRepository:
    def __init__(self) -> None:
        self.notifications_by_key: dict[str, AppNotification] = {}
        self.created_notifications: list[AppNotification] = []

    def get_by_idempotency_key(self, idempotency_key: str):
        return self.notifications_by_key.get(idempotency_key)

    def create_notification(self, **kwargs) -> AppNotification:
        now = datetime.now(timezone.utc)
        notification = AppNotification(
            id=f"notification-{len(self.created_notifications) + 1}",
            category=kwargs["category"],
            notification_type=kwargs["notification_type"],
            title=kwargs["title"],
            message=kwargs["message"],
            navigation_mode=kwargs["navigation_mode"],
            recipient_user_ids=list(kwargs["recipient_user_ids"]),
            read_by_user_ids=[],
            target=dict(kwargs["target"]),
            details=dict(kwargs["details"]),
            metadata=dict(kwargs["metadata"]),
            idempotency_key=kwargs.get("idempotency_key"),
            created_at=now,
            updated_at=now,
        )
        self.notifications_by_key[notification.idempotency_key] = notification
        self.created_notifications.append(notification)
        return notification

    def unread_count_for_user(self, user_id: str) -> int:
        return 0

    def update_notification_content(self, **kwargs) -> AppNotification | None:
        notification_id = kwargs["notification_id"]
        for index, notification in enumerate(self.created_notifications):
            if notification.id != notification_id:
                continue
            updated = AppNotification(
                id=notification.id,
                category=notification.category,
                notification_type=notification.notification_type,
                title=kwargs["title"],
                message=kwargs["message"],
                navigation_mode=kwargs["navigation_mode"],
                recipient_user_ids=list(notification.recipient_user_ids),
                read_by_user_ids=list(notification.read_by_user_ids),
                target=dict(kwargs["target"]),
                details=dict(kwargs["details"]),
                metadata=dict(kwargs["metadata"]),
                idempotency_key=notification.idempotency_key,
                created_at=notification.created_at,
                updated_at=notification.updated_at,
            )
            self.created_notifications[index] = updated
            self.notifications_by_key[updated.idempotency_key] = updated
            return updated
        return None


class StubSavedMealPlanRepository:
    def __init__(self, plans: list[SavedMealPlan]) -> None:
        self.plans = list(plans)
        self.list_calls: list[dict] = []

    def list_saved_plans(self, **kwargs):
        self.list_calls.append(dict(kwargs))
        plans = list(self.plans)
        status = kwargs.get("status")
        if status is not None:
            plans = [plan for plan in plans if plan.status == status]
        updated_before = kwargs.get("updated_before")
        if updated_before is not None:
            plans = [plan for plan in plans if plan.updated_at < updated_before]
        return plans[: kwargs.get("limit", 20)], len(plans)


class NotificationServiceReminderTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsaved_plan_reminders_use_saved_meal_plan_drafts(self) -> None:
        now = datetime.now(timezone.utc)
        draft_plan = SavedMealPlan(
            id="draft-1",
            user_id="user-1",
            title="Meal Plan",
            status="draft",
            view_mode="week",
            plan_scope="weekly_parent",
            effective_date=now.date(),
            week_start=now.date(),
            week_end=now.date() + timedelta(days=6),
            day_index=None,
            parent_saved_plan_id=None,
            source_saved_plan_id=None,
            linked_day_plan_ids=[],
            meal_type=None,
            country_code=None,
            planned_meals=[],
            plan_payload={
                "snapshot_id": "snapshot-draft-1",
                "title": "Meal Plan",
                "view_mode": "week",
                "state": "draft",
                "period_label": "This Week",
                "days": [
                    {
                        "date": now.date().isoformat(),
                        "sections": [
                            {
                                "slot": "breakfast",
                                "items": [
                                    {
                                        "meal_id": "meal-1",
                                        "name": "Berry Oats",
                                        "hero_image_url": "https://example.com/berry-oats.jpg",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            requested_culture=None,
            user_goal=None,
            source_snapshot_id="snapshot-draft-1",
            source_conversation_id="direct-planner",
            agent_type="meal_planner_agent",
            created_at=now - timedelta(minutes=20),
            updated_at=now - timedelta(minutes=20),
        )
        saved_plan = SavedMealPlan(
            id="saved-1",
            user_id="user-1",
            title="Meal Plan",
            status="saved",
            view_mode="day",
            plan_scope="standalone_day",
            effective_date=now.date(),
            week_start=None,
            week_end=None,
            day_index=None,
            parent_saved_plan_id=None,
            source_saved_plan_id=None,
            linked_day_plan_ids=[],
            meal_type=None,
            country_code=None,
            planned_meals=[],
            plan_payload={
                "snapshot_id": "snapshot-saved-1",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "saved",
            },
            requested_culture=None,
            user_goal=None,
            source_snapshot_id="snapshot-saved-1",
            source_conversation_id="direct-planner",
            agent_type="meal_planner_agent",
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
        )

        notification_repo = StubNotificationRepository()
        saved_repo = StubSavedMealPlanRepository([draft_plan, saved_plan])
        realtime = StubRealtimeDeliveryService(deliveries=[])
        service = NotificationService(
            notification_repository=notification_repo,
            saved_meal_plan_repository=saved_repo,
        )

        with patch.object(notification_service_module, "realtime_delivery_service", realtime):
            await service.scan_and_deliver_unsaved_plan_reminders(scan_limit=10)

        self.assertEqual(1, len(notification_repo.created_notifications))
        created = notification_repo.created_notifications[0]
        self.assertEqual(NotificationType.UNSAVED_MEAL_PLAN_REMINDER, created.notification_type)
        self.assertEqual("draft-1", created.target["saved_plan_id"])
        self.assertEqual("ios.home", created.target["location"])
        self.assertEqual("draft", created.details["status"])
        self.assertEqual(1, len(realtime.deliveries))
        self.assertEqual("notification", realtime.deliveries[0]["delivery_type"])
        self.assertEqual("draft-1", realtime.deliveries[0]["payload"]["notification"]["target"]["saved_plan_id"])
        self.assertEqual(
            "https://example.com/berry-oats.jpg",
            realtime.deliveries[0]["push_payload"]["notification_image_url"],
        )

    async def test_meal_slot_reminder_targets_home_meal_detail(self) -> None:
        notification_repo = StubNotificationRepository()
        realtime = StubRealtimeDeliveryService(deliveries=[])
        service = NotificationService(
            notification_repository=notification_repo,
            saved_meal_plan_repository=StubSavedMealPlanRepository([]),
        )

        meal_item = {
            "meal_id": "meal-42",
            "name": "Greek Yogurt Bowl",
            "hero_image_url": "https://example.com/meal.jpg",
        }

        with patch.object(notification_service_module, "realtime_delivery_service", realtime):
            await service.create_and_deliver_meal_slot_reminder(
                user_id="user-1",
                conversation_id="conversation-1",
                saved_plan_id="saved-day-1",
                snapshot_id="snapshot-day-1",
                effective_date="2026-06-27",
                meal_slot="breakfast",
                meal_name="Greek Yogurt Bowl",
                section_title="Breakfast",
                meal_item=meal_item,
                time_label="this morning",
                message_id="message-1",
                ui_block_id="block-1",
            )

        self.assertEqual(1, len(notification_repo.created_notifications))
        created = notification_repo.created_notifications[0]
        self.assertEqual(NotificationType.MEAL_SLOT_REMINDER, created.notification_type)
        self.assertEqual("ios.home", created.target["location"])
        self.assertEqual("meal_slot_detail", created.target["target_kind"])
        self.assertEqual("meal_detail", created.target["notification_focus"])
        self.assertEqual("breakfast", created.target["meal_slot"])
        self.assertEqual("meal-42", created.target["meal_id"])
        self.assertEqual(meal_item, created.target["meal_item"])
        self.assertEqual("conversation-1", created.details["conversation_id"])
        self.assertEqual(1, len(realtime.deliveries))
        self.assertEqual("ios.notifications", realtime.deliveries[0]["location"])
        self.assertEqual(
            "meal_slot_detail",
            realtime.deliveries[0]["push_payload"]["target"]["target_kind"],
        )
        self.assertEqual(
            "https://example.com/meal.jpg",
            realtime.deliveries[0]["push_payload"]["notification_image_url"],
        )
