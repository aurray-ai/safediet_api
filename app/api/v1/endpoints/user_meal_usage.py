from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import get_current_user, get_user_meal_usage_service
from app.models.user import User
from app.schemas.user_meal_usage import (
    UserMealUsageOverviewResponse,
    UserMealUsageWeekHistoryResponse,
)
from app.services.user_meal_usage_service import UserMealUsageService

router = APIRouter(prefix="/meal-planning/usage", tags=["meal-planning"])


@router.get("/overview", response_model=UserMealUsageOverviewResponse, status_code=status.HTTP_200_OK)
def get_usage_overview(
    usage_date: date | None = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    user_meal_usage_service: UserMealUsageService = Depends(get_user_meal_usage_service),
) -> UserMealUsageOverviewResponse:
    return user_meal_usage_service.get_overview(
        current_user=current_user,
        on_date=usage_date,
    )


@router.get("/history/weeks", response_model=UserMealUsageWeekHistoryResponse, status_code=status.HTTP_200_OK)
def get_usage_week_history(
    limit: int = Query(default=8, ge=1, le=52),
    end_date: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    user_meal_usage_service: UserMealUsageService = Depends(get_user_meal_usage_service),
) -> UserMealUsageWeekHistoryResponse:
    return user_meal_usage_service.list_week_history(
        current_user=current_user,
        limit=limit,
        end_date=end_date,
    )
