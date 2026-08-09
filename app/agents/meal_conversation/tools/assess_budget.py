from __future__ import annotations

from typing import Any

from app.models.grocery import CountryCode
from app.repositories.meal_repository import MealRepository


class AssessBudgetTool:
    name = "assess_budget"
    description = (
        "Assess whether one selected catalog meal fits the current budget posture in the active country. "
        "Use this near the end of selection, not before a meal_id is chosen."
    )

    def __init__(self, meal_repository: MealRepository) -> None:
        self._meal_repository = meal_repository

    def execute(
        self,
        *,
        slot: str,
        meal_id: str | None = None,
        weekly_budget: int | None = None,
        low_budget_mode: bool = False,
        country_code: str | None = None,
    ) -> dict[str, Any]:
        if not meal_id:
            return {"error": "meal_id is required."}
        meal = self._meal_repository.get_meal(meal_id)
        if meal is None:
            return {"error": "Meal not found."}

        resolved_country = CountryCode(country_code) if country_code else None
        resolved_cost = None
        if resolved_country is not None:
            for cost in meal.estimated_costs:
                if cost.country_code == resolved_country:
                    resolved_cost = cost
                    break

        if resolved_cost is None:
            return {
                "slot": slot,
                "fit": "unknown",
                "notes": ["No resolved country cost was available for this meal."],
            }

        threshold = None
        if weekly_budget is not None and weekly_budget > 0:
            threshold = max(weekly_budget / 7.0, 1.0)

        within_budget = None if threshold is None else resolved_cost.amount <= threshold
        if low_budget_mode and within_budget is False:
            fit = "poor"
        elif within_budget is True:
            fit = "good"
        else:
            fit = "unknown"

        return {
            "slot": slot,
            "fit": fit,
            "amount": resolved_cost.amount,
            "country_code": resolved_cost.country_code.value,
            "currency_code": resolved_cost.currency_code.value,
            "threshold": threshold,
            "low_budget_mode": low_budget_mode,
        }
