from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_checkout_service, get_current_user
from app.models.user import User
from app.schemas.checkout import CheckoutConfirmRequest, CheckoutConfirmResponse, CheckoutQuoteRequest, CheckoutQuoteResponse
from app.services.checkout_service import CheckoutError, CheckoutService

router = APIRouter(prefix="/shop/checkout", tags=["shop-checkout"])


@router.post("/quote", response_model=CheckoutQuoteResponse, status_code=status.HTTP_200_OK)
def create_checkout_quote(
    payload: CheckoutQuoteRequest,
    current_user: User = Depends(get_current_user),
    checkout_service: CheckoutService = Depends(get_checkout_service),
) -> CheckoutQuoteResponse:
    try:
        return checkout_service.create_quote(current_user=current_user, payload=payload)
    except CheckoutError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/confirm", response_model=CheckoutConfirmResponse, status_code=status.HTTP_200_OK)
def confirm_checkout(
    payload: CheckoutConfirmRequest,
    current_user: User = Depends(get_current_user),
    checkout_service: CheckoutService = Depends(get_checkout_service),
) -> CheckoutConfirmResponse:
    try:
        return checkout_service.confirm_checkout(current_user=current_user, payload=payload)
    except CheckoutError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
