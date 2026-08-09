from __future__ import annotations

from datetime import datetime, timezone
import unittest

from fastapi import HTTPException

from app.api.v1.endpoints.households import create_household
from app.models.user import User, UserType
from app.schemas.household import CreateHouseholdRequest
from app.services.household_service import HouseholdConflictError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_user() -> User:
    return User(
        id="user-1",
        name="Sarah",
        email="sarah@example.com",
        password_hash="hash",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


class StubHouseholdService:
    def create_household(self, **_: object) -> object:
        raise HouseholdConflictError("User already belongs to an active household.")


class HouseholdEndpointTests(unittest.TestCase):
    def test_create_household_maps_conflict_error_to_http_409(self) -> None:
        payload = CreateHouseholdRequest.model_validate(
            {
                "name": "Our Kitchen",
                "currency": "GBP",
                "budget_profile": {
                    "period": "weekly",
                    "target_amount_minor": 12000,
                },
                "default_split_rule": {
                    "type": "equal",
                    "weights": [],
                },
            }
        )

        with self.assertRaises(HTTPException) as context:
            create_household(
                payload=payload,
                current_user=make_user(),
                household_service=StubHouseholdService(),  # type: ignore[arg-type]
            )

        self.assertEqual(409, context.exception.status_code)
        self.assertEqual("User already belongs to an active household.", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
