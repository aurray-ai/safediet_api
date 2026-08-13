from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class AssignmentHistoryEntryResponse(BaseModel):
    action: str
    worker_id: str | None
    actor_user_id: str | None
    note: str
    created_at: datetime


class AssignWorkerRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=300)

    @field_validator("worker_id", "note", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class FulfillmentStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=300)

    @field_validator("status", "note", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class DeclineRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=300)

    @field_validator("reason_code", "note", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return str(value).strip()


class WorkerSummaryResponse(BaseModel):
    id: str
    name: str
    email: str


class WorkerListResponse(BaseModel):
    items: list[WorkerSummaryResponse]
    total: int


class WorkerRosterEntryResponse(BaseModel):
    id: str
    name: str
    email: str
    active_count: int
    completed_this_week: int


class WorkerRosterListResponse(BaseModel):
    items: list[WorkerRosterEntryResponse]
    total: int


class TrackOverviewResponse(BaseModel):
    unassigned: int
    in_progress: int
    completed_this_week: int


class FulfillmentOverviewResponse(BaseModel):
    chef: TrackOverviewResponse
    shopper: TrackOverviewResponse


# --- Chef track (MealOrder) ---


class MealOrderFulfillmentItemResponse(BaseModel):
    id: str
    meal_id: str
    meal_name: str
    img_url: str
    servings: int
    unit_price_minor: int
    line_total_minor: int
    currency: str
    delivery_date: date | None
    slot: str


class MealOrderFulfillmentResponse(BaseModel):
    id: str
    order_number: str
    user_id: str
    status: str
    currency: str
    items: list[MealOrderFulfillmentItemResponse]
    total_minor: int
    fulfillment_status: str
    assigned_worker_id: str | None
    assigned_by: str | None
    assigned_at: datetime | None
    assignment_history: list[AssignmentHistoryEntryResponse]
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class MealOrderFulfillmentListResponse(BaseModel):
    items: list[MealOrderFulfillmentResponse]
    next_cursor: str | None = None


# --- Shopper track (grocery Order) ---


class GroceryOrderFulfillmentItemResponse(BaseModel):
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
    currency: str
    allow_substitutions: bool
    substitution_resolution: str
    substituted_product_id: str | None
    source_meal_id: str | None


class GroceryOrderFulfillmentResponse(BaseModel):
    id: str
    order_number: str
    user_id: str
    status: str
    currency: str
    items: list[GroceryOrderFulfillmentItemResponse]
    total_minor: int
    fulfillment_status: str
    assigned_worker_id: str | None
    assigned_by: str | None
    assigned_at: datetime | None
    assignment_history: list[AssignmentHistoryEntryResponse]
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class GroceryOrderFulfillmentListResponse(BaseModel):
    items: list[GroceryOrderFulfillmentResponse]
    next_cursor: str | None = None
