from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.models.grocery import CountryCode, CurrencyCode, NutritionSpec
from app.models.measurement import MeasurementType, RoundingRule, ScalingBehavior


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class MealCategorySlug(StrEnum):
    QUICK_BREAKFASTS = "quick_breakfasts"
    BUDGET_FRIENDLY = "budget_friendly"
    HIGH_PROTEIN = "high_protein"
    NIGERIAN = "nigerian"
    INDIAN = "indian"
    BRITISH = "british"
    FAMILY_DINNERS = "family_dinners"
    LOW_EFFORT = "low_effort"
    HEALTHY = "healthy"


class MealDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    ADVANCED = "advanced"


class MealHighlightTag(StrEnum):
    HIGH_PROTEIN = "high_protein"
    RICH_FLAVOUR = "rich_flavour"
    FAMILY_FRIENDLY = "family_friendly"
    BUDGET_FRIENDLY = "budget_friendly"
    QUICK_EASY = "quick_easy"


@dataclass(frozen=True, slots=True)
class MealCategory:
    id: str
    slug: MealCategorySlug
    name: str
    description: str
    img_url: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MealEstimatedCost:
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float


@dataclass(frozen=True, slots=True)
class MealSellingPrice:
    country_code: CountryCode
    currency_code: CurrencyCode
    amount_minor: int


@dataclass(frozen=True, slots=True)
class MealNutritionSummary:
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True, slots=True)
class MealIngredient:
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


@dataclass(frozen=True, slots=True)
class MealRecipeStep:
    instruction: str
    ingredient_ids: list[str]
    image_url: str | None = None


@dataclass(frozen=True, slots=True)
class Meal:
    id: str
    name: str
    hero_image_url: str
    image_urls: list[str]
    description: str
    meal_type: MealType
    category_ids: list[str]
    culture_tags: list[str]
    diet_rules_supported: list[str]
    allergy_exclusions: list[str]
    prep_time_minutes: int
    cook_time_minutes: int
    difficulty: MealDifficulty
    servings: int
    nutritional_specs: list[NutritionSpec]
    nutrition_summary: MealNutritionSummary
    estimated_costs: list[MealEstimatedCost]
    recipe_steps: list[str]
    recipe_step_items: list[MealRecipeStep]
    ingredient_items: list[MealIngredient]
    linked_product_ids: list[str]
    chef_available: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    meal_types: list[MealType] = field(default_factory=list)
    selling_prices: list[MealSellingPrice] = field(default_factory=list)
    rating_average: float = 0.0
    rating_count: int = 0
    highlight_tags: list[MealHighlightTag] = field(default_factory=list)
