from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from app.models.invitation import Invitation, InvitationStatus, InvitationType
from app.models.user import StaffType, User, UserType
from app.services.staff_service import (
    StaffEmailAlreadyRegisteredError,
    StaffInvitationInvalidError,
    StaffNotFoundError,
    StaffService,
    StaffValidationError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user(
    *, user_id: str, user_types: list[UserType], email: str | None = None, staff_type: StaffType | None = None
) -> User:
    return User(
        id=user_id,
        name=f"User {user_id}",
        email=email or f"{user_id}@example.com",
        password_hash="x",
        user_types=user_types,
        user_configuration={},
        created_at=utc_now(),
        staff_type=staff_type,
    )


class StubUserRepository:
    def __init__(self, users: dict[str, User] | None = None) -> None:
        self.users: dict[str, User] = dict(users or {})
        self.update_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.password_update_calls: list[dict] = []

    def find_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def find_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        for user in self.users.values():
            if user.email.lower() == normalized:
                return user
        return None

    def list_users(self, *, page, page_size, search=None, user_type=None):
        items = [
            user
            for user in self.users.values()
            if user_type is None or user_type in user.user_types
        ]
        return items, len(items)

    def create(self, *, name, email, password_hash, user_types, user_configuration, staff_type=None) -> User:
        self.create_calls.append(
            {
                "name": name,
                "email": email,
                "password_hash": password_hash,
                "user_types": user_types,
                "staff_type": staff_type,
            }
        )
        user = User(
            id=f"user-{len(self.users) + 1}",
            name=name,
            email=email,
            password_hash=password_hash,
            user_types=user_types,
            user_configuration=user_configuration,
            created_at=utc_now(),
            staff_type=staff_type,
        )
        self.users[user.id] = user
        return user

    def update_staff_profile(self, *, user_id: str, user_types: list[UserType], staff_type: StaffType | None) -> User | None:
        self.update_calls.append({"user_id": user_id, "user_types": user_types, "staff_type": staff_type})
        user = self.users.get(user_id)
        if user is None:
            return None
        updated = build_user(user_id=user.id, user_types=user_types, email=user.email, staff_type=staff_type)
        self.users[user_id] = updated
        return updated

    def update_password_hash(self, *, user_id: str, password_hash: str) -> User | None:
        self.password_update_calls.append({"user_id": user_id, "password_hash": password_hash})
        user = self.users.get(user_id)
        if user is None:
            return None
        updated = build_user(
            user_id=user.id, user_types=user.user_types, email=user.email, staff_type=user.staff_type
        )
        self.users[user_id] = updated
        return updated


class StubInvitationRepository:
    def __init__(self, invitations: dict[str, Invitation] | None = None) -> None:
        self.items: dict[str, Invitation] = dict(invitations or {})
        self.create_calls: list[dict] = []
        self.mark_accepted_calls: list[dict] = []

    def create(
        self,
        *,
        invitation_type,
        invited_by_user_id,
        invitee_email,
        invitee_user_id,
        display_name,
        token_hash,
        expires_at,
        context,
    ) -> Invitation:
        self.create_calls.append(
            {
                "invitation_type": invitation_type,
                "invitee_email": invitee_email,
                "invitee_user_id": invitee_user_id,
                "token_hash": token_hash,
                "context": context,
            }
        )
        item = Invitation(
            id=f"invite-{len(self.items) + 1}",
            invitation_type=invitation_type,
            invited_by_user_id=invited_by_user_id,
            invitee_email=invitee_email,
            invitee_user_id=invitee_user_id,
            display_name=display_name,
            status=InvitationStatus.PENDING,
            token_hash=token_hash,
            expires_at=expires_at,
            accepted_at=None,
            accepted_by_user_id=None,
            context=dict(context),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_pending_by_type_and_email(self, *, invitation_type, invitee_email, context_filters, now):
        normalized = invitee_email.strip().lower()
        for item in self.items.values():
            if (
                item.invitation_type == invitation_type
                and item.invitee_email.lower() == normalized
                and item.status == InvitationStatus.PENDING
                and item.expires_at > now
            ):
                return item
        return None

    def find_active_by_token_hash(self, *, token_hash, now):
        for item in self.items.values():
            if item.token_hash == token_hash and item.status == InvitationStatus.PENDING and item.expires_at > now:
                return item
        return None

    def mark_accepted(self, *, invitation_id, accepted_by_user_id):
        self.mark_accepted_calls.append({"invitation_id": invitation_id, "accepted_by_user_id": accepted_by_user_id})
        current = self.items.get(invitation_id)
        if current is None:
            return None
        updated = Invitation(
            id=current.id,
            invitation_type=current.invitation_type,
            invited_by_user_id=current.invited_by_user_id,
            invitee_email=current.invitee_email,
            invitee_user_id=current.invitee_user_id,
            display_name=current.display_name,
            status=InvitationStatus.ACCEPTED,
            token_hash=current.token_hash,
            expires_at=current.expires_at,
            accepted_at=utc_now(),
            accepted_by_user_id=accepted_by_user_id,
            context=dict(current.context),
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[invitation_id] = updated
        return updated


class StubEmailService:
    def __init__(self) -> None:
        self.invitation_calls: list[dict] = []

    def send_staff_invitation_email(self, *, user, user_types, setup_token, expires_at) -> None:
        self.invitation_calls.append(
            {"user": user, "user_types": user_types, "setup_token": setup_token, "expires_at": expires_at}
        )


def build_service(*, users=None, invitations=None):
    user_repository = StubUserRepository(users)
    invitation_repository = StubInvitationRepository(invitations)
    email_service = StubEmailService()
    settings = SimpleNamespace(staff_invitation_token_ttl_days=7)
    service = StaffService(
        user_repository=user_repository,
        invitation_repository=invitation_repository,
        email_service=email_service,
        settings=settings,
    )
    return service, user_repository, invitation_repository, email_service


class StaffServiceTests(unittest.TestCase):
    def test_list_staff_filters_by_role(self) -> None:
        service, _, _, _ = build_service(
            users={
                "u1": build_user(user_id="u1", user_types=[UserType.CHEF]),
                "u2": build_user(user_id="u2", user_types=[UserType.CUSTOMER]),
            }
        )

        items, total = service.list_staff(page=1, page_size=20, role=UserType.CHEF)

        self.assertEqual(1, total)
        self.assertEqual("u1", items[0].id)

    def test_update_staff_raises_when_user_missing(self) -> None:
        service, _, _, _ = build_service()

        with self.assertRaises(StaffNotFoundError):
            service.update_staff(user_id="missing", user_types=[UserType.CHEF], staff_type=None)

    def test_update_staff_raises_on_empty_list(self) -> None:
        service, _, _, _ = build_service(users={"u1": build_user(user_id="u1", user_types=[UserType.CUSTOMER])})

        with self.assertRaises(StaffValidationError):
            service.update_staff(user_id="u1", user_types=[], staff_type=None)

    def test_update_staff_dedupes_roles_and_sets_staff_type(self) -> None:
        service, repository, _, _ = build_service(
            users={"u1": build_user(user_id="u1", user_types=[UserType.CUSTOMER])}
        )

        updated = service.update_staff(
            user_id="u1",
            user_types=[UserType.CHEF, UserType.CHEF, UserType.SHOPPER],
            staff_type=StaffType.CONTRACTOR,
        )

        self.assertEqual(1, len(repository.update_calls))
        self.assertEqual(StaffType.CONTRACTOR, repository.update_calls[0]["staff_type"])
        self.assertEqual(
            sorted([UserType.CHEF.value, UserType.SHOPPER.value]),
            sorted(user_type.value for user_type in repository.update_calls[0]["user_types"]),
        )
        self.assertIn(UserType.CHEF, updated.user_types)
        self.assertIn(UserType.SHOPPER, updated.user_types)
        self.assertEqual(StaffType.CONTRACTOR, updated.staff_type)

    def test_create_staff_creates_user_and_invitation_and_sends_email(self) -> None:
        service, user_repository, invitation_repository, email_service = build_service()

        created = service.create_staff(
            name="New Chef",
            email="New.Chef@Example.com",
            user_types=[UserType.CHEF],
            staff_type=StaffType.FULL_TIME,
            actor_user_id="admin-1",
        )

        self.assertEqual("new.chef@example.com", created.email)
        self.assertEqual(StaffType.FULL_TIME, created.staff_type)
        self.assertEqual(1, len(user_repository.create_calls))
        self.assertEqual(1, len(invitation_repository.create_calls))
        invite_call = invitation_repository.create_calls[0]
        self.assertEqual(InvitationType.STAFF, invite_call["invitation_type"])
        self.assertEqual(created.id, invite_call["invitee_user_id"])
        self.assertEqual(["chef"], invite_call["context"]["user_types"])
        self.assertEqual("full_time", invite_call["context"]["staff_type"])
        self.assertEqual(1, len(email_service.invitation_calls))
        self.assertEqual(created.id, email_service.invitation_calls[0]["user"].id)

    def test_create_staff_raises_when_email_already_registered(self) -> None:
        service, _, _, _ = build_service(
            users={"u1": build_user(user_id="u1", user_types=[UserType.CUSTOMER], email="taken@example.com")}
        )

        with self.assertRaises(StaffEmailAlreadyRegisteredError):
            service.create_staff(
                name="Dup", email="taken@example.com", user_types=[UserType.CHEF], staff_type=None, actor_user_id="admin-1"
            )

    def test_create_staff_raises_when_invitation_already_pending(self) -> None:
        now = utc_now()
        pending = Invitation(
            id="invite-1",
            invitation_type=InvitationType.STAFF,
            invited_by_user_id="admin-1",
            invitee_email="pending@example.com",
            invitee_user_id="u1",
            display_name="Pending Person",
            status=InvitationStatus.PENDING,
            token_hash="hash",
            expires_at=now + timedelta(days=1),
            accepted_at=None,
            accepted_by_user_id=None,
            context={"user_types": ["chef"], "staff_type": None},
            created_at=now,
            updated_at=now,
        )
        service, _, _, _ = build_service(invitations={"invite-1": pending})

        with self.assertRaises(StaffEmailAlreadyRegisteredError):
            service.create_staff(
                name="Another",
                email="pending@example.com",
                user_types=[UserType.CHEF],
                staff_type=None,
                actor_user_id="admin-1",
            )

    def test_accept_invitation_sets_password_and_marks_accepted(self) -> None:
        now = utc_now()
        chef = build_user(user_id="u1", user_types=[UserType.CHEF], email="chef@example.com")
        invitation = Invitation(
            id="invite-1",
            invitation_type=InvitationType.STAFF,
            invited_by_user_id="admin-1",
            invitee_email="chef@example.com",
            invitee_user_id="u1",
            display_name="Chef",
            status=InvitationStatus.PENDING,
            token_hash="known-hash",
            expires_at=now + timedelta(days=1),
            accepted_at=None,
            accepted_by_user_id=None,
            context={"user_types": ["chef"], "staff_type": None},
            created_at=now,
            updated_at=now,
        )
        service, user_repository, invitation_repository, _ = build_service(
            users={"u1": chef}, invitations={"invite-1": invitation}
        )

        with mock.patch("app.services.staff_service.hash_invitation_token", return_value="known-hash"):
            result = service.accept_invitation(token="raw-token", password="Str0ngPassw0rd!")

        self.assertEqual("u1", result.user.id)
        self.assertTrue(result.access_token)
        self.assertEqual(1, len(user_repository.password_update_calls))
        self.assertEqual(1, len(invitation_repository.mark_accepted_calls))
        self.assertEqual("u1", invitation_repository.mark_accepted_calls[0]["accepted_by_user_id"])

    def test_accept_invitation_raises_for_unknown_token(self) -> None:
        service, _, _, _ = build_service()

        with self.assertRaises(StaffInvitationInvalidError):
            service.accept_invitation(token="missing", password="Str0ngPassw0rd!")

    def test_accept_invitation_raises_for_wrong_invitation_type(self) -> None:
        now = utc_now()
        household_invite = Invitation(
            id="invite-1",
            invitation_type=InvitationType.HOUSEHOLD,
            invited_by_user_id="admin-1",
            invitee_email="member@example.com",
            invitee_user_id="u1",
            display_name="Member",
            status=InvitationStatus.PENDING,
            token_hash="known-hash",
            expires_at=now + timedelta(days=1),
            accepted_at=None,
            accepted_by_user_id=None,
            context={"household_id": "hh-1", "role": "adult", "share_weight": 1},
            created_at=now,
            updated_at=now,
        )
        service, _, _, _ = build_service(invitations={"invite-1": household_invite})

        with mock.patch("app.services.staff_service.hash_invitation_token", return_value="known-hash"):
            with self.assertRaises(StaffInvitationInvalidError):
                service.accept_invitation(token="raw-token", password="Str0ngPassw0rd!")


if __name__ == "__main__":
    unittest.main()
