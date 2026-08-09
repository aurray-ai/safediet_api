from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, get_meal_service, get_optional_current_user
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.user import User
from app.schemas.meal import (
    MealCategoryResponse,
    MealDetailResponse,
    MealListResponse,
)
from app.services.meal_service import (
    MealBudgetTier,
    MealCategoryNotFoundError,
    MealNotFoundError,
    MealService,
    MealSortOption,
)

router = APIRouter(prefix="/meals", tags=["meals"])


@router.get("/categories", response_model=list[MealCategoryResponse], status_code=status.HTTP_200_OK)
def list_meal_categories(
    meal_service: MealService = Depends(get_meal_service),
) -> list[MealCategoryResponse]:
    return meal_service.list_categories()


@router.get("", response_model=MealListResponse, status_code=status.HTTP_200_OK)
def list_meals(
    country: CountryCode | None = Query(default=None),
    meal_type: MealType | None = Query(default=None),
    category: str | None = Query(default=None, min_length=1),
    culture: str | None = Query(default=None, min_length=1),
    cuisine: str | None = Query(default=None, min_length=1),
    dietary: list[str] | None = Query(default=None),
    nutrition_focus: list[str] | None = Query(default=None),
    cook_time_max: int | None = Query(default=None, ge=1),
    budget_tier: MealBudgetTier | None = Query(default=None),
    sort: MealSortOption | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User | None = Depends(get_optional_current_user),
    meal_service: MealService = Depends(get_meal_service),
) -> MealListResponse:
    try:
        return meal_service.list_meals(
            country=country,
            meal_type=meal_type,
            category_id=category,
            culture=culture,
            cuisine=cuisine,
            dietary=dietary,
            nutrition_focus=nutrition_focus,
            cook_time_max=cook_time_max,
            budget_tier=budget_tier,
            sort=sort,
            search=search,
            page=page,
            page_size=page_size,
            current_user_id=current_user.id if current_user is not None else None,
        )
    except MealCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal category not found.",
        ) from exc


@router.get("/{meal_id}", response_model=MealDetailResponse, status_code=status.HTTP_200_OK)
def get_meal(
    meal_id: str,
    country: CountryCode | None = Query(default=None),
    current_user: User | None = Depends(get_optional_current_user),
    meal_service: MealService = Depends(get_meal_service),
) -> MealDetailResponse:
    try:
        return meal_service.get_meal(
            meal_id,
            country=country,
            current_user_id=current_user.id if current_user is not None else None,
        )
    except MealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal not found.",
        ) from exc


@router.post("/{meal_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def favorite_meal(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    meal_service: MealService = Depends(get_meal_service),
) -> None:
    try:
        meal_service.favorite_meal(user_id=current_user.id, meal_id=meal_id)
    except MealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal not found.",
        ) from exc


@router.delete("/{meal_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def unfavorite_meal(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    meal_service: MealService = Depends(get_meal_service),
) -> None:
    meal_service.unfavorite_meal(user_id=current_user.id, meal_id=meal_id)
