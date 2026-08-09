from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import get_current_user, get_kitchen_service
from app.models.user import User
from app.schemas.kitchen import (
    KitchenItemResponse,
    KitchenItemUpsertRequest,
    KitchenListResponse,
    KitchenMovementListResponse,
    KitchenSummaryResponse,
)
from app.services.kitchen_service import KitchenService

router = APIRouter(prefix="/meal-planning/kitchen", tags=["meal-planning"])


@router.get("", response_model=KitchenListResponse, status_code=status.HTTP_200_OK)
def list_kitchen_items(
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> KitchenListResponse:
    return kitchen_service.list_items(current_user=current_user)


@router.get("/summary", response_model=KitchenSummaryResponse, status_code=status.HTTP_200_OK)
def get_kitchen_summary(
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> KitchenSummaryResponse:
    return kitchen_service.get_summary(current_user=current_user)


@router.get("/movements", response_model=KitchenMovementListResponse, status_code=status.HTTP_200_OK)
def list_kitchen_movements(
    product_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> KitchenMovementListResponse:
    return kitchen_service.list_movements(
        current_user=current_user,
        product_id=product_id,
        limit=limit,
    )


@router.put("/{product_id}", response_model=KitchenItemResponse, status_code=status.HTTP_200_OK)
def upsert_kitchen_item(
    product_id: str,
    payload: KitchenItemUpsertRequest,
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> KitchenItemResponse:
    if payload.product_id != product_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path product_id does not match payload product_id.",
        )
    return kitchen_service.upsert_manual_item(current_user=current_user, payload=payload)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kitchen_item(
    product_id: str,
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> Response:
    deleted = kitchen_service.delete_manual_item(
        current_user=current_user,
        product_id=product_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kitchen item not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
