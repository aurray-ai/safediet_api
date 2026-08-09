from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from app.core.config import Settings
from app.core.security import verify_password
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserType
from app.services.auth_service import (
    AuthService,
    PasswordResetTokenInvalidOrExpiredError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_user() -> User:
    return User(
        id="user-1",
        name="Ada",
        email="ada@example.com",
        password_hash="hashed-password",
        user_types=[UserType.CUSTOMER],
        user_configuration={"mode": "solo", "goal": "maintain"},
        created_at=utc_now(),
    )


class StubUserRepository:
    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.updated_password_hash: str | None = None

    def find_by_email(self, email: str) -> User | None:
        if self.user is None:
            return None
        return self.user if self.user.email == email else None

    def find_by_id(self, user_id: str) -> User | None:
        if self.user is None:
            return None
        return self.user if self.user.id == user_id else None

    def create(self, *, name: str, email: str, password_hash: str, user_types, user_configuration):
        self.user = User(
            id="created-user",
            name=name,
            email=email,
            password_hash=password_hash,
            user_types=list(user_types),
            user_configuration=dict(user_configuration),
            created_at=utc_now(),
        )
        return self.user

    def update_password_hash(self, *, user_id: str, password_hash: str) -> User | None:
        if self.user is None or self.user.id != user_id:
            return None
        self.updated_password_hash = password_hash
        self.user = replace(self.user, password_hash=password_hash)
        return self.user

    def update_user_configuration(self, *, user_id: str, user_configuration: dict[str, object]) -> User | None:
        if self.user is None or self.user.id != user_id:
            return None
        self.user = replace(self.user, user_configuration=dict(user_configuration))
        return self.user


class StubPasswordResetTokenRepository:
    def __init__(self) -> None:
        self.created: list[PasswordResetToken] = []
        self.invalidated_user_ids: list[str] = []
        self.marked_used_ids: list[str] = []
        self.active_token: PasswordResetToken | None = None

    def create_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        request_ip: str | None,
        user_agent: str | None,
    ) -> PasswordResetToken:
        token = PasswordResetToken(
            id="token-1",
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            used_at=None,
            created_at=utc_now(),
            request_ip=request_ip,
            user_agent=user_agent,
        )
        self.created.append(token)
        self.active_token = token
        return token

    def find_active_by_token_hash(self, *, token_hash: str, now: datetime) -> PasswordResetToken | None:
        if self.active_token is None:
            return None
        if self.active_token.token_hash != token_hash:
            return None
        if self.active_token.expires_at <= now:
            return None
        return self.active_token

    def mark_used(self, *, token_id: str) -> None:
        self.marked_used_ids.append(token_id)

    def invalidate_for_user(self, *, user_id: str) -> None:
        self.invalidated_user_ids.append(user_id)


class StubEmailService:
    def __init__(self) -> None:
        self.registration_emails: list[str] = []
        self.reset_emails: list[dict[str, str]] = []
        self.reset_success_emails: list[str] = []

    def send_registration_email(self, *, user: User) -> None:
        self.registration_emails.append(user.email)

    def send_password_reset_email(self, *, user: User, reset_token: str, expires_at: datetime) -> None:
        self.reset_emails.append(
            {"email": user.email, "token": reset_token, "expires_at": expires_at.isoformat()}
        )

    def send_password_reset_success_email(self, *, user: User) -> None:
        self.reset_success_emails.append(user.email)


class FailingEmailService(StubEmailService):
    def send_registration_email(self, *, user: User) -> None:
        raise RuntimeError("email down")


class AuthServiceEmailAndResetTests(unittest.TestCase):
    def test_register_swallows_welcome_email_failure(self) -> None:
        user_repository = StubUserRepository()
        service = AuthService(
            user_repository=user_repository,
            email_service=FailingEmailService(),
            password_reset_token_repository=StubPasswordResetTokenRepository(),
            settings=Settings(),
        )

        result = service.register(
            name="Ada",
            email="ada@example.com",
            password="ValidPass123",
            user_types=[UserType.CUSTOMER],
            user_configuration={"mode": "solo", "goal": "maintain"},
        )

        self.assertEqual("ada@example.com", result.user.email)

    def test_request_password_reset_creates_token_and_sends_email(self) -> None:
        user = make_user()
        email_service = StubEmailService()
        token_repository = StubPasswordResetTokenRepository()
        service = AuthService(
            user_repository=StubUserRepository(user),
            email_service=email_service,
            password_reset_token_repository=token_repository,
            settings=Settings(password_reset_token_ttl_minutes=30),
        )

        service.request_password_reset(
            email="ada@example.com",
            request_ip="127.0.0.1",
            user_agent="pytest",
        )

        self.assertEqual(["user-1"], token_repository.invalidated_user_ids)
        self.assertEqual(1, len(token_repository.created))
        self.assertEqual("127.0.0.1", token_repository.created[0].request_ip)
        self.assertEqual(1, len(email_service.reset_emails))
        self.assertEqual("ada@example.com", email_service.reset_emails[0]["email"])

    def test_confirm_password_reset_updates_password_and_sends_success_email(self) -> None:
        user = make_user()
        email_service = StubEmailService()
        token_repository = StubPasswordResetTokenRepository()
        service = AuthService(
            user_repository=StubUserRepository(user),
            email_service=email_service,
            password_reset_token_repository=token_repository,
            settings=Settings(),
        )

        service.request_password_reset(email="ada@example.com")
        raw_token = email_service.reset_emails[0]["token"]

        service.confirm_password_reset(token=raw_token, new_password="NewPass123")

        self.assertEqual(["token-1"], token_repository.marked_used_ids)
        self.assertIn("user-1", token_repository.invalidated_user_ids)
        self.assertEqual(["ada@example.com"], email_service.reset_success_emails)
        self.assertTrue(verify_password("NewPass123", service._user_repository.user.password_hash))

    def test_confirm_password_reset_rejects_invalid_token(self) -> None:
        service = AuthService(
            user_repository=StubUserRepository(make_user()),
            email_service=StubEmailService(),
            password_reset_token_repository=StubPasswordResetTokenRepository(),
            settings=Settings(),
        )

        with self.assertRaises(PasswordResetTokenInvalidOrExpiredError):
            service.confirm_password_reset(token="missing-token", new_password="NewPass123")


if __name__ == "__main__":
    unittest.main()
