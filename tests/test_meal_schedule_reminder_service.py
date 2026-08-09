from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import unittest

from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.services.meal_schedule_reminder_service import (
    MealScheduleReminderService,
    MealSlotReminderWindow,
)


class StubUserRepository:
    def __init__(self, users: list[User]) -> None:
        self._users = {user.id: user for user in users}

    def list_by_ids(self, user_ids: list[str]) -> list[User]:
        return [self._users[user_id] for user_id in user_ids if user_id in self._users]


class StubSavedMealPlanRepository:
    def __init__(self, plans: list[SavedMealPlan]) -> None:
        self._plans = list(plans)

    def list_saved_day_plans_for_effective_dates(
        self,
        *,
        effective_dates: list[date],
        limit: int = 500,
    ) -> list[SavedMealPlan]:
        allowed = set(effective_dates)
        return [plan for plan in self._plans if plan.effective_date in allowed][:limit]


class StubMealConversationRepository:
    def __init__(self, message_id: str | None = None, ui_block_id: str | None = None) -> None:
        self._message_id = message_id
        self._ui_block_id = ui_block_id

    def find_latest_message_block_by_snapshot_id(
        self,
        *,
        conversation_id: str,
        snapshot_id: str,
    ) -> tuple[str | None, str | None]:
        return self._message_id, self._ui_block_id


@dataclass
class RecordedMealSlotReminder:
    user_id: str
    conversation_id: str
    saved_plan_id: str
    snapshot_id: str
    effective_date: str | None
    meal_slot: str
    meal_name: str
    section_title: str | None
    meal_item: dict[str, object] | None
    time_label: str
    message_id: str | None = None
    ui_block_id: str | None = None


class StubNotificationService:
    def __init__(self) -> None:
        self.calls: list[RecordedMealSlotReminder] = []

    async def create_and_deliver_meal_slot_reminder(self, **kwargs) -> None:
        self.calls.append(RecordedMealSlotReminder(**kwargs))


class MealScheduleReminderServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_delivers_reminder_for_matching_slot(self) -> None:
        user = User(
            id="user-1",
            name="Test User",
            email="test@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={"timezone": "UTC"},
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        plan = SavedMealPlan(
            id="saved-day-1",
            user_id="user-1",
            title="Meal Plan",
            status="saved",
            view_mode="day",
            plan_scope=None,
            effective_date=date(2026, 6, 21),
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
                "sections": [
                    {
                        "slot": "breakfast",
                        "title": "Breakfast",
                        "items": [
                            {
                                "meal_id": "meal-1",
                                "name": "Greek Yogurt Bowl",
                                "hero_image_url": "https://example.com/yogurt.jpg",
                            }
                        ],
                    }
                ]
            },
            requested_culture=None,
            user_goal=None,
            source_snapshot_id="snapshot-day-1",
            source_conversation_id="conversation-1",
            agent_type="meal_coordinator",
            created_at=datetime(2026, 6, 21, 7, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 21, 7, 5, tzinfo=timezone.utc),
        )
        notification_service = StubNotificationService()
        service = MealScheduleReminderService(
            user_repository=StubUserRepository([user]),
            meal_conversation_repository=StubMealConversationRepository("message-1", "block-1"),
            saved_meal_plan_repository=StubSavedMealPlanRepository([plan]),
            notification_service=notification_service,
            default_timezone_name="Europe/London",
        )

        await service.scan_and_deliver_current_slot_reminders(
            now=datetime(2026, 6, 21, 7, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(1, len(notification_service.calls))
        call = notification_service.calls[0]
        self.assertEqual("breakfast", call.meal_slot)
        self.assertEqual("Greek Yogurt Bowl", call.meal_name)
        self.assertEqual("snapshot-day-1", call.snapshot_id)
        self.assertEqual("this morning", call.time_label)
        self.assertEqual("message-1", call.message_id)
        self.assertEqual("block-1", call.ui_block_id)
        self.assertEqual("Breakfast", call.section_title)
        self.assertEqual("meal-1", call.meal_item["meal_id"])

    async def test_scan_uses_parent_weekly_snapshot_for_child_day_plan(self) -> None:
        user = User(
            id="user-2",
            name="Test User",
            email="test2@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={"timezone": "UTC"},
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        plan = SavedMealPlan(
            id="saved-day-2",
            user_id="user-2",
            title="Meal Plan",
            status="saved",
            view_mode="day",
            plan_scope=None,
            effective_date=date(2026, 6, 21),
            week_start=date(2026, 6, 21),
            week_end=date(2026, 6, 27),
            day_index=0,
            parent_saved_plan_id="saved-week-1",
            source_saved_plan_id=None,
            linked_day_plan_ids=[],
            meal_type=None,
            country_code=None,
            planned_meals=[],
            plan_payload={
                "parent_weekly_snapshot_id": "snapshot-week-1",
                "sections": [
                    {
                        "slot": "dinner",
                        "items": [{"name": "Chicken Stir Fry"}],
                    }
                ],
            },
            requested_culture=None,
            user_goal=None,
            source_snapshot_id="snapshot-day-2",
            source_conversation_id="conversation-2",
            agent_type="meal_coordinator",
            created_at=datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 21, 16, 10, tzinfo=timezone.utc),
        )
        notification_service = StubNotificationService()
        service = MealScheduleReminderService(
            user_repository=StubUserRepository([user]),
            meal_conversation_repository=StubMealConversationRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository([plan]),
            notification_service=notification_service,
            default_timezone_name="Europe/London",
        )

        await service.scan_and_deliver_current_slot_reminders(
            now=datetime(2026, 6, 21, 19, 10, tzinfo=timezone.utc)
        )

        self.assertEqual(1, len(notification_service.calls))
        self.assertEqual("snapshot-week-1", notification_service.calls[0].snapshot_id)

    async def test_scan_supports_optional_snack_window(self) -> None:
        user = User(
            id="user-3",
            name="Test User",
            email="test3@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={
                "timezone": "UTC",
                "plan_reminder_time": {
                    "breakfast": "07:00",
                    "lunch": "13:00",
                    "dinner": "19:00",
                    "snack": "15:00",
                },
            },
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        plan = SavedMealPlan(
            id="saved-day-3",
            user_id="user-3",
            title="Meal Plan",
            status="saved",
            view_mode="day",
            plan_scope=None,
            effective_date=date(2026, 6, 21),
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
                "sections": [
                    {
                        "slot": "snack",
                        "items": [{"name": "Apple with Peanut Butter"}],
                    }
                ]
            },
            requested_culture=None,
            user_goal=None,
            source_snapshot_id="snapshot-day-3",
            source_conversation_id="conversation-3",
            agent_type="meal_coordinator",
            created_at=datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 21, 14, 10, tzinfo=timezone.utc),
        )
        notification_service = StubNotificationService()
        service = MealScheduleReminderService(
            user_repository=StubUserRepository([user]),
            meal_conversation_repository=StubMealConversationRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository([plan]),
            notification_service=notification_service,
            default_timezone_name="Europe/London",
            reminder_windows=(
                MealSlotReminderWindow("breakfast", 5, 10, "this morning"),
                MealSlotReminderWindow("lunch", 11, 14, "this afternoon"),
                MealSlotReminderWindow("snack", 15, 15, "later today"),
                MealSlotReminderWindow("dinner", 17, 21, "this evening"),
            ),
        )

        await service.scan_and_deliver_current_slot_reminders(
            now=datetime(2026, 6, 21, 15, 5, tzinfo=timezone.utc)
        )

        self.assertEqual(1, len(notification_service.calls))
        self.assertEqual("snack", notification_service.calls[0].meal_slot)
        self.assertEqual("later today", notification_service.calls[0].time_label)

    async def test_scan_uses_user_specific_reminder_time(self) -> None:
        user = User(
            id="user-4",
            name="Test User",
            email="test4@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={
                "timezone": "UTC",
                "plan_reminder_time": {
                    "breakfast": "09:10",
                    "lunch": "13:00",
                    "dinner": "19:00",
                    "snack": None,
                },
            },
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        plan = SavedMealPlan(
            id="saved-day-4",
            user_id="user-4",
            title="Meal Plan",
            status="saved",
            view_mode="day",
            plan_scope=None,
            effective_date=date(2026, 6, 21),
            week_start=None,
            week_end=None,
            day_index=None,
            parent_saved_plan_id=None,
            source_saved_plan_id=None,
            linked_day_plan_ids=[],
            meal_type=None,
            country_code=None,
            planned_meals=[],
            plan_payload={"sections": [{"slot": "breakfast", "items": [{"name": "Egg Wrap"}]}]},
            requested_culture=None,
            user_goal=None,
            source_snapshot_id="snapshot-day-4",
            source_conversation_id="conversation-4",
            agent_type="meal_coordinator",
            created_at=datetime(2026, 6, 21, 7, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 21, 7, 5, tzinfo=timezone.utc),
        )
        notification_service = StubNotificationService()
        service = MealScheduleReminderService(
            user_repository=StubUserRepository([user]),
            meal_conversation_repository=StubMealConversationRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository([plan]),
            notification_service=notification_service,
            default_timezone_name="Europe/London",
        )

        await service.scan_and_deliver_current_slot_reminders(
            now=datetime(2026, 6, 21, 8, 55, tzinfo=timezone.utc)
        )
        self.assertEqual(0, len(notification_service.calls))

        await service.scan_and_deliver_current_slot_reminders(
            now=datetime(2026, 6, 21, 9, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(1, len(notification_service.calls))
        self.assertEqual("breakfast", notification_service.calls[0].meal_slot)
