from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_auth_service, get_current_user, get_staff_service
from app.models.user import User
from app.schemas.auth import (
    AuthMessageResponse,
    AuthResponse,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    UpdateUserConfigurationRequest,
    UserConfigurationPayload,
    UserResponse,
)
from app.schemas.staff import AcceptStaffInvitationRequest
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    PasswordResetTokenInvalidOrExpiredError,
)
from app.services.staff_service import StaffInvitationInvalidError, StaffService

router = APIRouter(prefix="/auth", tags=["auth"])


def _merge_nested_documents(
    current: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(current)
    for key, value in incoming.items():
        current_value = merged.get(key)
        if isinstance(current_value, dict) and isinstance(value, dict):
            merged[key] = _merge_nested_documents(current_value, value)
        else:
            merged[key] = value
    return merged


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        result = auth_service.register(
            name=payload.name,
            email=str(payload.email),
            password=payload.password,
            user_types=payload.user_types,
            user_configuration=payload.user_configuration.to_document(),
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered.",
        ) from exc

    return AuthResponse.from_result(result)


@router.post("/login", response_model=AuthResponse, status_code=status.HTTP_200_OK)
def login(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        result = auth_service.login(
            email=str(payload.email),
            password=payload.password,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from exc

    return AuthResponse.from_result(result)


@router.post(
    "/password-reset/request",
    response_model=AuthMessageResponse,
    status_code=status.HTTP_200_OK,
)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthMessageResponse:
    auth_service.request_password_reset(
        email=str(payload.email),
        request_ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )
    return AuthMessageResponse(
        message="If that email exists, a password reset link has been sent."
    )


@router.post(
    "/password-reset/confirm",
    response_model=AuthMessageResponse,
    status_code=status.HTTP_200_OK,
)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthMessageResponse:
    try:
        auth_service.confirm_password_reset(
            token=payload.token,
            new_password=payload.password,
        )
    except PasswordResetTokenInvalidOrExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset link is invalid or expired.",
        ) from exc
    return AuthMessageResponse(message="Password updated successfully.")


@router.post(
    "/staff-invitations/{token}/accept",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
)
def accept_staff_invitation(
    token: str,
    payload: AcceptStaffInvitationRequest,
    staff_service: StaffService = Depends(get_staff_service),
) -> AuthResponse:
    try:
        result = staff_service.accept_invitation(token=token, password=payload.password)
    except StaffInvitationInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation link is invalid or has expired.",
        ) from exc
    return AuthResponse.from_result(result)


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.from_user(current_user)


@router.patch("/me/configuration", response_model=UserResponse, status_code=status.HTTP_200_OK)
def update_user_configuration(
    payload: UpdateUserConfigurationRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    merged_configuration = _merge_nested_documents(
        dict(current_user.user_configuration or {}),
        payload.user_configuration.to_document(),
    )
    normalized_configuration = UserConfigurationPayload.model_validate(merged_configuration)
    updated_user = auth_service.update_user_configuration(
        current_user=current_user,
        user_configuration=normalized_configuration.to_document(),
    )
    return UserResponse.from_user(updated_user)
