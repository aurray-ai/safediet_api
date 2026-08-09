from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.billing import CheckoutPaymentMethod, CheckoutRoute
from app.schemas.meal_checkout import MealCheckoutPaymentActionResponse


class MealPlanCheckoutQuoteRequest(BaseModel):
    address_id: str = Field(min_length=1, max_length=120)
    effective_date: date
    view: Literal["day", "week"] = "week"
    currency: str = Field(min_length=3, max_length=3, default="GBP")

    @field_validator("address_id", mode="before")
    @classmethod
    def normalize_address_id(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class MealPlanCheckoutQuoteItemResponse(BaseModel):
    meal_id: str
    meal_name: str
    img_url: str = ""
    servings: int
    unit_price_minor: int
    line_total_minor: int
    delivery_date: date
    slot: str
    unavailable: bool = False


class MealPlanCheckoutQuoteResponse(BaseModel):
    quote_id: str
    plan_id: str
    currency: str
    route: CheckoutRoute
    wallet_available_minor: int
    wallet_contribution_minor: int
    card_contribution_minor: int
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    items: list[MealPlanCheckoutQuoteItemResponse]
    unavailable_meal_ids: list[str]
    delivery_days: list[date]
    expires_at: datetime
    message: str


class MealPlanCheckoutConfirmRequest(BaseModel):
    quote_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=200)
    payment_method: CheckoutPaymentMethod | None = None

    @field_validator("quote_id", "idempotency_key", mode="before")
    @classmethod
    def normalize_ids(cls, value: str) -> str:
        return str(value).strip()


class MealPlanCheckoutConfirmResponse(BaseModel):
    order_id: str
    order_number: str
    status: str
    requires_payment_action: bool
    payment_action: MealCheckoutPaymentActionResponse | None = None
    message: str
