from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class UserDeliveryAddressCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    recipient_name: str = Field(min_length=1, max_length=160)
    phone_number: str = Field(min_length=5, max_length=40)
    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default="", max_length=200)
    city: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=120)
    postal_code: str = Field(min_length=1, max_length=40)
    country: str = Field(min_length=1, default="United Kingdom")
    delivery_notes: str = Field(default="", max_length=500)
    is_default: bool = False

    @field_validator(
        "label",
        "recipient_name",
        "phone_number",
        "line1",
        "line2",
        "city",
        "state",
        "postal_code",
        "country",
        "delivery_notes",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class UserDeliveryAddressUpdateRequest(UserDeliveryAddressCreateRequest):
    pass


class UserDeliveryAddressResponse(BaseModel):
    id: str
    label: str
    recipient_name: str
    phone_number: str
    line1: str
    line2: str
    city: str
    state: str
    postal_code: str
    country: str
    delivery_notes: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class UserDeliveryAddressListResponse(BaseModel):
    items: list[UserDeliveryAddressResponse]


class SelectDefaultAddressRequest(BaseModel):
    address_id: str = Field(min_length=1, max_length=120)
