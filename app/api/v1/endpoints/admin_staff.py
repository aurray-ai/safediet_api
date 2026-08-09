from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_staff_service, require_platform_user
from app.models.user import User, UserType
from app.schemas.staff import CreateStaffRequest, StaffListResponse, StaffUserResponse, UpdateStaffRequest
from app.services.staff_service import (
    StaffEmailAlreadyRegisteredError,
    StaffNotFoundError,
    StaffService,
    StaffValidationError,
)

router = APIRouter(prefix="/admin/staff", tags=["admin-staff"])


def _to_response(user: User) -> StaffUserResponse:
    return StaffUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        user_types=[user_type.value for user_type in user.user_types],
        staff_type=user.staff_type.value if user.staff_type is not None else None,
        created_at=user.created_at,
    )


@router.get("", response_model=StaffListResponse, status_code=status.HTTP_200_OK)
def list_staff(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    role: UserType | None = Query(default=None),
    _: User = Depends(require_platform_user),
    staff_service: StaffService = Depends(get_staff_service),
) -> StaffListResponse:
    items, total = staff_service.list_staff(page=page, page_size=page_size, search=search, role=role)
    return StaffListResponse(
        items=[_to_response(user) for user in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=StaffUserResponse, status_code=status.HTTP_201_CREATED)
def create_staff_member(
    payload: CreateStaffRequest,
    current_admin: User = Depends(require_platform_user),
    staff_service: StaffService = Depends(get_staff_service),
) -> StaffUserResponse:
    try:
        created = staff_service.create_staff(
            name=payload.name,
            email=str(payload.email),
            user_types=payload.user_types,
            staff_type=payload.staff_type,
            actor_user_id=current_admin.id,
        )
    except StaffEmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists, or an invite is already pending.",
        ) from exc
    return _to_response(created)


@router.post("/{user_id}/roles", response_model=StaffUserResponse, status_code=status.HTTP_200_OK)
def update_staff_roles(
    user_id: str,
    payload: UpdateStaffRequest,
    _: User = Depends(require_platform_user),
    staff_service: StaffService = Depends(get_staff_service),
) -> StaffUserResponse:
    try:
        updated = staff_service.update_staff(
            user_id=user_id,
            user_types=payload.user_types,
            staff_type=payload.staff_type,
        )
    except StaffNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.") from exc
    except StaffValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(updated)
