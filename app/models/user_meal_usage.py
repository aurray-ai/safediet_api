from dataclasses import dataclass
from datetime import date, datetime

from app.models.meal import MealType


@dataclass(frozen=True, slots=True)
class UserMealUsageEntry:
    id: str
    user_id: str
    saved_plan_id: str
    source_snapshot_id: str
    source_conversation_id: str
    effective_date: date
    week_start: date
    week_end: date
    view_mode: str
    meal_slot: MealType
    meal_name: str
    meal_source: str | None
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    estimated_cost: float | None
    currency_code: str | None
    status: str
    created_at: datetime
    updated_at: datetime
