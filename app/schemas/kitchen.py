from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.grocery import CountryCode


class KitchenItemUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=120)
    product_name: str = Field(min_length=1, max_length=160)
    quantity: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=40)
    country_code: CountryCode | None = None


class KitchenItemResponse(BaseModel):
    product_id: str
    product_name: str
    quantity_on_hand: float
    quantity_reserved: float
    quantity_available: float
    quantity_consumed: float
    unit: str
    base_unit: str
    country_code: CountryCode | None = None
    source_types: list[str] = Field(default_factory=list)
    updated_at: datetime


class KitchenListResponse(BaseModel):
    items: list[KitchenItemResponse] = Field(default_factory=list)


class KitchenSummaryResponse(BaseModel):
    total_items: int
    available_items: int
    reserved_items: int
    low_stock_items: int
    total_available_quantity: float
    total_reserved_quantity: float
    updated_at: datetime | None = None


class KitchenMovementResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    stock_lot_id: str | None
    movement_type: str
    quantity: float
    unit: str
    reference_type: str | None
    reference_id: str | None
    note: str
    created_at: datetime


class KitchenMovementListResponse(BaseModel):
    items: list[KitchenMovementResponse] = Field(default_factory=list)


class KitchenOrderImportPreviewItemResponse(BaseModel):
    item_id: str
    product_id: str
    product_name: str
    quantity: float
    unit: str
    will_import: bool
    already_imported: bool


class KitchenOrderImportPreviewResponse(BaseModel):
    order_id: str
    order_status: str
    items: list[KitchenOrderImportPreviewItemResponse] = Field(default_factory=list)
    importable_count: int
    already_imported_count: int


class KitchenOrderImportResponse(BaseModel):
    order_id: str
    imported_count: int
    skipped_count: int
    message: str


class SavedPlanKitchenAllocationResponse(BaseModel):
    id: str
    saved_plan_id: str
    effective_date: date | None
    slot: str
    meal_id: str
    product_id: str
    product_name: str
    reserved_quantity: float
    consumed_quantity: float
    unit: str
    status: str
    updated_at: datetime


class SavedPlanKitchenResponse(BaseModel):
    items: list[SavedPlanKitchenAllocationResponse] = Field(default_factory=list)


class SavedPlanKitchenConsumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_date: date | None = None
    slot: str = Field(min_length=1, max_length=80)
    meal_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("slot", mode="before")
    @classmethod
    def normalize_slot(cls, value: str) -> str:
        return str(value).strip().lower()
