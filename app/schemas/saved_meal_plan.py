from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.schemas.meal_conversation import ConversationUIBlockResponse


class SavedMealPlanResponse(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=20)
    view_mode: str = Field(min_length=1, max_length=20)
    plan_scope: str | None = None
    effective_date: date | None = None
    week_start: date | None = None
    week_end: date | None = None
    day_index: int | None = None
    parent_saved_plan_id: str | None = None
    source_saved_plan_id: str | None = None
    linked_day_plan_ids: list[str] = Field(default_factory=list)
    meal_type: MealType | None = None
    country_code: CountryCode | None = None
    planned_meals: list[dict[str, Any]] = Field(default_factory=list)
    plan_payload: dict[str, Any] = Field(default_factory=dict)
    requested_culture: str | None = None
    user_goal: str | None = None
    source_snapshot_id: str
    source_conversation_id: str
    agent_type: str
    created_at: datetime
    updated_at: datetime


class SavedMealPlanListResponse(BaseModel):
    items: list[SavedMealPlanResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)


class HomeMealPlanResponse(BaseModel):
    selected_date: date
    view_mode: str = Field(min_length=1, max_length=20)
    resolution_mode: str = Field(min_length=1, max_length=80)
    ui_block: ConversationUIBlockResponse | None = None


class SavedMealPlanSlotMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add", "swap", "remove", "update_servings"]
    slot: MealType
    view: Literal["day", "week"] = "day"
    effective_date: date | None = None
    meal_id: str | None = Field(default=None, min_length=1, max_length=120)
    replacing_meal_id: str | None = Field(default=None, min_length=1, max_length=120)
    saved_plan_id: str | None = Field(default=None, min_length=1, max_length=120)
    planned_servings: int | None = Field(default=None, ge=1, le=24)

    @model_validator(mode="after")
    def validate_payload(self) -> "SavedMealPlanSlotMutationRequest":
        if self.operation in {"add", "swap"} and not self.meal_id:
            raise ValueError("meal_id is required for add and swap operations.")
        if self.operation == "swap" and not self.replacing_meal_id:
            raise ValueError("replacing_meal_id is required for swap operations.")
        if self.operation == "update_servings":
            if not self.meal_id:
                raise ValueError("meal_id is required for update_servings.")
            if self.planned_servings is None:
                raise ValueError("planned_servings is required for update_servings.")
        if self.operation == "remove" and self.meal_id and not self.replacing_meal_id:
            self.replacing_meal_id = self.meal_id
        if self.saved_plan_id is not None:
            self.saved_plan_id = self.saved_plan_id.strip() or None
        if self.meal_id is not None:
            self.meal_id = self.meal_id.strip() or None
        if self.replacing_meal_id is not None:
            self.replacing_meal_id = self.replacing_meal_id.strip() or None
        return self
