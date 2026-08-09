from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.grocery import CountryCode


class UserPantryItemUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=120)
    product_name: str = Field(min_length=1, max_length=160)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    country_code: CountryCode | None = None


class UserPantryItemResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    quantity: float
    unit: str
    country_code: CountryCode | None = None
    created_at: datetime
    updated_at: datetime


class UserPantryListResponse(BaseModel):
    items: list[UserPantryItemResponse] = Field(default_factory=list)
