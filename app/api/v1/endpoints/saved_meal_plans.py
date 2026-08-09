from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, get_saved_meal_plan_service
from app.models.user import User
from app.schemas.kitchen import SavedPlanKitchenConsumeRequest, SavedPlanKitchenResponse
from app.schemas.saved_meal_plan import (
    HomeMealPlanResponse,
    SavedMealPlanListResponse,
    SavedMealPlanSlotMutationRequest,
)
from app.services.saved_meal_plan_service import (
    SavedMealPlanMutationError,
    SavedMealPlanNotFoundError,
    SavedMealPlanService,
)

router = APIRouter(prefix="/meal-planning/saved-plans", tags=["meal-planning"])


@router.get("", response_model=SavedMealPlanListResponse, status_code=status.HTTP_200_OK)
def list_saved_meal_plans(
    view_mode: str | None = Query(default=None),
    effective_date: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    saved_meal_plan_service: SavedMealPlanService = Depends(get_saved_meal_plan_service),
) -> SavedMealPlanListResponse:
    return saved_meal_plan_service.list_saved_plans(
        current_user=current_user,
        view_mode=view_mode,
        effective_date=effective_date,
        limit=limit,
    )


@router.get("/home-plan", response_model=HomeMealPlanResponse, status_code=status.HTTP_200_OK)
def get_home_meal_plan(
    date: date = Query(...),
    view: Literal["day", "week"] = Query(default="day"),
    include_drafts: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    saved_meal_plan_service: SavedMealPlanService = Depends(get_saved_meal_plan_service),
) -> HomeMealPlanResponse:
    return saved_meal_plan_service.resolve_home_plan(
        current_user=current_user,
        selected_date=date,
        view_mode=view,
        include_drafts=include_drafts,
    )


@router.post("/slot-mutations", response_model=HomeMealPlanResponse, status_code=status.HTTP_200_OK)
def mutate_saved_meal_plan_slot(
    payload: SavedMealPlanSlotMutationRequest,
    current_user: User = Depends(get_current_user),
    saved_meal_plan_service: SavedMealPlanService = Depends(get_saved_meal_plan_service),
) -> HomeMealPlanResponse:
    try:
        return saved_meal_plan_service.mutate_slot(
            current_user=current_user,
            payload=payload,
        )
    except SavedMealPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved meal plan not found.") from exc
    except SavedMealPlanMutationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{saved_plan_id}/kitchen", response_model=SavedPlanKitchenResponse, status_code=status.HTTP_200_OK)
def list_saved_plan_kitchen(
    saved_plan_id: str,
    current_user: User = Depends(get_current_user),
    saved_meal_plan_service: SavedMealPlanService = Depends(get_saved_meal_plan_service),
) -> SavedPlanKitchenResponse:
    try:
        return saved_meal_plan_service.list_saved_plan_kitchen(
            current_user=current_user,
            saved_plan_id=saved_plan_id,
        )
    except SavedMealPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved meal plan not found.") from exc


@router.post(
    "/{saved_plan_id}/kitchen/consume-slot",
    response_model=SavedPlanKitchenResponse,
    status_code=status.HTTP_200_OK,
)
def consume_saved_plan_kitchen_slot(
    saved_plan_id: str,
    payload: SavedPlanKitchenConsumeRequest,
    current_user: User = Depends(get_current_user),
    saved_meal_plan_service: SavedMealPlanService = Depends(get_saved_meal_plan_service),
) -> SavedPlanKitchenResponse:
    try:
        return saved_meal_plan_service.consume_saved_plan_kitchen_slot(
            current_user=current_user,
            saved_plan_id=saved_plan_id,
            payload=payload,
        )
    except SavedMealPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved meal plan not found.") from exc
