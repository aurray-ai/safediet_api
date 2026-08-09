from __future__ import annotations

from typing import Any

from app.services.meal_semantic_search_service import MealSemanticSearchService


class SemanticSearchMealsTool:
    name = "semantic_search_meals"
    description = (
        "Retrieve semantically relevant catalog meals from a natural-language search query. "
        "Use this first when you need strong meal options for a slot based on taste, cuisine, goal, effort, or budget."
    )

    def __init__(self, search_service: MealSemanticSearchService) -> None:
        self._search_service = search_service

    def execute(
        self,
        *,
        slot: str,
        semantic_query: str,
        meal_type: str | None,
        requested_culture: str | None = None,
        diet_rules: list[str] | None = None,
        allergies: list[str] | None = None,
        country_code: str | None = None,
        low_budget_mode: bool = False,
        goal: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        items = self._search_service.search(
            semantic_query=semantic_query,
            meal_type=meal_type,
            requested_culture=requested_culture,
            diet_rules=diet_rules,
            allergies=allergies,
            country_code=country_code,
            low_budget_mode=low_budget_mode,
            goal=goal,
            limit=max(limit, 1),
        )
        return {
            "slot": slot,
            "semantic_query": semantic_query,
            "items": [
                {
                    "meal_id": item.meal.id,
                    "name": item.meal.name,
                    "meal_type": item.meal.meal_type.value,
                    "culture_tags": item.meal.culture_tags,
                    "description": item.meal.description,
                    "prep_time_minutes": item.meal.prep_time_minutes,
                    "cook_time_minutes": item.meal.cook_time_minutes,
                    "protein_g": item.meal.nutrition_summary.protein_g,
                    "calories": item.meal.nutrition_summary.calories,
                    "estimated_cost_amount": item.estimated_cost_amount,
                    "semantic_score": round(item.semantic_score, 4),
                    "why_it_matched": item.why_it_matched,
                }
                for item in items
            ],
        }
