from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_meal_plan_checkout_service
from app.models.user import User
from app.schemas.meal_plan_checkout import (
    MealPlanCheckoutConfirmRequest,
    MealPlanCheckoutConfirmResponse,
    MealPlanCheckoutQuoteRequest,
    MealPlanCheckoutQuoteResponse,
)
from app.services.meal_plan_checkout_service import MealPlanCheckoutError, MealPlanCheckoutService

router = APIRouter(prefix="/meals/plan-checkout", tags=["meal-plan-checkout"])


@router.post("/quote", response_model=MealPlanCheckoutQuoteResponse, status_code=status.HTTP_200_OK)
def create_meal_plan_checkout_quote(
    payload: MealPlanCheckoutQuoteRequest,
    current_user: User = Depends(get_current_user),
    meal_plan_checkout_service: MealPlanCheckoutService = Depends(get_meal_plan_checkout_service),
) -> MealPlanCheckoutQuoteResponse:
    try:
        return meal_plan_checkout_service.create_quote(current_user=current_user, payload=payload)
    except MealPlanCheckoutError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/confirm", response_model=MealPlanCheckoutConfirmResponse, status_code=status.HTTP_200_OK)
def confirm_meal_plan_checkout(
    payload: MealPlanCheckoutConfirmRequest,
    current_user: User = Depends(get_current_user),
    meal_plan_checkout_service: MealPlanCheckoutService = Depends(get_meal_plan_checkout_service),
) -> MealPlanCheckoutConfirmResponse:
    try:
        return meal_plan_checkout_service.confirm_checkout(current_user=current_user, payload=payload)
    except MealPlanCheckoutError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
