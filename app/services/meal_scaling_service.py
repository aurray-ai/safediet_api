from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.measurement import RoundingRule
from app.models.meal import Meal, MealIngredient


@dataclass(frozen=True, slots=True)
class ScaledIngredient:
    id: str
    name: str
    base_quantity: float
    scaled_quantity: float
    unit: str
    canonical_quantity: float | None
    canonical_unit: str | None
    optional: bool
    linked_product_ids: list[str]
    scale_factor: float


class MealScalingService:
    def scale_ingredients(
        self,
        *,
        meal: Meal,
        target_servings: float,
    ) -> list[ScaledIngredient]:
        base_servings = max(float(meal.servings or 1), 1.0)
        scale_factor = max(float(target_servings), 0.0) / base_servings
        return [
            self.scale_ingredient(
                ingredient=ingredient,
                scale_factor=scale_factor,
            )
            for ingredient in meal.ingredient_items
        ]

    def scale_ingredient(
        self,
        *,
        ingredient: MealIngredient,
        scale_factor: float,
    ) -> ScaledIngredient:
        scaled_display_quantity = self._apply_rounding_rule(
            ingredient.quantity * scale_factor,
            ingredient.rounding_rule,
        )
        scaled_canonical_quantity = (
            round(float(ingredient.canonical_quantity) * scale_factor, 2)
            if ingredient.canonical_quantity is not None
            else None
        )
        return ScaledIngredient(
            id=ingredient.id,
            name=ingredient.name,
            base_quantity=ingredient.quantity,
            scaled_quantity=scaled_display_quantity,
            unit=ingredient.unit,
            canonical_quantity=scaled_canonical_quantity,
            canonical_unit=ingredient.canonical_unit,
            optional=ingredient.optional,
            linked_product_ids=list(ingredient.linked_product_ids),
            scale_factor=scale_factor,
        )

    @staticmethod
    def _apply_rounding_rule(value: float, rule: RoundingRule | None) -> float:
        if rule in {None, RoundingRule.NONE}:
            return round(value, 2)
        if rule == RoundingRule.NEAREST_0_25:
            return round(value * 4) / 4
        if rule == RoundingRule.NEAREST_0_5:
            return round(value * 2) / 2
        if rule == RoundingRule.NEAREST_1:
            return round(value)
        if rule == RoundingRule.CEIL_WHOLE:
            return float(math.ceil(value))
        return round(value, 2)
