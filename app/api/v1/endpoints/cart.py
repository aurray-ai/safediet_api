from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_cart_service, get_current_user
from app.models.user import User
from app.schemas.cart import (
    CartItemQuantityUpdateRequest,
    CartItemUpsertRequest,
    CartResponse,
    CartSelectAddressRequest,
    CartValidateResponse,
)
from app.services.cart_service import CartItemNotFoundError, CartService, CartValidationError

router = APIRouter(prefix="/shop/cart", tags=["shop-cart"])


@router.get("", response_model=CartResponse, status_code=status.HTTP_200_OK)
def get_cart(
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartResponse:
    return cart_service.get_cart(current_user=current_user)


@router.put("/items/{product_id}", response_model=CartResponse, status_code=status.HTTP_200_OK)
def upsert_cart_item(
    product_id: str,
    payload: CartItemUpsertRequest,
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartResponse:
    if payload.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Path product_id does not match payload product_id.")
    try:
        return cart_service.upsert_item(current_user=current_user, payload=payload)
    except CartValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/items/{item_id}", response_model=CartResponse, status_code=status.HTTP_200_OK)
def update_cart_item_quantity(
    item_id: str,
    payload: CartItemQuantityUpdateRequest,
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartResponse:
    try:
        return cart_service.update_item_quantity(current_user=current_user, item_id=item_id, payload=payload)
    except CartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found.") from exc


@router.delete("/items/{item_id}", response_model=CartResponse, status_code=status.HTTP_200_OK)
def remove_cart_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartResponse:
    try:
        return cart_service.remove_item(current_user=current_user, item_id=item_id)
    except CartItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found.") from exc


@router.post("/address", response_model=CartResponse, status_code=status.HTTP_200_OK)
def select_cart_address(
    payload: CartSelectAddressRequest,
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartResponse:
    try:
        return cart_service.select_address(current_user=current_user, payload=payload)
    except CartValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/validate", response_model=CartValidateResponse, status_code=status.HTTP_200_OK)
def validate_cart(
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartValidateResponse:
    return cart_service.validate_cart(current_user=current_user)
