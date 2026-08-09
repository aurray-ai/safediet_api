from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_current_user, get_user_pantry_service
from app.models.user import User
from app.schemas.user_pantry import (
    UserPantryItemResponse,
    UserPantryItemUpsertRequest,
    UserPantryListResponse,
)
from app.services.user_pantry_service import UserPantryService

router = APIRouter(prefix="/meal-planning/pantry", tags=["meal-planning"])


@router.get("", response_model=UserPantryListResponse, status_code=status.HTTP_200_OK)
def list_user_pantry_items(
    current_user: User = Depends(get_current_user),
    user_pantry_service: UserPantryService = Depends(get_user_pantry_service),
) -> UserPantryListResponse:
    return user_pantry_service.list_items(current_user=current_user)


@router.put("/{product_id}", response_model=UserPantryItemResponse, status_code=status.HTTP_200_OK)
def upsert_user_pantry_item(
    product_id: str,
    payload: UserPantryItemUpsertRequest,
    current_user: User = Depends(get_current_user),
    user_pantry_service: UserPantryService = Depends(get_user_pantry_service),
) -> UserPantryItemResponse:
    if payload.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Path product_id does not match payload product_id.")
    return user_pantry_service.upsert_item(current_user=current_user, payload=payload)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_pantry_item(
    product_id: str,
    current_user: User = Depends(get_current_user),
    user_pantry_service: UserPantryService = Depends(get_user_pantry_service),
) -> Response:
    deleted = user_pantry_service.delete_item(
        current_user=current_user,
        product_id=product_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pantry item not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
