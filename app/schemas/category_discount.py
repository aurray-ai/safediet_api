from datetime import datetime

from pydantic import BaseModel, Field


class CategoryDiscountResponse(BaseModel):
    category_id: str
    category_name: str
    discount_percent: float | None
    updated_at: datetime


class CategoryDiscountListResponse(BaseModel):
    items: list[CategoryDiscountResponse]


class SetCategoryDiscountRequest(BaseModel):
    discount_percent: float = Field(gt=0, lt=100)


class CategoryDiscountAuditEntryResponse(BaseModel):
    action: str
    previous_percent: float | None
    new_percent: float | None
    actor_user_id: str
    created_at: datetime


class CategoryDiscountAuditListResponse(BaseModel):
    items: list[CategoryDiscountAuditEntryResponse]
