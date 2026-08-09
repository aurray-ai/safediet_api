from datetime import date, timedelta
from typing import Any

from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User
from app.models.user_meal_usage import UserMealUsageEntry
from app.repositories.user_meal_usage_repository import UserMealUsageRepository
from app.schemas.user_meal_usage import (
    UserMealUsageDayOverviewResponse,
    UserMealUsageOverviewResponse,
    UserMealUsageWeekHistoryItemResponse,
    UserMealUsageWeekHistoryResponse,
    UserMealUsageWeekOverviewResponse,
)
from app.services.goal_target_service import GoalTargetService


class UserMealUsageService:
    def __init__(
        self,
        *,
        user_meal_usage_repository: UserMealUsageRepository,
        goal_target_service: GoalTargetService,
    ) -> None:
        self._user_meal_usage_repository = user_meal_usage_repository
        self._goal_target_service = goal_target_service

    def sync_saved_day_plan(self, *, saved_plan: SavedMealPlan) -> list[UserMealUsageEntry]:
        if saved_plan.view_mode != "day" or saved_plan.effective_date is None:
            return []

        normalized_entries = self._normalize_saved_plan_entries(saved_plan=saved_plan)
        return self._user_meal_usage_repository.replace_day_entries(
            user_id=saved_plan.user_id,
            effective_date=saved_plan.effective_date,
            saved_plan_id=saved_plan.id,
            source_snapshot_id=saved_plan.source_snapshot_id,
            source_conversation_id=saved_plan.source_conversation_id,
            entries=normalized_entries,
        )

    def get_overview(
        self,
        *,
        current_user: User,
        on_date: date | None = None,
    ) -> UserMealUsageOverviewResponse:
        resolved_date = on_date or date.today()
        week_start = self._week_start(resolved_date)
        week_end = week_start + timedelta(days=6)
        entries = self._user_meal_usage_repository.list_entries_between(
            user_id=current_user.id,
            start_date=week_start,
            end_date=week_end,
        )
        today_entries = [entry for entry in entries if entry.effective_date == resolved_date]
        targets = self._goal_target_service.calculate_from_user_configuration(
            current_user.user_configuration or {}
        )
        configured_weekly_budget = self._normalized_int(
            (current_user.user_configuration or {}).get("weekly_budget")
        ) or 0
        day_totals = self._sum_entries(today_entries)
        week_totals = self._sum_entries(entries)
        currency_code = next(
            (entry.currency_code for entry in entries if entry.currency_code),
            None,
        )
        return UserMealUsageOverviewResponse(
            today=UserMealUsageDayOverviewResponse(
                date=resolved_date,
                target_calories=targets.daily_calories,
                planned_calories=day_totals["calories"],
                remaining_calories=targets.daily_calories - day_totals["calories"],
                target_protein_g=targets.protein_g,
                planned_protein_g=round(day_totals["protein_g"], 1),
                remaining_protein_g=round(targets.protein_g - day_totals["protein_g"], 1),
                target_carbs_g=targets.carbs_g,
                planned_carbs_g=round(day_totals["carbs_g"], 1),
                remaining_carbs_g=round(targets.carbs_g - day_totals["carbs_g"], 1),
                target_fat_g=targets.fat_g,
                planned_fat_g=round(day_totals["fat_g"], 1),
                remaining_fat_g=round(targets.fat_g - day_totals["fat_g"], 1),
            ),
            week=UserMealUsageWeekOverviewResponse(
                week_start=week_start,
                week_end=week_end,
                target_weekly_budget=configured_weekly_budget,
                planned_spend=round(week_totals["estimated_cost"], 2),
                remaining_budget=round(configured_weekly_budget - week_totals["estimated_cost"], 2),
                currency_code=currency_code,
            ),
        )

    def list_week_history(
        self,
        *,
        current_user: User,
        limit: int,
        end_date: date | None = None,
    ) -> UserMealUsageWeekHistoryResponse:
        resolved_end_date = end_date or date.today()
        latest_week_start = self._week_start(resolved_end_date)
        earliest_week_start = latest_week_start - timedelta(days=(limit - 1) * 7)
        fetch_end = latest_week_start + timedelta(days=6)
        entries = self._user_meal_usage_repository.list_entries_between(
            user_id=current_user.id,
            start_date=earliest_week_start,
            end_date=fetch_end,
        )
        grouped: dict[date, list[UserMealUsageEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.week_start, []).append(entry)

        targets = self._goal_target_service.calculate_from_user_configuration(
            current_user.user_configuration or {}
        )
        configured_weekly_budget = self._normalized_int(
            (current_user.user_configuration or {}).get("weekly_budget")
        ) or 0
        items: list[UserMealUsageWeekHistoryItemResponse] = []
        for index in range(limit):
            week_start = latest_week_start - timedelta(days=index * 7)
            week_entries = grouped.get(week_start, [])
            totals = self._sum_entries(week_entries)
            active_days = len({entry.effective_date for entry in week_entries})
            currency_code = next(
                (entry.currency_code for entry in week_entries if entry.currency_code),
                None,
            )
            items.append(
                UserMealUsageWeekHistoryItemResponse(
                    week_start=week_start,
                    week_end=week_start + timedelta(days=6),
                    target_weekly_budget=configured_weekly_budget,
                    planned_spend=round(totals["estimated_cost"], 2),
                    remaining_budget=round(configured_weekly_budget - totals["estimated_cost"], 2),
                    planned_calories=totals["calories"],
                    planned_protein_g=round(totals["protein_g"], 1),
                    planned_carbs_g=round(totals["carbs_g"], 1),
                    planned_fat_g=round(totals["fat_g"], 1),
                    days_with_saved_meals=active_days,
                    average_daily_calories=round(
                        totals["calories"] / active_days,
                        1,
                    ) if active_days else 0.0,
                    currency_code=currency_code,
                )
            )
        return UserMealUsageWeekHistoryResponse(items=items)

    def _normalize_saved_plan_entries(
        self,
        *,
        saved_plan: SavedMealPlan,
    ) -> list[dict[str, Any]]:
        payload = dict(saved_plan.plan_payload or {})
        sections = list(payload.get("sections") or [])
        normalized_entries: list[dict[str, Any]] = []

        for section in sections:
            slot = str(section.get("slot") or "").strip().lower()
            if slot not in {"breakfast", "lunch", "dinner", "snack"}:
                continue

            items = list(section.get("items") or [])
            meal_names: list[str] = []
            calories_total = 0
            protein_total = 0.0
            carbs_total = 0.0
            fat_total = 0.0
            estimated_cost_total = 0.0
            has_known_cost = False
            currency_code = None
            meal_source = None

            for item in items:
                item_payload = dict(item or {})
                meal_detail = dict(item_payload.get("meal_detail") or {})
                meal_source = meal_source or str(item_payload.get("meal_source") or "").strip() or None
                meal_name = str(
                    meal_detail.get("name")
                    or item_payload.get("name")
                    or ""
                ).strip()
                if meal_name and meal_name not in meal_names:
                    meal_names.append(meal_name)

                nutrition = dict(meal_detail.get("estimated_nutrition_per_serving") or {})
                calories_total += self._normalized_int(
                    nutrition.get("calories")
                ) or self._normalized_int(item_payload.get("calories")) or 0
                protein_total += self._normalized_float(nutrition.get("protein_g")) or 0.0
                carbs_total += self._normalized_float(nutrition.get("carbs_g")) or 0.0
                fat_total += self._normalized_float(nutrition.get("fat_g")) or 0.0

                estimated_cost = self._normalized_float(meal_detail.get("estimated_cost_gbp"))
                if estimated_cost is None:
                    nested_cost = dict(meal_detail.get("estimated_cost") or {})
                    nested_currency = str(nested_cost.get("currency_code") or "").upper()
                    if nested_currency == "GBP":
                        estimated_cost = self._normalized_float(nested_cost.get("amount"))
                        currency_code = currency_code or nested_currency
                else:
                    currency_code = currency_code or "GBP"

                if estimated_cost is not None:
                    has_known_cost = True
                    estimated_cost_total += estimated_cost

            if calories_total == 0:
                calories_total = self._normalized_int(section.get("calories")) or 0

            normalized_entries.append(
                {
                    "view_mode": saved_plan.view_mode,
                    "meal_slot": slot,
                    "meal_name": " + ".join(meal_names)[:240]
                    or str(section.get("title") or slot.capitalize()),
                    "meal_source": meal_source,
                    "calories": calories_total,
                    "protein_g": protein_total,
                    "carbs_g": carbs_total,
                    "fat_g": fat_total,
                    "estimated_cost": estimated_cost_total if has_known_cost else None,
                    "currency_code": currency_code,
                    "status": "planned",
                }
            )

        return normalized_entries

    @staticmethod
    def _week_start(value: date) -> date:
        return value - timedelta(days=value.weekday())

    @staticmethod
    def _sum_entries(entries: list[UserMealUsageEntry]) -> dict[str, Any]:
        return {
            "calories": sum(entry.calories for entry in entries),
            "protein_g": sum(entry.protein_g for entry in entries),
            "carbs_g": sum(entry.carbs_g for entry in entries),
            "fat_g": sum(entry.fat_g for entry in entries),
            "estimated_cost": sum(
                entry.estimated_cost for entry in entries if entry.estimated_cost is not None
            ),
        }

    @staticmethod
    def _normalized_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
