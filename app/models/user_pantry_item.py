from dataclasses import dataclass
from datetime import datetime

from app.models.grocery import CountryCode


@dataclass(frozen=True, slots=True)
class UserPantryItem:
    id: str
    user_id: str
    product_id: str
    product_name: str
    quantity: float
    unit: str
    country_code: CountryCode | None
    created_at: datetime
    updated_at: datetime
