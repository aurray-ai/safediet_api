from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum


class GroceryCategorySlug(StrEnum):
    GRAINS_CARBS = "grains_carbs"
    PROTEIN = "protein"
    VEGETABLES = "vegetables"
    FRUITS = "fruits"
    SPICES_SEASONING = "spices_seasoning"
    OILS_FATS = "oils_fats"
    DAIRY = "dairy"
    DRINKS = "drinks"
    SNACKS = "snacks"
    FROZEN_FOOD = "frozen_food"
    CANNED_FOOD = "canned_food"
    HEALTH_FITNESS_FOOD = "health_fitness_food"
    CULTURAL_FOOD_ITEMS = "cultural_food_items"


class CultureTag(StrEnum):
    INDIAN = "indian"
    BRITISH = "british"
    NIGERIAN = "nigerian"


class NutrientType(IntEnum):
    PROTEIN = 1
    CARBOHYDRATES = 2
    FAT = 3
    FIBER = 4
    SUGAR = 5
    SODIUM = 6
    CALORIES = 7
    SATURATED_FAT = 8
    CALCIUM = 9
    IRON = 10
    POTASSIUM = 11
    VITAMIN_C = 12
    VITAMIN_A = 13


class NutrientUnit(StrEnum):
    GRAM = "g"
    MILLIGRAM = "mg"
    KILOCALORIE = "kcal"
    MILLILITER = "ml"


class CountryCode(StrEnum):
    NIGERIA = "NG"
    UNITED_KINGDOM = "GB"
    INDIA = "IN"


class CurrencyCode(StrEnum):
    NAIRA = "NGN"
    POUND_STERLING = "GBP"
    INDIAN_RUPEE = "INR"


@dataclass(frozen=True, slots=True)
class GroceryCategory:
    id: str
    slug: GroceryCategorySlug
    name: str
    icon_name: str
    img_url: str
    description: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GroceryDiscount:
    id: str
    label: str
    percent: float
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NutritionSpec:
    nutrient_id: NutrientType
    amount: float
    unit: NutrientUnit


@dataclass(frozen=True, slots=True)
class CountryPrice:
    country_code: CountryCode
    currency_code: CurrencyCode
    amount: float
    price_unit: str
    source: str
    updated_at: datetime
    is_active: bool
    region: str | None = None
    city: str | None = None


@dataclass(frozen=True, slots=True)
class GroceryProduct:
    id: str
    category_id: str
    img_url: str
    product: str
    product_tags: list[str]
    culture_tags: list[CultureTag]
    nutritional_specs: list[NutritionSpec]
    prices: list[CountryPrice]
    description: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    discount_id: str | None = None
