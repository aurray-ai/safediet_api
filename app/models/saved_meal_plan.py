from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.models.grocery import CountryCode
from app.models.meal import MealType


@dataclass(frozen=True, slots=True)
class SavedMealPlan:
    id: str
    user_id: str
    title: str
    status: str
    view_mode: str
    plan_scope: str | None
    effective_date: date | None
    week_start: date | None
    week_end: date | None
    day_index: int | None
    parent_saved_plan_id: str | None
    source_saved_plan_id: str | None
    linked_day_plan_ids: list[str]
    meal_type: MealType | None
    country_code: CountryCode | None
    planned_meals: list[dict[str, Any]]
    plan_payload: dict[str, Any]
    requested_culture: str | None
    user_goal: str | None
    source_snapshot_id: str
    source_conversation_id: str
    agent_type: str
    created_at: datetime
    updated_at: datetime
