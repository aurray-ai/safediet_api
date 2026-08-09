from __future__ import annotations

from app.models.meal import Meal


def resolve_meal_unit_price_minor(*, meal: Meal, currency: str) -> int:
    """Resolves a meal's per-serving selling price in minor units for a given currency.

    Falls back to the meal's first configured selling price if none match the
    requested currency, and to 0 if the meal has no selling price configured at all.
    """
    for price in meal.selling_prices:
        if price.currency_code.value == currency:
            return price.amount_minor
    return meal.selling_prices[0].amount_minor if meal.selling_prices else 0
