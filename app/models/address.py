from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UserDeliveryAddress:
    id: str
    user_id: str
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
