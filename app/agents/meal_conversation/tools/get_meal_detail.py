from __future__ import annotations

from typing import Any

from app.models.grocery import CountryCode
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_repository import MealRepository


class GetMealDetailTool:
    name = "get_meal_detail"
    description = (
        "Load one selected meal in full detail. "
        "Use this only after you already have a specific meal_id and need recipe, ingredients, or linked products."
    )

    def __init__(
        self,
        meal_repository: MealRepository,
        grocery_repository: GroceryRepository,
    ) -> None:
        self._meal_repository = meal_repository
        self._grocery_repository = grocery_repository

    def execute(self, *, slot: str, meal_id: str, country_code: str | None = None) -> dict[str, Any]:
        meal = self._meal_repository.get_meal(meal_id)
        if meal is None:
            return {"error": "Meal not found."}

        resolved_country = CountryCode(country_code) if country_code else None
        linked_products = self._grocery_repository.list_products_by_ids(meal.linked_product_ids)
        return {
            "slot": slot,
            "meal": {
                "id": meal.id,
                "name": meal.name,
                "hero_image_url": meal.hero_image_url,
                "image_urls": meal.image_urls,
                "description": meal.description,
                "meal_type": meal.meal_type.value,
                "category_ids": meal.category_ids,
                "culture_tags": meal.culture_tags,
                "prep_time_minutes": meal.prep_time_minutes,
                "cook_time_minutes": meal.cook_time_minutes,
                "difficulty": meal.difficulty.value,
                "servings": meal.servings,
                "diet_rules_supported": meal.diet_rules_supported,
                "allergy_exclusions": meal.allergy_exclusions,
                "nutrition_summary": {
                    "calories": meal.nutrition_summary.calories,
                    "protein_g": meal.nutrition_summary.protein_g,
                    "carbs_g": meal.nutrition_summary.carbs_g,
                    "fat_g": meal.nutrition_summary.fat_g,
                },
                "estimated_cost": self._resolved_meal_cost(meal, resolved_country),
                "estimated_costs": [
                    {
                        "country_code": cost.country_code.value,
                        "currency_code": cost.currency_code.value,
                        "amount": cost.amount,
                    }
                    for cost in meal.estimated_costs
                ],
                "recipe_steps": meal.recipe_steps,
                "recipe_step_items": [
                    {
                        "instruction": step.instruction,
                        "ingredient_ids": step.ingredient_ids,
                        "image_url": step.image_url,
                    }
                    for step in meal.recipe_step_items
                ],
                "ingredient_items": [
                    {
                        "id": ingredient.id,
                        "name": ingredient.name,
                        "quantity": ingredient.quantity,
                        "unit": ingredient.unit,
                        "optional": ingredient.optional,
                        "linked_product_ids": ingredient.linked_product_ids,
                    }
                    for ingredient in meal.ingredient_items
                ],
                "linked_product_ids": meal.linked_product_ids,
                "linked_products": [
                    {
                        "id": product.id,
                        "name": product.product,
                        "img_url": product.img_url,
                        "resolved_price": self._resolved_product_price(product, resolved_country),
                    }
                    for product in linked_products
                ],
                "chef_available": meal.chef_available,
            }
        }

    @staticmethod
    def _resolved_meal_cost(meal, country_code: CountryCode | None) -> dict[str, Any] | None:
        if country_code is None:
            return None
        for cost in meal.estimated_costs:
            if cost.country_code == country_code:
                return {
                    "country_code": cost.country_code.value,
                    "currency_code": cost.currency_code.value,
                    "amount": cost.amount,
                }
        return None

    @staticmethod
    def _resolved_product_price(product, country_code: CountryCode | None) -> dict[str, Any] | None:
        if country_code is None:
            return None
        for price in product.prices:
            if price.is_active and price.country_code == country_code:
                return {
                    "country_code": price.country_code.value,
                    "currency_code": price.currency_code.value,
                    "amount": price.amount,
                }
        return None
