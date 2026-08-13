from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OrderItemResponse(BaseModel):
    id: str
    product_id: str
    category_id: str
    product_name: str
    img_url: str
    quantity: int
    unit_label: str
    unit_weight_grams: int
    unit_price_minor: int
    line_total_minor: int
    base_price_minor: int = 0
    discount_percent_applied: float = 0.0
    currency: str
    allow_substitutions: bool
    substitution_resolution: str
    substituted_product_id: str | None


class OrderPricingSummaryResponse(BaseModel):
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    total_weight_grams: int


class OrderPaymentSummaryResponse(BaseModel):
    currency: str
    wallet_amount_minor: int
    card_amount_minor: int
    total_paid_minor: int
    provider: str | None
    provider_payment_intent_id: str | None


class OrderStatusHistoryResponse(BaseModel):
    status: str
    note: str
    actor_user_id: str | None
    created_at: datetime


class OrderFulfillmentAssignmentHistoryResponse(BaseModel):
    action: str
    worker_id: str | None
    actor_user_id: str | None
    note: str
    created_at: datetime


class OrderResponse(BaseModel):
    id: str
    order_number: str
    user_id: str
    store_id: str
    status: str
    currency: str
    items: list[OrderItemResponse]
    pricing_summary: OrderPricingSummaryResponse
    address_snapshot: dict[str, object]
    substitution_policy: dict[str, object]
    payment_summary: OrderPaymentSummaryResponse
    cancellation_window_expires_at: datetime | None
    status_history: list[OrderStatusHistoryResponse]
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    fulfillment_status: str = "unassigned"
    assigned_worker_id: str | None = None
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    assignment_history: list[OrderFulfillmentAssignmentHistoryResponse] = []


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int = 0
    page: int = 1
    page_size: int = 20
    next_cursor: str | None = None


class OrderCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return str(value).strip()


class OrderCancelResponse(BaseModel):
    order: OrderResponse
    message: str


class RefundLineItemRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1)


class RefundCreateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    amount_minor: int | None = Field(default=None, ge=0)
    line_items: list[RefundLineItemRequest] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=200)

    @field_validator("reason", "idempotency_key", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class RefundResponse(BaseModel):
    id: str
    order_id: str
    user_id: str
    status: str
    currency: str
    refund_type: str
    reason: str
    wallet_refund_minor: int
    card_refund_minor: int
    line_items: list[dict[str, object]]
    provider: str | None
    provider_refund_id: str | None
    idempotency_key: str
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class RefundListResponse(BaseModel):
    items: list[RefundResponse]


class AdminOrderStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=200)

    @field_validator("status", "note", mode="before")
    @classmethod
    def normalize_status_fields(cls, value: str) -> str:
        return str(value).strip()


class AdminOrderSubstitutionRequest(BaseModel):
    replacement_product_id: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=200)

    @field_validator("replacement_product_id", "note", mode="before")
    @classmethod
    def normalize_substitution_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
