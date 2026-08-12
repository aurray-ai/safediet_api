from datetime import datetime

from pydantic import BaseModel, Field


class DiscountResponse(BaseModel):
    id: str
    label: str
    percent: float
    product_count: int
    created_at: datetime
    updated_at: datetime


class DiscountListResponse(BaseModel):
    items: list[DiscountResponse]


class CreateDiscountRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    percent: float = Field(gt=0, lt=100)


class UpdateDiscountRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    percent: float = Field(gt=0, lt=100)


class DiscountProductSummaryResponse(BaseModel):
    id: str
    product: str
    img_url: str
    category_id: str


class DiscountProductListResponse(BaseModel):
    items: list[DiscountProductSummaryResponse]
    total: int
    page: int
    page_size: int


class AssignProductsToDiscountRequest(BaseModel):
    product_ids: list[str] = Field(min_length=1)


class UnassignProductsFromDiscountRequest(BaseModel):
    product_ids: list[str] = Field(min_length=1)


class DiscountAuditEntryResponse(BaseModel):
    action: str
    details: dict
    actor_user_id: str
    actor_name: str
    created_at: datetime


class DiscountAuditListResponse(BaseModel):
    items: list[DiscountAuditEntryResponse]
