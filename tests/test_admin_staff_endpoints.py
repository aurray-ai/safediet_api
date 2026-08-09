from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.admin_staff import create_staff_member, list_staff, update_staff_roles
from app.models.user import StaffType, User, UserType
from app.schemas.staff import CreateStaffRequest, UpdateStaffRequest
from app.services.staff_service import (
    StaffEmailAlreadyRegisteredError,
    StaffNotFoundError,
    StaffValidationError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_admin() -> User:
    return User(
        id="admin-1",
        name="Admin",
        email="admin@example.com",
        password_hash="x",
        user_types=[UserType.PLATFORM_USER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_staff_user(
    *, user_id: str = "u1", user_types: list[UserType] | None = None, staff_type: StaffType | None = None
) -> User:
    return User(
        id=user_id,
        name="Staffer",
        email="staffer@example.com",
        password_hash="x",
        user_types=user_types or [UserType.CHEF],
        user_configuration={},
        created_at=utc_now(),
        staff_type=staff_type,
    )


class StubStaffService:
    def __init__(self, *, users: list[User] | None = None, error: Exception | None = None) -> None:
        self._users = users or []
        self._error = error
        self.update_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def list_staff(self, *, page, page_size, search=None, role=None):
        return self._users, len(self._users)

    def create_staff(self, *, name, email, user_types, staff_type, actor_user_id):
        self.create_calls.append(
            {
                "name": name,
                "email": email,
                "user_types": user_types,
                "staff_type": staff_type,
                "actor_user_id": actor_user_id,
            }
        )
        if self._error is not None:
            raise self._error
        return make_staff_user(user_types=user_types, staff_type=staff_type)

    def update_staff(self, *, user_id, user_types, staff_type):
        self.update_calls.append({"user_id": user_id, "user_types": user_types, "staff_type": staff_type})
        if self._error is not None:
            raise self._error
        return make_staff_user(user_id=user_id, user_types=user_types, staff_type=staff_type)


class AdminStaffEndpointTests(unittest.TestCase):
    def test_list_staff_returns_items(self) -> None:
        service = StubStaffService(users=[make_staff_user()])

        response = list_staff(page=1, page_size=20, search=None, role=None, _=make_admin(), staff_service=service)

        self.assertEqual(1, response.total)
        self.assertEqual("u1", response.items[0].id)
        self.assertIn("chef", response.items[0].user_types)

    def test_create_staff_member_returns_created_user(self) -> None:
        service = StubStaffService()
        payload = CreateStaffRequest(
            name="New Chef", email="new.chef@example.com", user_types=[UserType.CHEF], staff_type=StaffType.CONTRACTOR
        )

        response = create_staff_member(payload=payload, current_admin=make_admin(), staff_service=service)

        self.assertEqual(1, len(service.create_calls))
        self.assertEqual("admin-1", service.create_calls[0]["actor_user_id"])
        self.assertIn("chef", response.user_types)
        self.assertEqual("contractor", response.staff_type)

    def test_create_staff_member_maps_duplicate_email_to_409(self) -> None:
        service = StubStaffService(error=StaffEmailAlreadyRegisteredError())
        payload = CreateStaffRequest(name="Dup", email="dup@example.com", user_types=[UserType.CHEF])

        with self.assertRaises(HTTPException) as context:
            create_staff_member(payload=payload, current_admin=make_admin(), staff_service=service)

        self.assertEqual(409, context.exception.status_code)

    def test_update_staff_roles_returns_updated_user(self) -> None:
        service = StubStaffService()
        payload = UpdateStaffRequest(user_types=[UserType.CHEF, UserType.SHOPPER], staff_type=StaffType.PART_TIME)

        response = update_staff_roles(user_id="u1", payload=payload, _=make_admin(), staff_service=service)

        self.assertEqual(1, len(service.update_calls))
        self.assertEqual(StaffType.PART_TIME, service.update_calls[0]["staff_type"])
        self.assertIn("chef", response.user_types)
        self.assertIn("shopper", response.user_types)
        self.assertEqual("part_time", response.staff_type)

    def test_update_staff_roles_maps_not_found_to_404(self) -> None:
        service = StubStaffService(error=StaffNotFoundError())
        payload = UpdateStaffRequest(user_types=[UserType.CHEF])

        with self.assertRaises(HTTPException) as context:
            update_staff_roles(user_id="missing", payload=payload, _=make_admin(), staff_service=service)

        self.assertEqual(404, context.exception.status_code)

    def test_update_staff_roles_maps_validation_error_to_400(self) -> None:
        service = StubStaffService(error=StaffValidationError("At least one role is required."))
        payload = UpdateStaffRequest(user_types=[UserType.CHEF])

        with self.assertRaises(HTTPException) as context:
            update_staff_roles(user_id="u1", payload=payload, _=make_admin(), staff_service=service)

        self.assertEqual(400, context.exception.status_code)


if __name__ == "__main__":
    unittest.main()
