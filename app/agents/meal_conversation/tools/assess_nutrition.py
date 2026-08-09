from __future__ import annotations

from typing import Any

from app.repositories.meal_repository import MealRepository


class AssessNutritionTool:
    name = "assess_nutrition"
    description = (
        "Assess nutrition for a selected meal or created meal draft. "
        "Use this when you need a nutrition summary for the final response."
    )

    def __init__(self, meal_repository: MealRepository) -> None:
        self._meal_repository = meal_repository

    def execute(
        self,
        *,
        slot: str,
        meal_id: str | None = None,
        created_meal_draft: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if created_meal_draft is not None:
            nutrition_summary = dict(created_meal_draft.get("nutrition_summary") or {})
            return {
                "slot": slot,
                "summary": nutrition_summary,
                "fit": "approximate",
                "notes": ["Nutrition summary is estimated from the created meal draft."],
            }

        if not meal_id:
            return {"error": "A meal_id or created meal draft is required."}

        meal = self._meal_repository.get_meal(meal_id)
        if meal is None:
            return {"error": "Meal not found."}

        return {
            "slot": slot,
            "summary": {
                "calories": meal.nutrition_summary.calories,
                "protein_g": meal.nutrition_summary.protein_g,
                "carbs_g": meal.nutrition_summary.carbs_g,
                "fat_g": meal.nutrition_summary.fat_g,
            },
            "fit": "catalog",
            "notes": ["Nutrition summary is sourced from the meal catalog."],
        }
