from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_meal_checkout_service
from app.models.user import User
from app.schemas.meal_checkout import (
    MealCheckoutConfirmRequest,
    MealCheckoutConfirmResponse,
    MealCheckoutQuoteRequest,
    MealCheckoutQuoteResponse,
)
from app.services.meal_checkout_service import MealCheckoutError, MealCheckoutService

router = APIRouter(prefix="/meals/checkout", tags=["meal-checkout"])


@router.post("/quote", response_model=MealCheckoutQuoteResponse, status_code=status.HTTP_200_OK)
def create_meal_checkout_quote(
    payload: MealCheckoutQuoteRequest,
    current_user: User = Depends(get_current_user),
    meal_checkout_service: MealCheckoutService = Depends(get_meal_checkout_service),
) -> MealCheckoutQuoteResponse:
    try:
        return meal_checkout_service.create_quote(current_user=current_user, payload=payload)
    except MealCheckoutError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/confirm", response_model=MealCheckoutConfirmResponse, status_code=status.HTTP_200_OK)
def confirm_meal_checkout(
    payload: MealCheckoutConfirmRequest,
    current_user: User = Depends(get_current_user),
    meal_checkout_service: MealCheckoutService = Depends(get_meal_checkout_service),
) -> MealCheckoutConfirmResponse:
    try:
        return meal_checkout_service.confirm_checkout(current_user=current_user, payload=payload)
    except MealCheckoutError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
