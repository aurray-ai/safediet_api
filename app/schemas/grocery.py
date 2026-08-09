from datetime import datetime

from pydantic import BaseModel, Field

from app.models.grocery import CountryCode, CultureTag, CurrencyCode, NutrientType, NutrientUnit


class GroceryCategoryResponse(BaseModel):
    id: str
    slug: str
    name: str
    icon_name: str
    img_url: str
    description: str
    sort_order: int


class ResolvedPriceResponse(BaseModel):
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float
    price_unit: str
    member_amount: float | None = None
    discount_percent: float | None = None


class CountryPriceResponse(ResolvedPriceResponse):
    source: str
    updated_at: datetime
    is_active: bool
    region: str | None = None
    city: str | None = None


class NutritionSpecResponse(BaseModel):
    nutrient_id: NutrientType
    amount: float
    unit: NutrientUnit


class GroceryProductListItemResponse(BaseModel):
    id: str
    category_id: str
    img_url: str
    product: str
    sort_order: int
    product_tags: list[str]
    culture_tags: list[CultureTag]
    nutritional_specs: list[NutritionSpecResponse]
    resolved_price: ResolvedPriceResponse | None = None


class GroceryProductDetailResponse(BaseModel):
    id: str
    category_id: str
    img_url: str
    product: str
    sort_order: int
    product_tags: list[str]
    culture_tags: list[CultureTag]
    nutritional_specs: list[NutritionSpecResponse]
    prices: list[CountryPriceResponse]
    description: str


class GroceryProductListResponse(BaseModel):
    items: list[GroceryProductListItemResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class CultureMetadataResponse(BaseModel):
    value: CultureTag
    display_name: str


class NutrientMetadataResponse(BaseModel):
    id: NutrientType
    slug: str
    display_name: str
    default_unit: NutrientUnit
