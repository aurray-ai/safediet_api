from dataclasses import dataclass
from datetime import datetime

from app.models.cart import CartItemPricingState, CartStatus


@dataclass(frozen=True, slots=True)
class MealCartItem:
    id: str
    meal_id: str
    meal_name: str
    img_url: str
    servings: int
    observed_unit_price_minor: int
    current_unit_price_minor: int
    currency: str
    pricing_state: CartItemPricingState
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MealCartPricingSummary:
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    line_item_count: int


@dataclass(frozen=True, slots=True)
class MealCart:
    id: str
    user_id: str
    currency: str
    status: CartStatus
    items: list[MealCartItem]
    selected_address_id: str | None
    pricing_snapshot: dict[str, object]
    last_priced_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
