from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_admin_customer_service, require_platform_user
from app.models.meal_order import MealOrder
from app.models.order import Order
from app.models.user import User
from app.schemas.admin_customer import (
    AdminCustomerAuditEntryResponse,
    AdminCustomerAuditListResponse,
    AdminCustomerDetailResponse,
    AdminCustomerListResponse,
    AdminCustomerOrderSummaryResponse,
    AdminCustomerSummaryResponse,
    CancelCustomerSubscriptionRequest,
)
from app.services.admin_customer_service import (
    AdminCustomerDetail,
    AdminCustomerService,
    CustomerNotFoundError,
    CustomerSubscriptionCancelFailedError,
    CustomerSubscriptionNotActiveError,
)

router = APIRouter(prefix="/admin/customers", tags=["admin-customers"])


def _to_summary_response(user: User) -> AdminCustomerSummaryResponse:
    return AdminCustomerSummaryResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
    )


def _grocery_order_to_summary(order: Order) -> AdminCustomerOrderSummaryResponse:
    return AdminCustomerOrderSummaryResponse(
        id=order.id,
        order_number=order.order_number,
        kind="grocery",
        status=order.status,
        total_minor=order.pricing_summary.total_minor,
        currency=order.currency,
        created_at=order.created_at,
    )


def _meal_order_to_summary(order: MealOrder) -> AdminCustomerOrderSummaryResponse:
    return AdminCustomerOrderSummaryResponse(
        id=order.id,
        order_number=order.order_number,
        kind="meal",
        status=order.status,
        total_minor=order.pricing_summary.total_minor,
        currency=order.currency,
        created_at=order.created_at,
    )


def _to_detail_response(detail: AdminCustomerDetail) -> AdminCustomerDetailResponse:
    recent_orders = sorted(
        [_grocery_order_to_summary(order) for order in detail.recent_grocery_orders]
        + [_meal_order_to_summary(order) for order in detail.recent_meal_orders],
        key=lambda item: item.created_at,
        reverse=True,
    )[:5]

    return AdminCustomerDetailResponse(
        id=detail.user.id,
        name=detail.user.name,
        email=detail.user.email,
        user_types=[user_type.value for user_type in detail.user.user_types],
        created_at=detail.user.created_at,
        subscription=detail.billing_overview.subscription,
        wallet=detail.billing_overview.wallet,
        recent_orders=recent_orders,
    )


@router.get("", response_model=AdminCustomerListResponse, status_code=status.HTTP_200_OK)
def list_customers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    admin_customer_service: AdminCustomerService = Depends(get_admin_customer_service),
) -> AdminCustomerListResponse:
    items, total = admin_customer_service.list_customers(page=page, page_size=page_size, search=search)
    return AdminCustomerListResponse(
        items=[_to_summary_response(user) for user in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", response_model=AdminCustomerDetailResponse, status_code=status.HTTP_200_OK)
def get_customer(
    user_id: str,
    _: User = Depends(require_platform_user),
    admin_customer_service: AdminCustomerService = Depends(get_admin_customer_service),
) -> AdminCustomerDetailResponse:
    try:
        detail = admin_customer_service.get_customer_detail(user_id=user_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.") from exc
    return _to_detail_response(detail)


@router.post(
    "/{user_id}/subscription/cancel",
    response_model=AdminCustomerDetailResponse,
    status_code=status.HTTP_200_OK,
)
def cancel_customer_subscription(
    user_id: str,
    payload: CancelCustomerSubscriptionRequest,
    current_admin: User = Depends(require_platform_user),
    admin_customer_service: AdminCustomerService = Depends(get_admin_customer_service),
) -> AdminCustomerDetailResponse:
    try:
        admin_customer_service.cancel_subscription(
            user_id=user_id,
            reason=payload.reason,
            actor_user_id=current_admin.id,
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.") from exc
    except CustomerSubscriptionNotActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This customer does not have an active subscription to cancel.",
        ) from exc
    except CustomerSubscriptionCancelFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not cancel the subscription with the payment provider. Nothing was changed.",
        ) from exc

    detail = admin_customer_service.get_customer_detail(user_id=user_id)
    return _to_detail_response(detail)


@router.get(
    "/{user_id}/audit-log",
    response_model=AdminCustomerAuditListResponse,
    status_code=status.HTTP_200_OK,
)
def get_customer_audit_log(
    user_id: str,
    _: User = Depends(require_platform_user),
    admin_customer_service: AdminCustomerService = Depends(get_admin_customer_service),
) -> AdminCustomerAuditListResponse:
    entries = admin_customer_service.list_audit_log(user_id=user_id)
    return AdminCustomerAuditListResponse(
        items=[
            AdminCustomerAuditEntryResponse(
                action=str(entry["action"]),
                details=dict(entry.get("details") or {}),
                actor_user_id=str(entry["actor_user_id"]),
                created_at=entry["created_at"],
            )
            for entry in entries
        ]
    )
