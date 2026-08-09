from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_shopper_fulfillment_service, require_shopper_user
from app.models.fulfillment import ShopperFulfillmentStatus
from app.models.user import User
from app.schemas.fulfillment import (
    DeclineRequest,
    FulfillmentStatusUpdateRequest,
    GroceryOrderFulfillmentListResponse,
    GroceryOrderFulfillmentResponse,
)
from app.services.fulfillment_response_mappers import order_to_fulfillment_response
from app.services.shopper_fulfillment_service import (
    FulfillmentNotFoundError,
    FulfillmentTransitionError,
    ShopperFulfillmentService,
)

router = APIRouter(prefix="/shopper/orders", tags=["shopper-orders"])


@router.get("", response_model=GroceryOrderFulfillmentListResponse, status_code=status.HTTP_200_OK)
def list_my_grocery_orders(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_shopper: User = Depends(require_shopper_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> GroceryOrderFulfillmentListResponse:
    items, next_cursor = shopper_fulfillment_service.list_mine(
        current_shopper=current_shopper, before=before, limit=limit
    )
    return GroceryOrderFulfillmentListResponse(
        items=[order_to_fulfillment_response(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/{order_id}", response_model=GroceryOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
def get_my_grocery_order(
    order_id: str,
    current_shopper: User = Depends(require_shopper_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> GroceryOrderFulfillmentResponse:
    try:
        return order_to_fulfillment_response(
            shopper_fulfillment_service.get_for_shopper(current_shopper=current_shopper, order_id=order_id)
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc


@router.post("/{order_id}/status", response_model=GroceryOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
async def update_my_grocery_order_status(
    order_id: str,
    payload: FulfillmentStatusUpdateRequest,
    current_shopper: User = Depends(require_shopper_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> GroceryOrderFulfillmentResponse:
    try:
        target_status = ShopperFulfillmentStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status value.") from exc
    try:
        updated = await shopper_fulfillment_service.advance_status(
            current_shopper=current_shopper,
            order_id=order_id,
            status=target_status,
            note=payload.note,
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc
    except FulfillmentTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return order_to_fulfillment_response(updated)


@router.post("/{order_id}/decline", response_model=GroceryOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
async def decline_my_grocery_order(
    order_id: str,
    payload: DeclineRequest,
    current_shopper: User = Depends(require_shopper_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> GroceryOrderFulfillmentResponse:
    try:
        updated = await shopper_fulfillment_service.decline(
            current_shopper=current_shopper,
            order_id=order_id,
            reason_code=payload.reason_code,
            note=payload.note,
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc
    return order_to_fulfillment_response(updated)
