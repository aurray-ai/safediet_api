from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_meal_cart_service
from app.models.user import User
from app.schemas.meal_cart import (
    MealCartItemQuantityUpdateRequest,
    MealCartItemUpsertRequest,
    MealCartResponse,
    MealCartSelectAddressRequest,
    MealCartValidateResponse,
)
from app.services.meal_cart_service import MealCartItemNotFoundError, MealCartService, MealCartValidationError

router = APIRouter(prefix="/meals/cart", tags=["meal-cart"])


@router.get("", response_model=MealCartResponse, status_code=status.HTTP_200_OK)
def get_meal_cart(
    current_user: User = Depends(get_current_user),
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
) -> MealCartResponse:
    return meal_cart_service.get_cart(current_user=current_user)


@router.put("/items/{meal_id}", response_model=MealCartResponse, status_code=status.HTTP_200_OK)
def upsert_meal_cart_item(
    meal_id: str,
    payload: MealCartItemUpsertRequest,
    current_user: User = Depends(get_current_user),
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
) -> MealCartResponse:
    if payload.meal_id != meal_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path meal_id does not match payload meal_id.",
        )
    try:
        return meal_cart_service.upsert_item(current_user=current_user, payload=payload)
    except MealCartValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/items/{item_id}", response_model=MealCartResponse, status_code=status.HTTP_200_OK)
def update_meal_cart_item_quantity(
    item_id: str,
    payload: MealCartItemQuantityUpdateRequest,
    current_user: User = Depends(get_current_user),
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
) -> MealCartResponse:
    try:
        return meal_cart_service.update_item_quantity(current_user=current_user, item_id=item_id, payload=payload)
    except MealCartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal cart item not found.") from exc


@router.delete("/items/{item_id}", response_model=MealCartResponse, status_code=status.HTTP_200_OK)
def remove_meal_cart_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
) -> MealCartResponse:
    try:
        return meal_cart_service.remove_item(current_user=current_user, item_id=item_id)
    except MealCartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal cart item not found.") from exc


@router.post("/address", response_model=MealCartResponse, status_code=status.HTTP_200_OK)
def select_meal_cart_address(
    payload: MealCartSelectAddressRequest,
    current_user: User = Depends(get_current_user),
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
) -> MealCartResponse:
    try:
        return meal_cart_service.select_address(current_user=current_user, payload=payload)
    except MealCartValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/validate", response_model=MealCartValidateResponse, status_code=status.HTTP_200_OK)
def validate_meal_cart(
    current_user: User = Depends(get_current_user),
    meal_cart_service: MealCartService = Depends(get_meal_cart_service),
) -> MealCartValidateResponse:
    return meal_cart_service.validate_cart(current_user=current_user)
