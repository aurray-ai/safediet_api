from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_chef_fulfillment_service, require_chef_user
from app.models.fulfillment import ChefFulfillmentStatus
from app.models.user import User
from app.schemas.fulfillment import (
    DeclineRequest,
    FulfillmentStatusUpdateRequest,
    MealOrderFulfillmentListResponse,
    MealOrderFulfillmentResponse,
)
from app.services.chef_fulfillment_service import (
    ChefFulfillmentService,
    FulfillmentNotFoundError,
    FulfillmentTransitionError,
)
from app.services.fulfillment_response_mappers import meal_order_to_fulfillment_response

router = APIRouter(prefix="/chef/orders", tags=["chef-orders"])


@router.get("", response_model=MealOrderFulfillmentListResponse, status_code=status.HTTP_200_OK)
def list_my_meal_orders(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_chef: User = Depends(require_chef_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentListResponse:
    items, next_cursor = chef_fulfillment_service.list_mine(current_chef=current_chef, before=before, limit=limit)
    return MealOrderFulfillmentListResponse(items=[meal_order_to_fulfillment_response(item) for item in items], next_cursor=next_cursor)


@router.get("/{order_id}", response_model=MealOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
def get_my_meal_order(
    order_id: str,
    current_chef: User = Depends(require_chef_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentResponse:
    try:
        return meal_order_to_fulfillment_response(chef_fulfillment_service.get_for_chef(current_chef=current_chef, order_id=order_id))
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal order not found.") from exc


@router.post("/{order_id}/status", response_model=MealOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
async def update_my_meal_order_status(
    order_id: str,
    payload: FulfillmentStatusUpdateRequest,
    current_chef: User = Depends(require_chef_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentResponse:
    try:
        target_status = ChefFulfillmentStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status value.") from exc
    try:
        updated = await chef_fulfillment_service.advance_status(
            current_chef=current_chef,
            order_id=order_id,
            status=target_status,
            note=payload.note,
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal order not found.") from exc
    except FulfillmentTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return meal_order_to_fulfillment_response(updated)


@router.post("/{order_id}/decline", response_model=MealOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
async def decline_my_meal_order(
    order_id: str,
    payload: DeclineRequest,
    current_chef: User = Depends(require_chef_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentResponse:
    try:
        updated = await chef_fulfillment_service.decline(
            current_chef=current_chef,
            order_id=order_id,
            reason_code=payload.reason_code,
            note=payload.note,
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal order not found.") from exc
    return meal_order_to_fulfillment_response(updated)
