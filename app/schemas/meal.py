from pydantic import BaseModel, Field

from app.models.grocery import CountryCode, CurrencyCode
from app.models.measurement import MeasurementType, RoundingRule, ScalingBehavior
from app.models.meal import MealDifficulty, MealHighlightTag, MealType


class MealCategoryResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    img_url: str
    sort_order: int


class MealEstimatedCostResponse(BaseModel):
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float


class MealSellingPriceResponse(BaseModel):
    country_code: CountryCode
    currency_code: CurrencyCode
    amount_minor: int


class MealNutritionSummaryResponse(BaseModel):
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float


class MealIngredientResponse(BaseModel):
    id: str
    name: str
    quantity: float
    unit: str
    optional: bool
    linked_product_ids: list[str]
    measurement_type: MeasurementType | None = None
    unit_code: str | None = None
    canonical_quantity: float | None = None
    canonical_unit: str | None = None
    conversion_profile_id: str | None = None
    scaling_behavior: ScalingBehavior = ScalingBehavior.LINEAR
    rounding_rule: RoundingRule | None = None


class MealRecipeStepResponse(BaseModel):
    instruction: str
    ingredient_ids: list[str]
    image_url: str | None = None


class LinkedGroceryProductResponse(BaseModel):
    id: str
    name: str
    img_url: str
    resolved_price: MealEstimatedCostResponse | None = None


class MealListItemResponse(BaseModel):
    id: str
    name: str
    hero_image_url: str
    image_urls: list[str]
    description: str
    meal_type: MealType
    category_ids: list[str]
    culture_tags: list[str]
    prep_time_minutes: int
    cook_time_minutes: int
    difficulty: MealDifficulty
    servings: int
    nutrition_summary: MealNutritionSummaryResponse
    resolved_estimated_cost: MealEstimatedCostResponse | None = None
    resolved_selling_price: MealEstimatedCostResponse | None = None
    rating_average: float = 0.0
    rating_count: int = 0
    highlight_tags: list[MealHighlightTag] = Field(default_factory=list)
    is_favorited: bool = False
    chef_available: bool


class MealListResponse(BaseModel):
    items: list[MealListItemResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class MealDetailResponse(MealListItemResponse):
    diet_rules_supported: list[str]
    allergy_exclusions: list[str]
    recipe_steps: list[str]
    recipe_step_items: list[MealRecipeStepResponse]
    ingredient_items: list[MealIngredientResponse]
    linked_product_ids: list[str]
    linked_products: list[LinkedGroceryProductResponse]
