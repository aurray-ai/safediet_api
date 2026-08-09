from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.cart import CartItemPricingState, CartStatus


class MealCartItemUpsertRequest(BaseModel):
    meal_id: str = Field(min_length=1, max_length=120)
    servings: int = Field(ge=1, le=20)

    @field_validator("meal_id", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class MealCartItemQuantityUpdateRequest(BaseModel):
    servings: int = Field(ge=1, le=20)


class MealCartItemResponse(BaseModel):
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


class MealCartSummaryResponse(BaseModel):
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    line_item_count: int


class MealCartResponse(BaseModel):
    id: str
    status: CartStatus
    currency: str
    items: list[MealCartItemResponse]
    selected_address_id: str | None
    summary: MealCartSummaryResponse
    last_priced_at: datetime | None = None
    expires_at: datetime | None = None
    updated_at: datetime


class MealCartSelectAddressRequest(BaseModel):
    address_id: str | None = Field(default=None, max_length=120)

    @field_validator("address_id", mode="before")
    @classmethod
    def normalize_address_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class MealCartValidationIssueResponse(BaseModel):
    meal_id: str
    code: str
    message: str


class MealCartValidateResponse(BaseModel):
    cart: MealCartResponse
    valid: bool
    issues: list[MealCartValidationIssueResponse]
