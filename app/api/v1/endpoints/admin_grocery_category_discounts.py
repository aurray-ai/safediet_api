from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_category_discount_service, require_platform_user
from app.models.user import User
from app.schemas.category_discount import (
    CategoryDiscountAuditEntryResponse,
    CategoryDiscountAuditListResponse,
    CategoryDiscountResponse,
    CategoryDiscountListResponse,
    SetCategoryDiscountRequest,
)
from app.services.category_discount_service import CategoryDiscountService, CategoryNotFoundError

router = APIRouter(prefix="/admin/groceries/categories", tags=["admin-category-discounts"])


def _to_response(category) -> CategoryDiscountResponse:
    return CategoryDiscountResponse(
        category_id=category.id,
        category_name=category.name,
        discount_percent=category.discount_percent,
        updated_at=category.updated_at,
    )


@router.get("", response_model=CategoryDiscountListResponse, status_code=status.HTTP_200_OK)
def list_category_discounts(
    _: User = Depends(require_platform_user),
    category_discount_service: CategoryDiscountService = Depends(get_category_discount_service),
) -> CategoryDiscountListResponse:
    categories = category_discount_service.list_discounts()
    return CategoryDiscountListResponse(items=[_to_response(category) for category in categories])


@router.put("/{category_id}/discount", response_model=CategoryDiscountResponse, status_code=status.HTTP_200_OK)
def set_category_discount(
    category_id: str,
    payload: SetCategoryDiscountRequest,
    current_admin: User = Depends(require_platform_user),
    category_discount_service: CategoryDiscountService = Depends(get_category_discount_service),
) -> CategoryDiscountResponse:
    try:
        updated = category_discount_service.set_discount(
            category_id=category_id,
            discount_percent=payload.discount_percent,
            actor_user_id=current_admin.id,
        )
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grocery category not found.") from exc
    return _to_response(updated)


@router.delete("/{category_id}/discount", response_model=CategoryDiscountResponse, status_code=status.HTTP_200_OK)
def reset_category_discount(
    category_id: str,
    current_admin: User = Depends(require_platform_user),
    category_discount_service: CategoryDiscountService = Depends(get_category_discount_service),
) -> CategoryDiscountResponse:
    try:
        updated = category_discount_service.reset_discount(
            category_id=category_id,
            actor_user_id=current_admin.id,
        )
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grocery category not found.") from exc
    return _to_response(updated)


@router.get(
    "/{category_id}/discount/history",
    response_model=CategoryDiscountAuditListResponse,
    status_code=status.HTTP_200_OK,
)
def get_category_discount_history(
    category_id: str,
    _: User = Depends(require_platform_user),
    category_discount_service: CategoryDiscountService = Depends(get_category_discount_service),
) -> CategoryDiscountAuditListResponse:
    entries = category_discount_service.get_discount_history(category_id=category_id)
    return CategoryDiscountAuditListResponse(
        items=[
            CategoryDiscountAuditEntryResponse(
                action=str(entry["action"]),
                previous_percent=entry.get("previous_percent"),
                new_percent=entry.get("new_percent"),
                actor_user_id=str(entry["actor_user_id"]),
                created_at=entry["created_at"],
            )
            for entry in entries
        ]
    )
