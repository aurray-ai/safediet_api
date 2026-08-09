from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_order_service, get_refund_service, get_shopper_fulfillment_service, require_platform_user
from app.models.order import OrderStatus
from app.models.user import User
from app.schemas.fulfillment import (
    AssignWorkerRequest,
    GroceryOrderFulfillmentResponse,
    WorkerListResponse,
    WorkerRosterEntryResponse,
    WorkerRosterListResponse,
    WorkerSummaryResponse,
)
from app.schemas.order import (
    AdminOrderStatusUpdateRequest,
    AdminOrderSubstitutionRequest,
    OrderListResponse,
    OrderResponse,
    RefundCreateRequest,
    RefundListResponse,
    RefundResponse,
)
from app.services.fulfillment_response_mappers import order_to_fulfillment_response
from app.services.order_service import OrderNotFoundError, OrderService
from app.services.refund_service import RefundError, RefundService
from app.services.shopper_fulfillment_service import (
    FulfillmentNotFoundError,
    FulfillmentStateError,
    ShopperFulfillmentService,
)

router = APIRouter(prefix="/admin/grocery-orders", tags=["admin-grocery-orders"])


@router.get("", response_model=OrderListResponse, status_code=status.HTTP_200_OK)
def list_admin_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    _: User = Depends(require_platform_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderListResponse:
    return order_service.list_admin_orders(status=status_filter, before=before, limit=limit)


@router.get("/shoppers", response_model=WorkerListResponse, status_code=status.HTTP_200_OK)
def list_available_shoppers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> WorkerListResponse:
    items, total = shopper_fulfillment_service.list_available_shoppers(page=page, page_size=page_size, search=search)
    return WorkerListResponse(
        items=[WorkerSummaryResponse(id=user.id, name=user.name, email=user.email) for user in items],
        total=total,
    )


@router.get("/shoppers/roster", response_model=WorkerRosterListResponse, status_code=status.HTTP_200_OK)
def list_shopper_roster(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> WorkerRosterListResponse:
    entries, total = shopper_fulfillment_service.list_shopper_roster(page=page, page_size=page_size, search=search)
    return WorkerRosterListResponse(
        items=[
            WorkerRosterEntryResponse(
                id=entry["user"].id,
                name=entry["user"].name,
                email=entry["user"].email,
                active_count=entry["active_count"],
                completed_this_week=entry["completed_this_week"],
            )
            for entry in entries
        ],
        total=total,
    )


@router.post("/{order_id}/assign", response_model=GroceryOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
async def assign_grocery_order_to_shopper(
    order_id: str,
    payload: AssignWorkerRequest,
    current_admin: User = Depends(require_platform_user),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> GroceryOrderFulfillmentResponse:
    try:
        updated = await shopper_fulfillment_service.assign(
            order_id=order_id,
            shopper_id=payload.worker_id,
            actor_user_id=current_admin.id,
            note=payload.note,
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc
    except FulfillmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return order_to_fulfillment_response(updated)


@router.get("/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
def get_admin_order(
    order_id: str,
    _: User = Depends(require_platform_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return order_service.get_admin_order(order_id=order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc


@router.post("/{order_id}/status", response_model=OrderResponse, status_code=status.HTTP_200_OK)
def update_admin_order_status(
    order_id: str,
    payload: AdminOrderStatusUpdateRequest,
    current_admin: User = Depends(require_platform_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return order_service.advance_order_status(
            order_id=order_id,
            status=OrderStatus(payload.status),
            note=payload.note,
            actor_user_id=current_admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.") from exc


@router.post("/{order_id}/refunds", response_model=RefundResponse, status_code=status.HTTP_200_OK)
def create_admin_order_refund(
    order_id: str,
    payload: RefundCreateRequest,
    _: User = Depends(require_platform_user),
    refund_service: RefundService = Depends(get_refund_service),
) -> RefundResponse:
    try:
        return refund_service.create_admin_refund(order_id=order_id, payload=payload)
    except RefundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{order_id}/refunds", response_model=RefundListResponse, status_code=status.HTTP_200_OK)
def list_admin_order_refunds(
    order_id: str,
    _: User = Depends(require_platform_user),
    refund_service: RefundService = Depends(get_refund_service),
) -> RefundListResponse:
    return refund_service.list_admin_refunds(order_id=order_id)


@router.post("/{order_id}/items/{item_id}/substitution", response_model=OrderResponse, status_code=status.HTTP_200_OK)
def apply_substitution_decision(
    order_id: str,
    item_id: str,
    payload: AdminOrderSubstitutionRequest,
    current_admin: User = Depends(require_platform_user),
    order_service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    try:
        return order_service.apply_substitution_decision(
            order_id=order_id,
            item_id=item_id,
            replacement_product_id=payload.replacement_product_id,
            note=payload.note,
            actor_user_id=current_admin.id,
        )
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order or order item not found.") from exc
