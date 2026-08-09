from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class CartStatus(StrEnum):
    ACTIVE = "active"
    CHECKOUT_PENDING = "checkout_pending"
    CONVERTED = "converted"
    EXPIRED = "expired"


class CartItemPricingState(StrEnum):
    CURRENT = "current"
    PRICE_CHANGED = "price_changed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CartItem:
    id: str
    product_id: str
    category_id: str
    product_name: str
    img_url: str
    quantity: int
    unit_label: str
    unit_weight_grams: int
    observed_unit_price_minor: int
    current_unit_price_minor: int
    currency: str
    allow_substitutions: bool
    substitution_note: str
    pricing_state: CartItemPricingState
    created_at: datetime
    updated_at: datetime
    source_saved_plan_id: str | None = None
    source_meal_ids: list[str] = field(default_factory=list)
    base_price_minor: int = 0
    discount_percent_applied: float = 0.0


@dataclass(frozen=True, slots=True)
class CartPricingSummary:
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    total_weight_grams: int
    line_item_count: int


@dataclass(frozen=True, slots=True)
class Cart:
    id: str
    user_id: str
    store_id: str
    currency: str
    status: CartStatus
    items: list[CartItem]
    selected_address_id: str | None
    pricing_snapshot: dict[str, object]
    last_priced_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
