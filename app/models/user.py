from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class UserType(StrEnum):
    CUSTOMER = "customer"
    CHEF = "chef"
    SHOPPER = "shopper"
    PLATFORM_USER = "platform_user"


class StaffType(StrEnum):
    CONTRACTOR = "contractor"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"


@dataclass(frozen=True, slots=True)
class User:
    id: str
    name: str
    email: str
    password_hash: str
    user_types: list[UserType]
    user_configuration: dict[str, Any]
    created_at: datetime
    staff_type: StaffType | None = None
