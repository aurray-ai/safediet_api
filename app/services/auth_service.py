import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    verify_password,
)
from app.models.user import User, UserType
from app.repositories.password_reset_token_repository import PasswordResetTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class PasswordResetTokenInvalidOrExpiredError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AuthResult:
    access_token: str
    token_type: str
    user: User


class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        email_service: EmailService,
        password_reset_token_repository: PasswordResetTokenRepository,
        settings: Settings,
    ) -> None:
        self._user_repository = user_repository
        self._email_service = email_service
        self._password_reset_token_repository = password_reset_token_repository
        self._settings = settings

    def register(
        self,
        *,
        name: str,
        email: str,
        password: str,
        user_types: list[UserType],
        user_configuration: dict[str, object],
    ) -> AuthResult:
        normalized_email = email.strip().lower()

        if self._user_repository.find_by_email(normalized_email) is not None:
            raise EmailAlreadyRegisteredError

        try:
            user = self._user_repository.create(
                name=name.strip(),
                email=normalized_email,
                password_hash=hash_password(password),
                user_types=user_types,
                user_configuration=user_configuration,
            )
        except DuplicateKeyError as exc:
            raise EmailAlreadyRegisteredError from exc

        self._send_registration_email(user)
        return self._build_auth_result(user)

    def login(self, email: str, password: str) -> AuthResult:
        normalized_email = email.strip().lower()
        user = self._user_repository.find_by_email(normalized_email)

        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError

        return self._build_auth_result(user)

    def update_user_configuration(
        self,
        *,
        current_user: User,
        user_configuration: dict[str, object],
    ) -> User:
        updated_user = self._user_repository.update_user_configuration(
            user_id=current_user.id,
            user_configuration=user_configuration,
        )
        if updated_user is None:
            return current_user
        return updated_user

    def request_password_reset(
        self,
        *,
        email: str,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        normalized_email = email.strip().lower()
        user = self._user_repository.find_by_email(normalized_email)
        if user is None:
            return

        self._password_reset_token_repository.invalidate_for_user(user_id=user.id)
        raw_token = generate_password_reset_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self._settings.password_reset_token_ttl_minutes
        )
        self._password_reset_token_repository.create_token(
            user_id=user.id,
            token_hash=hash_password_reset_token(raw_token),
            expires_at=expires_at,
            request_ip=request_ip,
            user_agent=user_agent,
        )
        self._email_service.send_password_reset_email(
            user=user,
            reset_token=raw_token,
            expires_at=expires_at,
        )

    def confirm_password_reset(
        self,
        *,
        token: str,
        new_password: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        token_record = self._password_reset_token_repository.find_active_by_token_hash(
            token_hash=hash_password_reset_token(token),
            now=now,
        )
        if token_record is None:
            raise PasswordResetTokenInvalidOrExpiredError

        user = self._user_repository.find_by_id(token_record.user_id)
        if user is None:
            raise PasswordResetTokenInvalidOrExpiredError

        updated_user = self._user_repository.update_password_hash(
            user_id=user.id,
            password_hash=hash_password(new_password),
        )
        self._password_reset_token_repository.mark_used(token_id=token_record.id)
        self._password_reset_token_repository.invalidate_for_user(user_id=user.id)
        if updated_user is not None:
            self._email_service.send_password_reset_success_email(user=updated_user)

    def _send_registration_email(self, user: User) -> None:
        try:
            self._email_service.send_registration_email(user=user)
        except Exception:
            logger.exception(
                "auth.send_registration_email failed user_id=%s email=%s",
                user.id,
                user.email,
            )

    @staticmethod
    def _build_auth_result(user: User) -> AuthResult:
        return AuthResult(
            access_token=create_access_token(subject=user.id),
            token_type="bearer",
            user=user,
        )
