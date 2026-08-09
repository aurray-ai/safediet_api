from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.grocery import CountryCode, CultureTag, CurrencyCode
from app.models.measurement import MeasurementType, RoundingRule, ScalingBehavior
from app.models.meal import MealCategorySlug, MealDifficulty, MealHighlightTag, MealType
from app.schemas.meal import MealCategoryResponse


class AdminMealNutritionSummaryPayload(BaseModel):
    calories: int = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)


class AdminMealEstimatedCostPayload(BaseModel):
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float = Field(gt=0)


class AdminMealSellingPricePayload(BaseModel):
    country_code: CountryCode
    currency_code: CurrencyCode
    amount_minor: int = Field(gt=0)


class AdminMealIngredientPayload(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    optional: bool = False
    linked_product_ids: list[str] = Field(default_factory=list)
    measurement_type: MeasurementType | None = None
    unit_code: str | None = Field(default=None, min_length=1, max_length=40)
    canonical_quantity: float | None = Field(default=None, gt=0)
    canonical_unit: str | None = Field(default=None, min_length=1, max_length=40)
    conversion_profile_id: str | None = Field(default=None, min_length=1, max_length=120)
    scaling_behavior: ScalingBehavior = ScalingBehavior.LINEAR
    rounding_rule: RoundingRule | None = None

    @field_validator("id", "name", "unit", "unit_code", "canonical_unit", "conversion_profile_id", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("linked_product_ids", mode="before")
    @classmethod
    def normalize_product_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for product_id in value:
            cleaned = product_id.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class AdminMealRecipeStepPayload(BaseModel):
    instruction: str = Field(min_length=1, max_length=600)
    ingredient_ids: list[str] = Field(default_factory=list)
    image_url: str | None = Field(default=None, max_length=500)

    @field_validator("instruction", mode="before")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return value.strip()

    @field_validator("ingredient_ids", mode="before")
    @classmethod
    def normalize_ingredient_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for ingredient_id in value:
            cleaned = ingredient_id.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @field_validator("image_url", mode="before")
    @classmethod
    def normalize_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AdminMealPayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    hero_image_url: str = Field(default="", max_length=500)
    image_urls: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=2000)
    meal_type: MealType
    meal_types: list[MealType] = Field(default_factory=list)
    category_ids: list[str] = Field(default_factory=list, min_length=1)
    culture_tags: list[CultureTag] = Field(default_factory=list)
    diet_rules_supported: list[str] = Field(default_factory=list)
    allergy_exclusions: list[str] = Field(default_factory=list)
    prep_time_minutes: int = Field(ge=0, le=600)
    cook_time_minutes: int = Field(ge=0, le=600)
    difficulty: MealDifficulty
    servings: int = Field(ge=1, le=20)
    nutrition_summary: AdminMealNutritionSummaryPayload
    estimated_costs: list[AdminMealEstimatedCostPayload] = Field(default_factory=list)
    selling_prices: list[AdminMealSellingPricePayload] = Field(default_factory=list)
    rating_average: float = Field(default=0.0, ge=0, le=5)
    rating_count: int = Field(default=0, ge=0)
    highlight_tags: list[MealHighlightTag] = Field(default_factory=list)
    recipe_steps: list[str] = Field(default_factory=list, min_length=1)
    recipe_step_items: list[AdminMealRecipeStepPayload] = Field(default_factory=list)
    ingredient_items: list[AdminMealIngredientPayload] = Field(default_factory=list, min_length=1)
    chef_available: bool = False
    is_active: bool = True

    @field_validator(
        "name",
        "hero_image_url",
        "description",
        "image_urls",
        "diet_rules_supported",
        "allergy_exclusions",
        "recipe_steps",
        mode="before",
    )
    @classmethod
    def normalize_mixed_strings(cls, value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            normalized: list[str] = []
            for entry in value:
                cleaned = str(entry).strip()
                if cleaned and cleaned not in normalized:
                    normalized.append(cleaned)
            return normalized
        return value

    @field_validator("category_ids", mode="before")
    @classmethod
    def normalize_category_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for category_id in value:
            cleaned = category_id.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @model_validator(mode="before")
    @classmethod
    def normalize_meal_type_fields(cls, data):
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        raw_meal_type = normalized.get("meal_type")
        raw_meal_types = normalized.get("meal_types")

        meal_type = str(raw_meal_type).strip() if raw_meal_type is not None else None
        meal_types_input = raw_meal_types if isinstance(raw_meal_types, list) else [raw_meal_types] if raw_meal_types else []
        meal_types: list[str] = []
        for entry in meal_types_input:
            cleaned = str(entry).strip()
            if cleaned and cleaned not in meal_types:
                meal_types.append(cleaned)

        if meal_type is None:
            if not meal_types:
                raise ValueError("At least one meal type is required.")
            meal_type = meal_types[0]

        ordered_meal_types = [meal_type, *[entry for entry in meal_types if entry != meal_type]]
        normalized["meal_type"] = meal_type
        normalized["meal_types"] = ordered_meal_types
        return normalized

    @field_validator("culture_tags")
    @classmethod
    def deduplicate_cultures(cls, value: list[CultureTag]) -> list[CultureTag]:
        return list(dict.fromkeys(value))

    @field_validator("highlight_tags")
    @classmethod
    def deduplicate_highlight_tags(cls, value: list[MealHighlightTag]) -> list[MealHighlightTag]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_nested_uniqueness(self) -> "AdminMealPayload":
        country_codes = [cost.country_code for cost in self.estimated_costs]
        if len(set(country_codes)) != len(country_codes):
            raise ValueError("Each country can only have one estimated cost entry per meal.")

        selling_price_country_codes = [price.country_code for price in self.selling_prices]
        if len(set(selling_price_country_codes)) != len(selling_price_country_codes):
            raise ValueError("Each country can only have one selling price entry per meal.")

        ingredient_ids = [ingredient.id for ingredient in self.ingredient_items]
        if len(set(ingredient_ids)) != len(ingredient_ids):
            raise ValueError("Each ingredient row must have a unique id.")

        if self.recipe_step_items:
            referenced_ids = {
                ingredient_id
                for step in self.recipe_step_items
                for ingredient_id in step.ingredient_ids
            }
            invalid_ids = referenced_ids.difference(ingredient_ids)
            if invalid_ids:
                raise ValueError("Recipe steps reference unknown ingredient ids.")
        else:
            self.recipe_step_items = [
                AdminMealRecipeStepPayload(instruction=step, ingredient_ids=[])
                for step in self.recipe_steps
            ]

        self.recipe_steps = [step.instruction for step in self.recipe_step_items]
        normalized_image_urls: list[str] = []
        for image_url in self.image_urls:
            cleaned = str(image_url).strip()
            if cleaned and cleaned not in normalized_image_urls:
                normalized_image_urls.append(cleaned)
        if not normalized_image_urls and self.hero_image_url.strip():
            normalized_image_urls.append(self.hero_image_url.strip())
        if not normalized_image_urls:
            raise ValueError("Each meal must include at least one image.")
        self.image_urls = normalized_image_urls
        self.hero_image_url = normalized_image_urls[0]
        return self


class AdminMealCreateRequest(AdminMealPayload):
    meal_id: str | None = Field(default=None, max_length=120)

    @field_validator("meal_id", mode="before")
    @classmethod
    def normalize_meal_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "_")
        return normalized or None


class AdminMealProductOption(BaseModel):
    id: str
    name: str
    category_id: str
    img_url: str


class AdminMeasurementUnitOption(BaseModel):
    code: str
    display_name: str
    measurement_type: MeasurementType
    canonical_unit: str
    multiplier_to_canonical: float
    is_fractional_allowed: bool
    default_rounding_rule: RoundingRule
    aliases: list[str]


class AdminIngredientConversionProfileOption(BaseModel):
    id: str
    name: str
    ingredient_name: str
    linked_product_ids: list[str]
    unit_code: str
    canonical_quantity: float
    canonical_unit: str
    notes: str


class AdminMealTypeOption(BaseModel):
    value: MealType
    display_name: str


class AdminMealDifficultyOption(BaseModel):
    value: MealDifficulty
    display_name: str


class AdminMealResponse(AdminMealPayload):
    id: str
    linked_product_ids: list[str]
    created_at: datetime
    updated_at: datetime


class AdminMealListResponse(BaseModel):
    items: list[AdminMealResponse]
    total: int
    page: int
    page_size: int


class AdminMealBulkDeleteRequest(BaseModel):
    meal_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("meal_ids", mode="before")
    @classmethod
    def normalize_meal_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value or []:
            meal_id = str(item).strip()
            if meal_id and meal_id not in normalized:
                normalized.append(meal_id)
        return normalized


class AdminMealBulkDeleteResponse(BaseModel):
    deleted_meal_ids: list[str]
    missing_meal_ids: list[str]
    deleted_count: int


class AdminMealMetadataResponse(BaseModel):
    categories: list[MealCategoryResponse]
    cultures: list[dict[str, str]]
    meal_types: list[dict[str, str]]
    difficulties: list[dict[str, str]]
    supported_countries: list[dict[str, str]]
    products: list[AdminMealProductOption]
    measurement_units: list[AdminMeasurementUnitOption]
    ingredient_conversion_profiles: list[AdminIngredientConversionProfileOption]


class AdminMealUploadAssetResponse(BaseModel):
    url: str
    storage_backend: str
    content_type: str
    original_filename: str


class AdminMealUploadResponse(BaseModel):
    items: list[AdminMealUploadAssetResponse]
