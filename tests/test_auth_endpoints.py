from __future__ import annotations

from datetime import datetime, timezone
import unittest

from fastapi import HTTPException

from app.api.v1.endpoints.auth import accept_staff_invitation, get_me, update_user_configuration
from app.models.user import User, UserType
from app.schemas.auth import UpdateUserConfigurationRequest
from app.schemas.staff import AcceptStaffInvitationRequest
from app.services.auth_service import AuthResult
from app.services.staff_service import StaffInvitationInvalidError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_user_configuration() -> dict[str, object]:
    return {
        "mode": "solo",
        "goal": "Weight Loss",
        "weekly_budget": 75,
        "weekly_style": "Balanced",
        "low_budget_mode": False,
        "prioritize_savings": True,
        "fasting_pattern": "16:8",
        "culture_preferences": ["Nigerian"],
        "custom_culture_note": "",
        "diet_rules": ["Halal"],
        "protein_preference": "Fish",
        "household_size": 1,
        "selected_plan_types": ["Breakfast", "Dinner"],
        "allergies": ["Peanuts"],
        "gender": "Female",
        "age": 31,
        "height_cm": 168.0,
        "weight_kg": 69.5,
        "measurement_system": "metric",
        "weekday_cooking_time": "Around 30 min",
        "weekend_cooking_time": "Around 45 min",
        "cooking_confidence": "Moderate",
        "activity_source": "Manual",
        "shopping_frequency": "Weekly",
        "pantry_confidence": "Moderate",
        "waste_frequency": "Sometimes",
        "staples_habit": "Partly stocked",
        "plan_reminder_time": {
            "breakfast": "07:00",
            "lunch": "13:00",
            "dinner": "19:00",
            "snack": "16:00",
        },
    }


def make_user(configuration: dict[str, object] | None = None) -> User:
    return User(
        id="user-1",
        name="Ada",
        email="ada@example.com",
        password_hash="hashed",
        user_types=[UserType.CUSTOMER],
        user_configuration=dict(configuration or make_user_configuration()),
        created_at=utc_now(),
    )


class StubAuthService:
    def __init__(self) -> None:
        self.update_calls: list[dict[str, object]] = []

    def update_user_configuration(self, *, current_user: User, user_configuration: dict[str, object]) -> User:
        self.update_calls.append(
            {
                "current_user_id": current_user.id,
                "user_configuration": dict(user_configuration),
            }
        )
        return make_user(configuration=user_configuration)


class StubStaffService:
    def __init__(self, *, result: AuthResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.accept_calls: list[dict[str, object]] = []

    def accept_invitation(self, *, token: str, password: str) -> AuthResult:
        self.accept_calls.append({"token": token, "password": password})
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class AuthEndpointTests(unittest.TestCase):
    def test_accept_staff_invitation_returns_auth_response(self) -> None:
        user = make_user()
        staff_service = StubStaffService(
            result=AuthResult(access_token="token-123", token_type="bearer", user=user)
        )
        payload = AcceptStaffInvitationRequest(password="Str0ngPassw0rd!")

        response = accept_staff_invitation(token="raw-token", payload=payload, staff_service=staff_service)

        self.assertEqual(1, len(staff_service.accept_calls))
        self.assertEqual("raw-token", staff_service.accept_calls[0]["token"])
        self.assertEqual("token-123", response.access_token)
        self.assertEqual("user-1", response.user.id)

    def test_accept_staff_invitation_maps_invalid_token_to_400(self) -> None:
        staff_service = StubStaffService(error=StaffInvitationInvalidError())
        payload = AcceptStaffInvitationRequest(password="Str0ngPassw0rd!")

        with self.assertRaises(HTTPException) as context:
            accept_staff_invitation(token="bad-token", payload=payload, staff_service=staff_service)

        self.assertEqual(400, context.exception.status_code)


    def test_get_me_returns_current_user_payload(self) -> None:
        user = make_user()

        response = get_me(current_user=user)

        self.assertEqual("user-1", response.id)
        self.assertEqual("Ada", response.name)
        self.assertEqual("Weight Loss", response.user_configuration.goal)
        self.assertEqual("07:00", response.user_configuration.plan_reminder_time.breakfast)

    def test_update_user_configuration_merges_existing_nested_values(self) -> None:
        current_user = make_user()
        auth_service = StubAuthService()
        payload = UpdateUserConfigurationRequest.model_validate(
            {
                "user_configuration": {
                    "weekly_budget": 90,
                    "plan_reminder_time": {
                        "breakfast": "08:30",
                        "snack": "",
                    },
                    "low_budget_mode": True,
                }
            }
        )

        response = update_user_configuration(
            payload=payload,
            current_user=current_user,
            auth_service=auth_service,
        )

        self.assertEqual(1, len(auth_service.update_calls))
        merged = auth_service.update_calls[0]["user_configuration"]
        self.assertEqual(90, merged["weekly_budget"])
        self.assertEqual(True, merged["low_budget_mode"])
        self.assertEqual("Balanced", merged["weekly_style"])
        self.assertEqual(
            {
                "breakfast": "08:30",
                "lunch": "13:00",
                "dinner": "19:00",
            },
            merged["plan_reminder_time"],
        )
        self.assertEqual("Weight Loss", response.user_configuration.goal)
        self.assertEqual(90, response.user_configuration.weekly_budget)
        self.assertEqual("08:30", response.user_configuration.plan_reminder_time.breakfast)
        self.assertIsNone(response.user_configuration.plan_reminder_time.snack)


if __name__ == "__main__":
    unittest.main()
