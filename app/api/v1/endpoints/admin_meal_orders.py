from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_chef_fulfillment_service, require_platform_user
from app.models.user import User
from app.schemas.fulfillment import (
    AssignWorkerRequest,
    MealOrderFulfillmentListResponse,
    MealOrderFulfillmentResponse,
    WorkerListResponse,
    WorkerRosterEntryResponse,
    WorkerRosterListResponse,
    WorkerSummaryResponse,
)
from app.services.chef_fulfillment_service import (
    ChefFulfillmentService,
    FulfillmentNotFoundError,
    FulfillmentStateError,
)
from app.services.fulfillment_response_mappers import meal_order_to_fulfillment_response

router = APIRouter(prefix="/admin/meal-orders", tags=["admin-meal-orders"])


@router.get("", response_model=MealOrderFulfillmentListResponse, status_code=status.HTTP_200_OK)
def list_unassigned_meal_orders(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    _: User = Depends(require_platform_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentListResponse:
    items, next_cursor = chef_fulfillment_service.list_unassigned_for_admin(before=before, limit=limit)
    return MealOrderFulfillmentListResponse(
        items=[meal_order_to_fulfillment_response(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/chefs", response_model=WorkerListResponse, status_code=status.HTTP_200_OK)
def list_available_chefs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> WorkerListResponse:
    items, total = chef_fulfillment_service.list_available_chefs(page=page, page_size=page_size, search=search)
    return WorkerListResponse(
        items=[WorkerSummaryResponse(id=user.id, name=user.name, email=user.email) for user in items],
        total=total,
    )


@router.get("/chefs/roster", response_model=WorkerRosterListResponse, status_code=status.HTTP_200_OK)
def list_chef_roster(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> WorkerRosterListResponse:
    entries, total = chef_fulfillment_service.list_chef_roster(page=page, page_size=page_size, search=search)
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


@router.get("/{order_id}", response_model=MealOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
def get_meal_order_for_admin(
    order_id: str,
    _: User = Depends(require_platform_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentResponse:
    try:
        return meal_order_to_fulfillment_response(chef_fulfillment_service.get_for_admin(order_id=order_id))
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal order not found.") from exc


@router.post("/{order_id}/assign", response_model=MealOrderFulfillmentResponse, status_code=status.HTTP_200_OK)
async def assign_meal_order_to_chef(
    order_id: str,
    payload: AssignWorkerRequest,
    current_admin: User = Depends(require_platform_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
) -> MealOrderFulfillmentResponse:
    try:
        updated = await chef_fulfillment_service.assign(
            order_id=order_id,
            chef_id=payload.worker_id,
            actor_user_id=current_admin.id,
            note=payload.note,
        )
    except FulfillmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal order not found.") from exc
    except FulfillmentStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return meal_order_to_fulfillment_response(updated)
