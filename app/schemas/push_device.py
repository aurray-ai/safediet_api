from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.push_device import PushDevice, PushEnvironment, PushPlatform


class RegisterPushDeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: PushPlatform = PushPlatform.IOS
    device_token: str = Field(min_length=32, max_length=512)
    environment: PushEnvironment = PushEnvironment.SANDBOX
    locations: list[str] = Field(default_factory=list)
    delivery_types: list[str] = Field(default_factory=list)
    app_version: str | None = Field(default=None, max_length=40)
    build_number: str | None = Field(default=None, max_length=40)
    device_name: str | None = Field(default=None, max_length=120)

    @field_validator("device_token")
    @classmethod
    def normalize_device_token(cls, value: str) -> str:
        normalized = value.replace(" ", "").strip()
        if not normalized:
            raise ValueError("Device token is required.")
        return normalized

    @field_validator("locations", "delivery_types")
    @classmethod
    def normalize_string_lists(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class UnregisterPushDeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: PushPlatform = PushPlatform.IOS
    device_token: str = Field(min_length=32, max_length=512)

    @field_validator("device_token")
    @classmethod
    def normalize_device_token(cls, value: str) -> str:
        normalized = value.replace(" ", "").strip()
        if not normalized:
            raise ValueError("Device token is required.")
        return normalized


class PushDeviceResponse(BaseModel):
    id: str
    user_id: str
    platform: PushPlatform
    device_token: str
    environment: PushEnvironment
    locations: list[str]
    delivery_types: list[str]
    app_version: str | None
    build_number: str | None
    device_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, device: PushDevice) -> "PushDeviceResponse":
        return cls(
            id=device.id,
            user_id=device.user_id,
            platform=device.platform,
            device_token=device.device_token,
            environment=device.environment,
            locations=device.locations,
            delivery_types=device.delivery_types,
            app_version=device.app_version,
            build_number=device.build_number,
            device_name=device.device_name,
            is_active=device.is_active,
            created_at=device.created_at,
            updated_at=device.updated_at,
        )


class UnregisterPushDeviceResponse(BaseModel):
    success: bool = True
