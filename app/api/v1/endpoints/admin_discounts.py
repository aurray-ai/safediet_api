from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_discount_service, require_platform_user
from app.models.grocery import GroceryDiscount, GroceryProduct
from app.models.user import User
from app.schemas.discount import (
    AssignProductsToDiscountRequest,
    CreateDiscountRequest,
    DiscountAuditEntryResponse,
    DiscountAuditListResponse,
    DiscountListResponse,
    DiscountProductListResponse,
    DiscountProductSummaryResponse,
    DiscountResponse,
    UnassignProductsFromDiscountRequest,
    UpdateDiscountRequest,
)
from app.services.discount_service import DiscountNotFoundError, DiscountService

router = APIRouter(prefix="/admin/discounts", tags=["admin-discounts"])


def _to_response(discount: GroceryDiscount, *, product_count: int) -> DiscountResponse:
    return DiscountResponse(
        id=discount.id,
        label=discount.label,
        percent=discount.percent,
        product_count=product_count,
        created_at=discount.created_at,
        updated_at=discount.updated_at,
    )


def _to_product_summary(product: GroceryProduct) -> DiscountProductSummaryResponse:
    return DiscountProductSummaryResponse(
        id=product.id,
        product=product.product,
        img_url=product.img_url,
        category_id=product.category_id,
    )


@router.get("", response_model=DiscountListResponse, status_code=status.HTTP_200_OK)
def list_discounts(
    _: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountListResponse:
    pairs = discount_service.list_discounts()
    return DiscountListResponse(
        items=[_to_response(discount, product_count=count) for discount, count in pairs]
    )


@router.post("", response_model=DiscountResponse, status_code=status.HTTP_201_CREATED)
def create_discount(
    payload: CreateDiscountRequest,
    current_admin: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountResponse:
    created = discount_service.create_discount(
        label=payload.label,
        percent=payload.percent,
        actor_user_id=current_admin.id,
    )
    return _to_response(created, product_count=0)


@router.get("/{discount_id}", response_model=DiscountResponse, status_code=status.HTTP_200_OK)
def get_discount(
    discount_id: str,
    _: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountResponse:
    try:
        discount = discount_service.get_discount(discount_id)
        _, total = discount_service.list_discount_products(discount_id=discount_id, page=1, page_size=1)
    except DiscountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount not found.") from exc
    return _to_response(discount, product_count=total)


@router.put("/{discount_id}", response_model=DiscountResponse, status_code=status.HTTP_200_OK)
def update_discount(
    discount_id: str,
    payload: UpdateDiscountRequest,
    current_admin: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountResponse:
    try:
        updated = discount_service.update_discount(
            discount_id=discount_id,
            label=payload.label,
            percent=payload.percent,
            actor_user_id=current_admin.id,
        )
        _, total = discount_service.list_discount_products(discount_id=discount_id, page=1, page_size=1)
    except DiscountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount not found.") from exc
    return _to_response(updated, product_count=total)


@router.delete("/{discount_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_discount(
    discount_id: str,
    current_admin: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> None:
    try:
        discount_service.delete_discount(discount_id=discount_id, actor_user_id=current_admin.id)
    except DiscountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount not found.") from exc


@router.get(
    "/{discount_id}/products",
    response_model=DiscountProductListResponse,
    status_code=status.HTTP_200_OK,
)
def list_discount_products(
    discount_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountProductListResponse:
    try:
        products, total = discount_service.list_discount_products(
            discount_id=discount_id, page=page, page_size=page_size, search=search
        )
    except DiscountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount not found.") from exc
    return DiscountProductListResponse(
        items=[_to_product_summary(product) for product in products],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{discount_id}/products",
    response_model=DiscountProductListResponse,
    status_code=status.HTTP_200_OK,
)
def assign_products_to_discount(
    discount_id: str,
    payload: AssignProductsToDiscountRequest,
    current_admin: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountProductListResponse:
    try:
        discount_service.assign_products(
            discount_id=discount_id,
            product_ids=payload.product_ids,
            actor_user_id=current_admin.id,
        )
        products, total = discount_service.list_discount_products(discount_id=discount_id, page=1, page_size=20)
    except DiscountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount not found.") from exc
    return DiscountProductListResponse(
        items=[_to_product_summary(product) for product in products],
        total=total,
        page=1,
        page_size=20,
    )


@router.delete(
    "/{discount_id}/products",
    response_model=DiscountProductListResponse,
    status_code=status.HTTP_200_OK,
)
def unassign_products_from_discount(
    discount_id: str,
    payload: UnassignProductsFromDiscountRequest,
    current_admin: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountProductListResponse:
    try:
        discount_service.unassign_products(
            discount_id=discount_id,
            product_ids=payload.product_ids,
            actor_user_id=current_admin.id,
        )
        products, total = discount_service.list_discount_products(discount_id=discount_id, page=1, page_size=20)
    except DiscountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discount not found.") from exc
    return DiscountProductListResponse(
        items=[_to_product_summary(product) for product in products],
        total=total,
        page=1,
        page_size=20,
    )


@router.get(
    "/{discount_id}/audit-log",
    response_model=DiscountAuditListResponse,
    status_code=status.HTTP_200_OK,
)
def get_discount_audit_log(
    discount_id: str,
    _: User = Depends(require_platform_user),
    discount_service: DiscountService = Depends(get_discount_service),
) -> DiscountAuditListResponse:
    entries = discount_service.get_audit_log(discount_id=discount_id)
    return DiscountAuditListResponse(
        items=[
            DiscountAuditEntryResponse(
                action=str(entry["action"]),
                details=dict(entry.get("details") or {}),
                actor_user_id=str(entry["actor_user_id"]),
                actor_name=str(entry.get("actor_name") or "Unknown admin"),
                created_at=entry["created_at"],
            )
            for entry in entries
        ]
    )
