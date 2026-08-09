from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_inventory_service, require_platform_user
from app.models.user import User
from app.schemas.inventory import (
    AdminInventoryAdjustmentListResponse,
    AdminInventoryAdjustmentRequest,
    AdminInventoryAdjustmentResponse,
    AdminInventoryItemResponse,
    AdminInventoryItemUpsertRequest,
    AdminInventoryListResponse,
    DeliveryFeeRuleCreateRequest,
    DeliveryFeeRuleListResponse,
    DeliveryFeeRuleResponse,
    DeliveryFeeRuleUpdateRequest,
)
from app.services.inventory_service import InventoryNotFoundError, InventoryService

router = APIRouter(prefix="/admin/groceries/inventory", tags=["admin-grocery-inventory"])


@router.get("", response_model=AdminInventoryListResponse, status_code=status.HTTP_200_OK)
def list_inventory(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    is_active: bool | None = Query(default=None),
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> AdminInventoryListResponse:
    return inventory_service.list_inventory(page=page, page_size=page_size, search=search, is_active=is_active)


@router.put("/{product_id}", response_model=AdminInventoryItemResponse, status_code=status.HTTP_200_OK)
def upsert_inventory_item(
    product_id: str,
    payload: AdminInventoryItemUpsertRequest,
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> AdminInventoryItemResponse:
    try:
        return inventory_service.upsert_inventory_item(product_id=product_id, payload=payload)
    except InventoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grocery product not found.") from exc


@router.get("/{product_id}", response_model=AdminInventoryItemResponse, status_code=status.HTTP_200_OK)
def get_inventory_item(
    product_id: str,
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> AdminInventoryItemResponse:
    try:
        return inventory_service.get_inventory_item(product_id=product_id)
    except InventoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found.") from exc


@router.post("/{product_id}/adjustments", response_model=AdminInventoryAdjustmentResponse, status_code=status.HTTP_200_OK)
def adjust_inventory(
    product_id: str,
    payload: AdminInventoryAdjustmentRequest,
    current_admin: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> AdminInventoryAdjustmentResponse:
    try:
        return inventory_service.adjust_inventory(product_id=product_id, actor_user_id=current_admin.id, payload=payload)
    except (InventoryNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{product_id}/adjustments", response_model=AdminInventoryAdjustmentListResponse, status_code=status.HTTP_200_OK)
def list_inventory_adjustments(
    product_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> AdminInventoryAdjustmentListResponse:
    return inventory_service.list_adjustments(product_id=product_id, page=page, page_size=page_size)


@router.get("/delivery-fees/list", response_model=DeliveryFeeRuleListResponse, status_code=status.HTTP_200_OK)
def list_delivery_fee_rules(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> DeliveryFeeRuleListResponse:
    return inventory_service.list_delivery_fee_rules(currency=currency.upper() if currency else None)


@router.post("/delivery-fees", response_model=DeliveryFeeRuleResponse, status_code=status.HTTP_201_CREATED)
def create_delivery_fee_rule(
    payload: DeliveryFeeRuleCreateRequest,
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> DeliveryFeeRuleResponse:
    return inventory_service.create_delivery_fee_rule(payload=payload)


@router.put("/delivery-fees/{rule_id}", response_model=DeliveryFeeRuleResponse, status_code=status.HTTP_200_OK)
def update_delivery_fee_rule(
    rule_id: str,
    payload: DeliveryFeeRuleUpdateRequest,
    _: User = Depends(require_platform_user),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> DeliveryFeeRuleResponse:
    try:
        return inventory_service.update_delivery_fee_rule(rule_id=rule_id, payload=payload)
    except InventoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery fee rule not found.") from exc
