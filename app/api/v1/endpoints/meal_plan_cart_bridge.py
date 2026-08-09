from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_cart_service, get_current_user
from app.models.user import User
from app.schemas.cart import CartAddPlanItemsResponse
from app.services.cart_service import CartService, CartValidationError

router = APIRouter(prefix="/meal-plans", tags=["shop-cart"])


@router.post(
    "/{saved_plan_id}/add-to-cart",
    response_model=CartAddPlanItemsResponse,
    status_code=status.HTTP_200_OK,
)
def add_saved_plan_to_cart(
    saved_plan_id: str,
    current_user: User = Depends(get_current_user),
    cart_service: CartService = Depends(get_cart_service),
) -> CartAddPlanItemsResponse:
    try:
        return cart_service.add_saved_plan_buy_items(current_user=current_user, saved_plan_id=saved_plan_id)
    except CartValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
