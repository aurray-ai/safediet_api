from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.inventory import InventoryAdjustmentType


class AdminInventoryItemUpsertRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=120)
    is_active: bool = True
    available_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0, default=0)
    unit_label: str = Field(min_length=1, max_length=80)
    unit_weight_grams: int = Field(ge=1, le=500_000)
    max_per_order: int = Field(ge=1, le=500, default=25)
    allow_substitutions: bool = True
    substitution_group: str | None = Field(default=None, max_length=120)

    @field_validator("sku", "unit_label", "substitution_group", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class AdminInventoryItemResponse(BaseModel):
    id: str
    store_id: str
    product_id: str
    product_name: str | None = None
    category_id: str | None = None
    img_url: str | None = None
    sku: str
    is_active: bool
    available_quantity: int
    reserved_quantity: int
    unit_label: str
    unit_weight_grams: int
    max_per_order: int
    allow_substitutions: bool
    substitution_group: str | None
    created_at: datetime
    updated_at: datetime


class AdminInventoryListResponse(BaseModel):
    items: list[AdminInventoryItemResponse]
    total: int
    page: int
    page_size: int


class AdminInventoryAdjustmentRequest(BaseModel):
    adjustment_type: InventoryAdjustmentType
    quantity: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)
    reference_type: str | None = Field(default=None, max_length=120)
    reference_id: str | None = Field(default=None, max_length=120)
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("reason", "reference_type", "reference_id", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class AdminInventoryAdjustmentResponse(BaseModel):
    id: str
    inventory_item_id: str
    product_id: str
    store_id: str
    adjustment_type: InventoryAdjustmentType
    delta_quantity: int
    reason: str
    actor_user_id: str | None
    reference_type: str | None
    reference_id: str | None
    metadata: dict[str, object]
    created_at: datetime


class AdminInventoryAdjustmentListResponse(BaseModel):
    items: list[AdminInventoryAdjustmentResponse]
    total: int
    page: int
    page_size: int


class DeliveryFeeRuleCreateRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    min_weight_grams: int = Field(ge=0)
    max_weight_grams: int = Field(ge=1)
    fee_minor: int = Field(ge=0)
    is_active: bool = True

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()

    @model_validator(mode="after")
    def validate_weight_range(self) -> "DeliveryFeeRuleCreateRequest":
        if self.max_weight_grams <= self.min_weight_grams:
            raise ValueError("max_weight_grams must be greater than min_weight_grams.")
        return self


class DeliveryFeeRuleUpdateRequest(DeliveryFeeRuleCreateRequest):
    pass


class DeliveryFeeRuleResponse(BaseModel):
    id: str
    store_id: str
    currency: str
    min_weight_grams: int
    max_weight_grams: int
    fee_minor: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DeliveryFeeRuleListResponse(BaseModel):
    items: list[DeliveryFeeRuleResponse]
