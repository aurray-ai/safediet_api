from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    generate_invitation_token,
    hash_invitation_token,
    hash_password,
)
from app.models.invitation import InvitationType
from app.models.user import StaffType, User, UserType
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthResult
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


class StaffNotFoundError(Exception):
    pass


class StaffValidationError(Exception):
    pass


class StaffEmailAlreadyRegisteredError(Exception):
    pass


class StaffInvitationInvalidError(Exception):
    pass


class StaffService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        invitation_repository: InvitationRepository,
        email_service: EmailService,
        settings: Settings,
    ) -> None:
        self._user_repository = user_repository
        self._invitation_repository = invitation_repository
        self._email_service = email_service
        self._settings = settings

    def list_staff(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        role: UserType | None = None,
    ) -> tuple[list[User], int]:
        return self._user_repository.list_users(page=page, page_size=page_size, search=search, user_type=role)

    def create_staff(
        self,
        *,
        name: str,
        email: str,
        user_types: list[UserType],
        staff_type: StaffType | None,
        actor_user_id: str | None,
    ) -> User:
        normalized_email = email.strip().lower()
        now = datetime.now(timezone.utc)

        if self._user_repository.find_by_email(normalized_email) is not None:
            raise StaffEmailAlreadyRegisteredError

        if self._invitation_repository.get_pending_by_type_and_email(
            invitation_type=InvitationType.STAFF,
            invitee_email=normalized_email,
            context_filters=None,
            now=now,
        ) is not None:
            raise StaffEmailAlreadyRegisteredError

        user = self._user_repository.create(
            name=name.strip(),
            email=normalized_email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            user_types=user_types,
            user_configuration={},
            staff_type=staff_type,
        )

        raw_token = generate_invitation_token()
        expires_at = now + timedelta(days=self._settings.staff_invitation_token_ttl_days)
        self._invitation_repository.create(
            invitation_type=InvitationType.STAFF,
            invited_by_user_id=actor_user_id,
            invitee_email=normalized_email,
            invitee_user_id=user.id,
            display_name=user.name,
            token_hash=hash_invitation_token(raw_token),
            expires_at=expires_at,
            context={
                "user_types": [user_type.value for user_type in user_types],
                "staff_type": staff_type.value if staff_type is not None else None,
            },
        )

        self._send_staff_invitation_email(user=user, user_types=user_types, setup_token=raw_token, expires_at=expires_at)
        return user

    def update_staff(self, *, user_id: str, user_types: list[UserType], staff_type: StaffType | None) -> User:
        if not user_types:
            raise StaffValidationError("At least one role is required.")
        target = self._user_repository.find_by_id(user_id)
        if target is None:
            raise StaffNotFoundError
        deduped = sorted(set(user_types), key=lambda user_type: user_type.value)
        updated = self._user_repository.update_staff_profile(
            user_id=user_id,
            user_types=deduped,
            staff_type=staff_type,
        )
        if updated is None:
            raise StaffNotFoundError
        return updated

    def accept_invitation(self, *, token: str, password: str) -> AuthResult:
        now = datetime.now(timezone.utc)
        invitation = self._invitation_repository.find_active_by_token_hash(
            token_hash=hash_invitation_token(token),
            now=now,
        )
        if invitation is None or invitation.invitation_type != InvitationType.STAFF:
            raise StaffInvitationInvalidError

        user = (
            self._user_repository.find_by_id(invitation.invitee_user_id)
            if invitation.invitee_user_id is not None
            else None
        )
        if user is None:
            raise StaffInvitationInvalidError

        updated_user = self._user_repository.update_password_hash(
            user_id=user.id,
            password_hash=hash_password(password),
        )
        self._invitation_repository.mark_accepted(invitation_id=invitation.id, accepted_by_user_id=user.id)

        return AuthResult(
            access_token=create_access_token(subject=user.id),
            token_type="bearer",
            user=updated_user or user,
        )

    def _send_staff_invitation_email(
        self,
        *,
        user: User,
        user_types: list[UserType],
        setup_token: str,
        expires_at: datetime,
    ) -> None:
        try:
            self._email_service.send_staff_invitation_email(
                user=user,
                user_types=user_types,
                setup_token=setup_token,
                expires_at=expires_at,
            )
        except Exception:
            logger.exception(
                "staff_service.send_staff_invitation_email failed user_id=%s email=%s",
                user.id,
                user.email,
            )
