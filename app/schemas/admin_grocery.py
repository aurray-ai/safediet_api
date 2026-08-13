from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.grocery import CountryCode, CultureTag, CurrencyCode, NutrientType, NutrientUnit
from app.schemas.grocery import GroceryCategoryResponse


class AdminNutritionSpecPayload(BaseModel):
    nutrient_id: NutrientType
    amount: float = Field(gt=0)
    unit: NutrientUnit


class AdminCountryPricePayload(BaseModel):
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float = Field(gt=0)
    price_unit: str = Field(min_length=1, max_length=80)
    source: str = Field(default="admin_dashboard", min_length=1, max_length=80)
    is_active: bool = True
    region: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)

    @field_validator("price_unit", "source", "region", "city", mode="before")
    @classmethod
    def normalize_string_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AdminCountryPriceSummary(BaseModel):
    currency_code: CurrencyCode
    amount: float = Field(gt=0)
    price_unit: str = Field(min_length=1, max_length=80)


class AdminGroceryProductPayload(BaseModel):
    category_id: str = Field(min_length=1, max_length=120)
    img_url: str = Field(default="", max_length=500)
    product: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    sort_order: int = Field(default=0, ge=0)
    product_tags: list[str] = Field(default_factory=list)
    culture_tags: list[CultureTag] = Field(default_factory=list)
    nutritional_specs: list[AdminNutritionSpecPayload] = Field(default_factory=list)
    prices: list[AdminCountryPricePayload] = Field(default_factory=list)
    is_active: bool = True

    @field_validator("category_id", "img_url", "product", "description", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("product_tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized = []
        for tag in value:
            cleaned = tag.strip().lower()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @field_validator("culture_tags")
    @classmethod
    def deduplicate_cultures(cls, value: list[CultureTag]) -> list[CultureTag]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_nested_uniqueness(self) -> "AdminGroceryProductPayload":
        if not self.img_url.strip():
            raise ValueError("Each product must include an image.")

        nutrient_ids = [spec.nutrient_id for spec in self.nutritional_specs]
        if len(set(nutrient_ids)) != len(nutrient_ids):
            raise ValueError("Each nutrient can only be added once per product.")

        country_codes = [price.country_code for price in self.prices]
        if len(set(country_codes)) != len(country_codes):
            raise ValueError("Each country can only have one price entry per product.")

        if not any(price.amount > 0 for price in self.prices):
            raise ValueError("Each product must include at least one price entry.")

        return self

    def to_document(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class AdminGroceryProductCreateRequest(AdminGroceryProductPayload):
    product_id: str | None = Field(default=None, max_length=120)

    @field_validator("product_id", mode="before")
    @classmethod
    def normalize_product_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "_")
        return normalized or None


class AdminGroceryProductResponse(BaseModel):
    id: str
    category_id: str
    img_url: str = Field(default="", max_length=500)
    product: str
    description: str
    sort_order: int
    product_tags: list[str]
    culture_tags: list[CultureTag]
    nutritional_specs: list[AdminNutritionSpecPayload]
    prices: list[AdminCountryPricePayload]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminGroceryProductListItemResponse(BaseModel):
    id: str
    category_id: str
    category_name: str
    img_url: str = Field(default="", max_length=500)
    product: str
    price: AdminCountryPriceSummary | None = None
    is_active: bool


class AdminGroceryProductListResponse(BaseModel):
    items: list[AdminGroceryProductListItemResponse]
    total: int
    page: int
    page_size: int


class AdminGroceryBulkDeleteRequest(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("product_ids", mode="before")
    @classmethod
    def normalize_product_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value or []:
            product_id = str(item).strip()
            if product_id and product_id not in normalized:
                normalized.append(product_id)
        return normalized


class AdminGroceryBulkDeleteResponse(BaseModel):
    deleted_product_ids: list[str]
    missing_product_ids: list[str]
    deleted_count: int


class AdminGroceryUploadAssetResponse(BaseModel):
    url: str
    storage_backend: str
    content_type: str
    original_filename: str


class AdminGroceryUploadResponse(BaseModel):
    items: list[AdminGroceryUploadAssetResponse]


class AdminMetadataResponse(BaseModel):
    categories: list[GroceryCategoryResponse]
    cultures: list[dict[str, str]]
    nutrients: list[dict[str, int | str]]
    supported_countries: list[dict[str, str]]


class AdminBootstrapRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=5, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    user_types: list[Literal["platform_user"]] = Field(default_factory=lambda: ["platform_user"])
