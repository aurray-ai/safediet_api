from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.user import User, UserType
from app.services.auth_service import AuthResult


def validate_password_rules(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not any(character.islower() for character in password):
        raise ValueError("Password must include at least one lowercase letter.")
    if not any(character.isupper() for character in password):
        raise ValueError("Password must include at least one uppercase letter.")
    if not any(character.isdigit() for character in password):
        raise ValueError("Password must include at least one digit.")
    return password


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str
    user_types: list[UserType] = Field(default_factory=lambda: [UserType.CUSTOMER])
    user_configuration: "UserConfigurationPayload"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required.")
        return normalized

    @field_validator("user_types")
    @classmethod
    def validate_user_types(cls, value: list[UserType]) -> list[UserType]:
        if not value:
            raise ValueError("At least one user type is required.")
        deduplicated = list(dict.fromkeys(value))
        if UserType.CUSTOMER not in deduplicated:
            raise ValueError("Customer onboarding must include the customer user type.")
        return deduplicated

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_rules(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value:
            raise ValueError("Password is required.")
        return value


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_rules(value)


class AuthMessageResponse(BaseModel):
    message: str


class UserConfigurationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str
    goal: str
    weekly_budget: int = Field(ge=0)
    weekly_style: str | None = None
    low_budget_mode: bool = False
    prioritize_savings: bool = False
    fasting_pattern: str | None = None
    culture_preferences: list[str] = Field(default_factory=list)
    custom_culture_note: str = ""
    diet_rules: list[str] = Field(default_factory=list)
    protein_preference: str | None = None
    household_size: int = Field(ge=1)
    selected_plan_types: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    gender: str | None = None
    age: int | None = Field(default=None, ge=13, le=120)
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    measurement_system: str | None = None
    weekday_cooking_time: str | None = None
    weekend_cooking_time: str | None = None
    cooking_confidence: str | None = None
    activity_source: str | None = None
    shopping_frequency: str | None = None
    pantry_confidence: str | None = None
    waste_frequency: str | None = None
    staples_habit: str | None = None
    timezone: str | None = None
    plan_reminder_time: "PlanReminderTimePayload" = Field(default_factory=lambda: PlanReminderTimePayload())

    @model_validator(mode="after")
    def ensure_customer_configuration(self) -> "UserConfigurationPayload":
        if self.mode not in {"solo", "household"}:
            raise ValueError("Unsupported user mode.")
        if not self.selected_plan_types:
            raise ValueError("At least one plan type must be selected.")
        return self

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PlanReminderTimePayload(BaseModel):
    breakfast: str = "07:00"
    lunch: str = "13:00"
    dinner: str = "19:00"
    snack: str | None = None

    @field_validator("breakfast", "lunch", "dinner", "snack")
    @classmethod
    def validate_time_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parts = normalized.split(":")
        if len(parts) != 2:
            raise ValueError("Reminder times must use HH:MM format.")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("Reminder times must use HH:MM format.") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Reminder times must use a valid 24-hour time.")
        return f"{hour:02d}:{minute:02d}"


class UpdateUserConfigurationRequest(BaseModel):
    user_configuration: "PartialUserConfigurationPayload"


class PartialPlanReminderTimePayload(BaseModel):
    breakfast: str | None = None
    lunch: str | None = None
    dinner: str | None = None
    snack: str | None = None

    @field_validator("breakfast", "lunch", "dinner", "snack")
    @classmethod
    def validate_partial_time_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return ""
        parts = normalized.split(":")
        if len(parts) != 2:
            raise ValueError("Reminder times must use HH:MM format.")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("Reminder times must use HH:MM format.") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Reminder times must use a valid 24-hour time.")
        return f"{hour:02d}:{minute:02d}"


class PartialUserConfigurationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str | None = None
    goal: str | None = None
    weekly_budget: int | None = Field(default=None, ge=0)
    weekly_style: str | None = None
    low_budget_mode: bool | None = None
    prioritize_savings: bool | None = None
    fasting_pattern: str | None = None
    culture_preferences: list[str] | None = None
    custom_culture_note: str | None = None
    diet_rules: list[str] | None = None
    protein_preference: str | None = None
    household_size: int | None = Field(default=None, ge=1)
    selected_plan_types: list[str] | None = None
    allergies: list[str] | None = None
    gender: str | None = None
    age: int | None = Field(default=None, ge=13, le=120)
    height_cm: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    measurement_system: str | None = None
    weekday_cooking_time: str | None = None
    weekend_cooking_time: str | None = None
    cooking_confidence: str | None = None
    activity_source: str | None = None
    shopping_frequency: str | None = None
    pantry_confidence: str | None = None
    waste_frequency: str | None = None
    staples_habit: str | None = None
    timezone: str | None = None
    plan_reminder_time: PartialPlanReminderTimePayload | None = None

    def to_document(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=True)
        if self.plan_reminder_time is not None:
            payload["plan_reminder_time"] = self.plan_reminder_time.model_dump(
                mode="json",
                exclude_none=True,
            )
        return payload


class UserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    user_types: list[UserType]
    user_configuration: UserConfigurationPayload | None = None
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            user_types=user.user_types,
            user_configuration=(
                UserConfigurationPayload.model_validate(user.user_configuration)
                if user.user_configuration
                else None
            ),
            created_at=user.created_at,
        )


class AuthResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

    @classmethod
    def from_result(cls, result: AuthResult) -> "AuthResponse":
        return cls(
            access_token=result.access_token,
            token_type=result.token_type,
            user=UserResponse.from_user(result.user),
        )


RegisterRequest.model_rebuild()
UserConfigurationPayload.model_rebuild()
UpdateUserConfigurationRequest.model_rebuild()
PartialUserConfigurationPayload.model_rebuild()
