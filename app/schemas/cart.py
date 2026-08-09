from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.cart import CartItemPricingState, CartStatus


class CartItemUpsertRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=25)
    allow_substitutions: bool = True
    substitution_note: str = Field(default="", max_length=300)

    @field_validator("product_id", "substitution_note", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class CartItemQuantityUpdateRequest(BaseModel):
    quantity: int = Field(ge=1, le=25)


class CartItemResponse(BaseModel):
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
    base_price_minor: int = 0
    discount_percent_applied: float = 0.0
    currency: str
    allow_substitutions: bool
    substitution_note: str
    pricing_state: CartItemPricingState
    created_at: datetime
    updated_at: datetime
    source_saved_plan_id: str | None = None
    source_meal_ids: list[str] = []


class CartSummaryResponse(BaseModel):
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    total_weight_grams: int
    line_item_count: int
    free_delivery_threshold_minor: int = 0
    free_delivery_remaining_minor: int = 0
    free_delivery_unlocked: bool = False


class CartResponse(BaseModel):
    id: str
    status: CartStatus
    currency: str
    store_id: str
    items: list[CartItemResponse]
    selected_address_id: str | None
    summary: CartSummaryResponse
    last_priced_at: datetime | None = None
    expires_at: datetime | None = None
    updated_at: datetime


class CartSelectAddressRequest(BaseModel):
    address_id: str | None = Field(default=None, max_length=120)

    @field_validator("address_id", mode="before")
    @classmethod
    def normalize_address_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class CartValidationIssueResponse(BaseModel):
    product_id: str
    code: str
    message: str


class CartValidateResponse(BaseModel):
    cart: CartResponse
    valid: bool
    issues: list[CartValidationIssueResponse]


class CartSkippedPlanItemResponse(BaseModel):
    product_id: str
    reason: str


class CartAddPlanItemsResponse(BaseModel):
    cart: CartResponse
    skipped_items: list[CartSkippedPlanItemResponse]
