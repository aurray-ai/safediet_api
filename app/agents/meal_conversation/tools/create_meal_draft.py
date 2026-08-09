from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models.meal import MealType
from app.repositories.grocery_repository import GroceryRepository


class CreateMealDraftTool:
    name = "create_new_meal_draft"
    description = (
        "Create a user-scoped custom meal draft from real grocery product ids. "
        "Use this only after grounding the request in an existing catalog meal detail and only when the user explicitly asks for something new or custom."
    )

    def __init__(self, grocery_repository: GroceryRepository) -> None:
        self._grocery_repository = grocery_repository

    def execute(
        self,
        *,
        slot: str,
        meal_type: str,
        meal_name: str,
        requested_culture: str | None,
        product_ids: list[str],
        rationale: str,
    ) -> dict[str, Any]:
        resolved_products = self._grocery_repository.list_products_by_ids(product_ids)
        if not resolved_products:
            return {"error": "No valid grocery products were supplied for the new meal draft."}

        ingredient_items = []
        recipe_steps = []
        recipe_step_items = []
        nutrition_rollup: dict[str, float] = defaultdict(float)
        estimated_costs: list[dict[str, Any]] = []
        for index, product in enumerate(resolved_products, start=1):
            ingredient_id = f"ingredient_{index}"
            ingredient_items.append(
                {
                    "id": ingredient_id,
                    "name": product.product,
                    "quantity": 1.0,
                    "unit": "item",
                    "optional": False,
                    "linked_product_ids": [product.id],
                }
            )
            recipe_steps.append(f"Prepare {product.product.lower()} and stage it for the meal.")
            recipe_step_items.append(
                {
                    "instruction": f"Prepare {product.product.lower()} and stage it for the meal.",
                    "ingredient_ids": [ingredient_id],
                }
            )
            for spec in product.nutritional_specs:
                nutrition_rollup[str(spec.nutrient_id)] += float(spec.amount)
            if not estimated_costs:
                estimated_costs = [
                    {
                        "country_code": price.country_code.value,
                        "currency_code": price.currency_code.value,
                        "amount": float(price.amount),
                    }
                    for price in product.prices
                    if getattr(price, "is_active", True)
                ]

        draft_meal_type = MealType(meal_type).value
        return {
            "slot": slot,
            "meal_draft": {
                "name": meal_name,
                "hero_image_url": resolved_products[0].img_url if resolved_products else None,
                "description": (
                    f"A custom {draft_meal_type} draft grounded in currently available grocery support."
                ),
                "meal_type": draft_meal_type,
                "culture_tags": [requested_culture] if requested_culture else [],
                "prep_time_minutes": 15,
                "cook_time_minutes": 25,
                "servings": 2,
                "difficulty": "medium",
                "linked_product_ids": [product.id for product in resolved_products],
                "ingredient_items": ingredient_items,
                "recipe_steps": recipe_steps,
                "recipe_step_items": recipe_step_items,
                "nutrition_summary": dict(nutrition_rollup),
                "estimated_costs": estimated_costs,
                "rationale": rationale,
            }
        }
