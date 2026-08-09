from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import StaffType, UserType
from app.schemas.auth import validate_password_rules


class StaffUserResponse(BaseModel):
    id: str
    name: str
    email: str
    user_types: list[str]
    staff_type: str | None = None
    created_at: datetime


class StaffListResponse(BaseModel):
    items: list[StaffUserResponse]
    total: int
    page: int
    page_size: int


class CreateStaffRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    user_types: list[UserType] = Field(min_length=1)
    staff_type: StaffType | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return str(value).strip()


class UpdateStaffRequest(BaseModel):
    user_types: list[UserType] = Field(min_length=1)
    staff_type: StaffType | None = None


class AcceptStaffInvitationRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_rules(value)
