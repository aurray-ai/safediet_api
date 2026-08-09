from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PushPlatform(StrEnum):
    IOS = "ios"


class PushEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class PushDevice:
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
