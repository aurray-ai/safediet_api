from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class MealOrderItemResponse(BaseModel):
    id: str
    meal_id: str
    meal_name: str
    img_url: str
    servings: int
    unit_price_minor: int
    line_total_minor: int
    currency: str
    delivery_date: date | None = None
    slot: str = ""
    estimated_status: str = "upcoming"


class MealOrderPricingSummaryResponse(BaseModel):
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int


class MealOrderPaymentSummaryResponse(BaseModel):
    currency: str
    wallet_amount_minor: int
    card_amount_minor: int
    total_paid_minor: int
    provider: str | None
    provider_payment_intent_id: str | None


class MealOrderStatusHistoryResponse(BaseModel):
    status: str
    note: str
    actor_user_id: str | None
    created_at: datetime


class MealOrderResponse(BaseModel):
    id: str
    order_number: str
    user_id: str
    status: str
    currency: str
    delivery_type: str
    items: list[MealOrderItemResponse]
    pricing_summary: MealOrderPricingSummaryResponse
    address_snapshot: dict[str, object]
    payment_summary: MealOrderPaymentSummaryResponse
    cancellation_window_expires_at: datetime | None
    status_history: list[MealOrderStatusHistoryResponse]
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class MealOrderListResponse(BaseModel):
    items: list[MealOrderResponse]
    next_cursor: str | None = None


class MealOrderCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return str(value).strip()


class MealOrderCancelResponse(BaseModel):
    order: MealOrderResponse
    message: str
