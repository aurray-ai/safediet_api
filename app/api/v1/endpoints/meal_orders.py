from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, get_meal_order_service
from app.models.user import User
from app.schemas.meal_order import (
    MealOrderCancelRequest,
    MealOrderCancelResponse,
    MealOrderListResponse,
    MealOrderResponse,
)
from app.services.meal_order_service import MealOrderNotFoundError, MealOrderService, MealOrderTransitionError

router = APIRouter(prefix="/meals/orders", tags=["meal-orders"])


@router.get("", response_model=MealOrderListResponse, status_code=status.HTTP_200_OK)
def list_meal_orders(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    meal_order_service: MealOrderService = Depends(get_meal_order_service),
) -> MealOrderListResponse:
    return meal_order_service.list_user_orders(current_user=current_user, before=before, limit=limit)


@router.get("/{order_id}", response_model=MealOrderResponse, status_code=status.HTTP_200_OK)
def get_meal_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    meal_order_service: MealOrderService = Depends(get_meal_order_service),
) -> MealOrderResponse:
    try:
        return meal_order_service.get_user_order(current_user=current_user, order_id=order_id)
    except MealOrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc


@router.post("/{order_id}/cancel", response_model=MealOrderCancelResponse, status_code=status.HTTP_200_OK)
def cancel_meal_order(
    order_id: str,
    payload: MealOrderCancelRequest,
    current_user: User = Depends(get_current_user),
    meal_order_service: MealOrderService = Depends(get_meal_order_service),
) -> MealOrderCancelResponse:
    try:
        return meal_order_service.cancel_order(current_user=current_user, order_id=order_id, reason=payload.reason)
    except MealOrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc
    except MealOrderTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
