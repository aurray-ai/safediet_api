from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MeasurementType(StrEnum):
    WEIGHT = "weight"
    VOLUME = "volume"
    COUNT = "count"
    PACK = "pack"


class ScalingBehavior(StrEnum):
    LINEAR = "linear"
    FIXED = "fixed"
    DISCRETE = "discrete"


class RoundingRule(StrEnum):
    NONE = "none"
    NEAREST_0_25 = "nearest_0_25"
    NEAREST_0_5 = "nearest_0_5"
    NEAREST_1 = "nearest_1"
    CEIL_WHOLE = "ceil_whole"


@dataclass(frozen=True, slots=True)
class MeasurementUnitDefinition:
    code: str
    display_name: str
    measurement_type: MeasurementType
    canonical_unit: str
    multiplier_to_canonical: float
    is_fractional_allowed: bool
    default_rounding_rule: RoundingRule
    sort_order: int
    aliases: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngredientConversionProfile:
    id: str
    name: str
    ingredient_name: str
    linked_product_ids: list[str]
    unit_code: str
    canonical_quantity: float
    canonical_unit: str
    notes: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
