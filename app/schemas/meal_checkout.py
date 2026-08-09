from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.billing import CheckoutPaymentMethod, CheckoutRoute
from app.models.meal_order import MealDeliveryType


class MealCheckoutQuoteRequest(BaseModel):
    address_id: str | None = Field(default=None, max_length=120)
    delivery_window_id: str | None = Field(default=None, max_length=120)
    delivery_type: MealDeliveryType = MealDeliveryType.STANDARD
    currency: str = Field(min_length=3, max_length=3, default="GBP")

    @field_validator("address_id", "delivery_window_id", mode="before")
    @classmethod
    def normalize_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class MealCheckoutQuoteItemResponse(BaseModel):
    meal_id: str
    meal_name: str
    img_url: str = ""
    servings: int
    unit_price_minor: int
    line_total_minor: int
    pricing_changed: bool
    unavailable: bool


class MealCheckoutPriceAdjustmentResponse(BaseModel):
    meal_id: str
    previous_unit_price_minor: int
    current_unit_price_minor: int


class MealDeliveryWindowResponse(BaseModel):
    id: str
    label: str
    starts_at: datetime
    ends_at: datetime
    is_default: bool = False


class MealCheckoutQuoteResponse(BaseModel):
    quote_id: str
    cart_id: str
    currency: str
    route: CheckoutRoute
    delivery_type: MealDeliveryType
    wallet_available_minor: int
    wallet_contribution_minor: int
    card_contribution_minor: int
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    items: list[MealCheckoutQuoteItemResponse]
    price_adjustments: list[MealCheckoutPriceAdjustmentResponse]
    unavailable_meal_ids: list[str]
    selected_delivery_window: MealDeliveryWindowResponse
    available_delivery_windows: list[MealDeliveryWindowResponse]
    expires_at: datetime
    message: str


class MealCheckoutConfirmRequest(BaseModel):
    quote_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=200)
    payment_method: CheckoutPaymentMethod | None = None

    @field_validator("quote_id", "idempotency_key", mode="before")
    @classmethod
    def normalize_ids(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_payment_method(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None


class MealCheckoutPaymentActionResponse(BaseModel):
    provider: str
    payment_intent_id: str | None = None
    client_secret: str | None = None
    publishable_key: str | None = None


class MealCheckoutConfirmResponse(BaseModel):
    order_id: str
    order_number: str
    status: str
    requires_payment_action: bool
    payment_action: MealCheckoutPaymentActionResponse | None = None
    message: str
