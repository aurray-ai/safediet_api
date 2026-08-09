from datetime import date

from pydantic import BaseModel, Field


class UserMealUsageDayOverviewResponse(BaseModel):
    date: date
    target_calories: int
    planned_calories: int
    remaining_calories: int
    target_protein_g: int
    planned_protein_g: float
    remaining_protein_g: float
    target_carbs_g: int
    planned_carbs_g: float
    remaining_carbs_g: float
    target_fat_g: int
    planned_fat_g: float
    remaining_fat_g: float


class UserMealUsageWeekOverviewResponse(BaseModel):
    week_start: date
    week_end: date
    target_weekly_budget: int
    planned_spend: float
    remaining_budget: float
    currency_code: str | None = None


class UserMealUsageOverviewResponse(BaseModel):
    today: UserMealUsageDayOverviewResponse
    week: UserMealUsageWeekOverviewResponse


class UserMealUsageWeekHistoryItemResponse(BaseModel):
    week_start: date
    week_end: date
    target_weekly_budget: int
    planned_spend: float
    remaining_budget: float
    planned_calories: int
    planned_protein_g: float
    planned_carbs_g: float
    planned_fat_g: float
    days_with_saved_meals: int = Field(ge=0)
    average_daily_calories: float
    currency_code: str | None = None


class UserMealUsageWeekHistoryResponse(BaseModel):
    items: list[UserMealUsageWeekHistoryItemResponse] = Field(default_factory=list)
