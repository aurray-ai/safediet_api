from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService


@dataclass(frozen=True, slots=True)
class MealSlotReminderWindow:
    slot: str
    start_hour: int
    end_hour: int
    time_label: str


class MealScheduleReminderService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        meal_conversation_repository: MealConversationRepository,
        saved_meal_plan_repository: SavedMealPlanRepository,
        notification_service: NotificationService,
        default_timezone_name: str = "Europe/London",
        reminder_windows: tuple[MealSlotReminderWindow, ...] | None = None,
    ) -> None:
        self._user_repository = user_repository
        self._meal_conversation_repository = meal_conversation_repository
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._notification_service = notification_service
        self._default_timezone_name = default_timezone_name
        self._windows = reminder_windows or self.default_windows()

    @classmethod
    def default_windows(cls) -> tuple[MealSlotReminderWindow, ...]:
        return (
            MealSlotReminderWindow(slot="breakfast", start_hour=5, end_hour=10, time_label="this morning"),
            MealSlotReminderWindow(slot="lunch", start_hour=11, end_hour=15, time_label="this afternoon"),
            MealSlotReminderWindow(slot="snack", start_hour=16, end_hour=16, time_label="later today"),
            MealSlotReminderWindow(slot="dinner", start_hour=17, end_hour=21, time_label="this evening"),
        )

    @classmethod
    def windows_from_settings(cls, settings: Any) -> tuple[MealSlotReminderWindow, ...]:
        windows: list[MealSlotReminderWindow] = [
            MealSlotReminderWindow(
                slot="breakfast",
                start_hour=int(settings.background_meal_slot_breakfast_start_hour),
                end_hour=int(settings.background_meal_slot_breakfast_end_hour),
                time_label="this morning",
            ),
            MealSlotReminderWindow(
                slot="lunch",
                start_hour=int(settings.background_meal_slot_lunch_start_hour),
                end_hour=int(settings.background_meal_slot_lunch_end_hour),
                time_label="this afternoon",
            ),
            MealSlotReminderWindow(
                slot="snack",
                start_hour=int(settings.background_meal_slot_snack_start_hour),
                end_hour=int(settings.background_meal_slot_snack_end_hour),
                time_label="later today",
            ),
        ]
        windows.append(
            MealSlotReminderWindow(
                slot="dinner",
                start_hour=int(settings.background_meal_slot_dinner_start_hour),
                end_hour=int(settings.background_meal_slot_dinner_end_hour),
                time_label="this evening",
            )
        )
        return tuple(windows)

    async def scan_and_deliver_current_slot_reminders(
        self,
        *,
        scan_limit: int = 500,
        now: datetime | None = None,
    ) -> None:
        reference_now = now or datetime.now(timezone.utc)
        candidate_dates = [reference_now.date() + timedelta(days=offset) for offset in (-1, 0, 1)]
        plans = self._saved_meal_plan_repository.list_saved_day_plans_for_effective_dates(
            effective_dates=candidate_dates,
            limit=scan_limit,
        )
        plans = [plan for plan in plans if plan.status == "saved"]
        if not plans:
            return

        latest_plans_by_user_date = self._latest_plans_by_user_date(plans)
        users = {
            user.id: user
            for user in self._user_repository.list_by_ids(
                list({plan.user_id for plan in latest_plans_by_user_date.values()})
            )
        }
        for user_id, user in users.items():
            local_now = reference_now.astimezone(self._resolve_timezone(user))
            plan_reminder_time = self._plan_reminder_time(user)
            window = self._due_window_for_user(
                local_now=local_now,
                plan_reminder_time=plan_reminder_time,
                scan_interval_minutes=max(int(scan_limit * 0) + 20, 1),
            )
            if window is None:
                continue

            plan = latest_plans_by_user_date.get((user_id, local_now.date()))
            if plan is None:
                continue

            section = self._find_slot_section(plan.plan_payload, slot=window.slot)
            if section is None:
                continue

            meal_item = self._extract_primary_meal_item(section)
            if meal_item is None:
                continue
            meal_name = str(meal_item.get("name") or "").strip()
            if not meal_name:
                continue
            section_title = str(section.get("title") or "").strip() or window.slot.replace("_", " ").title()

            snapshot_id = self._notification_snapshot_id(plan)
            message_id, ui_block_id = self._meal_conversation_repository.find_latest_message_block_by_snapshot_id(
                conversation_id=plan.source_conversation_id,
                snapshot_id=snapshot_id,
            )
            await self._notification_service.create_and_deliver_meal_slot_reminder(
                user_id=user.id,
                conversation_id=plan.source_conversation_id,
                saved_plan_id=plan.id,
                snapshot_id=snapshot_id,
                effective_date=plan.effective_date.isoformat() if plan.effective_date else None,
                meal_slot=window.slot,
                meal_name=meal_name,
                section_title=section_title,
                meal_item=meal_item,
                time_label=window.time_label,
                message_id=message_id,
                ui_block_id=ui_block_id,
            )

    def _latest_plans_by_user_date(
        self,
        plans: list[SavedMealPlan],
    ) -> dict[tuple[str, date], SavedMealPlan]:
        results: dict[tuple[str, date], SavedMealPlan] = {}
        for plan in plans:
            if plan.effective_date is None:
                continue
            key = (plan.user_id, plan.effective_date)
            existing = results.get(key)
            if existing is None or plan.updated_at > existing.updated_at:
                results[key] = plan
        return results

    def _resolve_timezone(self, user: User) -> ZoneInfo:
        configuration = dict(user.user_configuration or {})
        timezone_name = str(configuration.get("timezone") or "").strip() or self._default_timezone_name
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo(self._default_timezone_name)

    def _due_window_for_user(
        self,
        *,
        local_now: datetime,
        plan_reminder_time: dict[str, str | None],
        scan_interval_minutes: int,
    ) -> MealSlotReminderWindow | None:
        current_minutes = (local_now.hour * 60) + local_now.minute
        previous_minutes = current_minutes - scan_interval_minutes
        for window in self._windows:
            configured = str(plan_reminder_time.get(window.slot) or "").strip()
            if not configured:
                continue
            target_minutes = self._parse_time_to_minutes(configured)
            if target_minutes is None:
                continue
            if previous_minutes < 0:
                if target_minutes <= current_minutes or target_minutes > (24 * 60 + previous_minutes):
                    return window
            elif previous_minutes < target_minutes <= current_minutes:
                return window
        return None

    @staticmethod
    def _parse_time_to_minutes(value: str) -> int | None:
        parts = value.split(":")
        if len(parts) != 2:
            return None
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return None
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return (hour * 60) + minute

    @staticmethod
    def _plan_reminder_time(user: User) -> dict[str, str | None]:
        configuration = dict(user.user_configuration or {})
        raw = dict(configuration.get("plan_reminder_time") or {})
        return {
            "breakfast": str(raw.get("breakfast") or "07:00"),
            "lunch": str(raw.get("lunch") or "13:00"),
            "dinner": str(raw.get("dinner") or "19:00"),
            "snack": str(raw.get("snack")).strip() if raw.get("snack") is not None else None,
        }

    @staticmethod
    def _find_slot_section(plan_payload: dict[str, Any], *, slot: str) -> dict[str, Any] | None:
        normalized_slot = slot.strip().lower()
        for section in list(plan_payload.get("sections") or []):
            section_slot = str(section.get("slot") or "").strip().lower()
            if section_slot == normalized_slot:
                return dict(section)
        return None

    @staticmethod
    def _extract_primary_meal_item(section: dict[str, Any]) -> dict[str, Any] | None:
        items = list(section.get("items") or [])
        for item in items:
            payload = dict(item or {})
            meal_name = str(payload.get("name") or "").strip()
            if meal_name:
                return payload
        return None

    @staticmethod
    def _notification_snapshot_id(plan: SavedMealPlan) -> str:
        parent_snapshot_id = str(plan.plan_payload.get("parent_weekly_snapshot_id") or "").strip()
        if parent_snapshot_id:
            return parent_snapshot_id
        return plan.source_snapshot_id
