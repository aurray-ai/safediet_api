from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, get_kitchen_service, get_order_service, get_refund_service
from app.models.user import User
from app.schemas.kitchen import KitchenOrderImportPreviewResponse, KitchenOrderImportResponse
from app.schemas.order import (
    OrderCancelRequest,
    OrderCancelResponse,
    OrderListResponse,
    OrderResponse,
    RefundCreateRequest,
    RefundListResponse,
    RefundResponse,
)
from app.services.kitchen_service import KitchenOrderImportError, KitchenService
from app.services.order_service import OrderNotFoundError, OrderService, OrderTransitionError
from app.services.refund_service import RefundError, RefundService

router = APIRouter(prefix="/shop/orders", tags=["shop-orders"])


@router.get("", response_model=OrderListResponse, status_code=status.HTTP_200_OK)
def list_orders(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderListResponse:
    return order_service.list_user_orders(current_user=current_user, before=before, limit=limit)


@router.get("/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return order_service.get_user_order(current_user=current_user, order_id=order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc


@router.post("/{order_id}/cancel", response_model=OrderCancelResponse, status_code=status.HTTP_200_OK)
def cancel_order(
    order_id: str,
    payload: OrderCancelRequest,
    current_user: User = Depends(get_current_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderCancelResponse:
    try:
        return order_service.cancel_order(current_user=current_user, order_id=order_id, reason=payload.reason)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc
    except OrderTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{order_id}/kitchen-import-preview",
    response_model=KitchenOrderImportPreviewResponse,
    status_code=status.HTTP_200_OK,
)
def preview_order_kitchen_import(
    order_id: str,
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> KitchenOrderImportPreviewResponse:
    try:
        return kitchen_service.preview_order_import(current_user=current_user, order_id=order_id)
    except KitchenOrderImportError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post(
    "/{order_id}/kitchen-import",
    response_model=KitchenOrderImportResponse,
    status_code=status.HTTP_200_OK,
)
def import_order_to_kitchen(
    order_id: str,
    current_user: User = Depends(get_current_user),
    kitchen_service: KitchenService = Depends(get_kitchen_service),
) -> KitchenOrderImportResponse:
    try:
        return kitchen_service.import_order_to_kitchen(current_user=current_user, order_id=order_id)
    except KitchenOrderImportError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/{order_id}/refunds", response_model=RefundListResponse, status_code=status.HTTP_200_OK)
def list_order_refunds(
    order_id: str,
    current_user: User = Depends(get_current_user),
    refund_service: RefundService = Depends(get_refund_service),
) -> RefundListResponse:
    try:
        return refund_service.list_refunds(current_user=current_user, order_id=order_id)
    except RefundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{order_id}/refunds", response_model=RefundResponse, status_code=status.HTTP_200_OK)
def create_order_refund(
    order_id: str,
    payload: RefundCreateRequest,
    current_user: User = Depends(get_current_user),
    refund_service: RefundService = Depends(get_refund_service),
) -> RefundResponse:
    try:
        return refund_service.create_refund(current_user=current_user, order_id=order_id, payload=payload)
    except RefundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
