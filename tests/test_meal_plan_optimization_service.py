from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.meal_inventory_reconciliation_service import MealInventoryReconciliationService
from app.services.meal_plan_cart_service import MealPlanCartService
from app.services.meal_plan_costing_service import MealPlanCostingService
from app.services.meal_plan_optimization_service import MealPlanOptimizationService


def make_candidate(
    *,
    meal_id: str,
    name: str,
    protein_g: float,
    calories: int,
    culture_tags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": meal_id,
        "name": name,
        "meal_type": "breakfast" if "breakfast" in meal_id else ("lunch" if "lunch" in meal_id else "dinner"),
        "servings": 2,
        "prep_time_minutes": 10,
        "cook_time_minutes": 15,
        "difficulty": "easy",
        "culture_tags": culture_tags or ["british"],
        "diet_rules_supported": ["high_protein"],
        "allergy_exclusions": ["peanut"],
        "ingredient_items": [],
        "linked_product_ids": [],
        "nutrition_summary": {
            "calories": calories,
            "protein_g": protein_g,
            "carbs_g": 30,
            "fat_g": 10,
        },
    }


class MealPlanOptimizationServiceTests(unittest.TestCase):
    def test_rank_bundles_caps_search_space_for_three_slots(self) -> None:
        grocery_repository = SimpleNamespace(list_products_by_ids=lambda product_ids: [])
        service = MealPlanOptimizationService(
            costing_service=MealPlanCostingService(grocery_repository),
            inventory_service=MealInventoryReconciliationService(),
            cart_service=MealPlanCartService(),
        )
        slot_candidates = {
            "breakfast": [
                make_candidate(meal_id="breakfast-1", name="Breakfast 1", protein_g=18, calories=320),
                make_candidate(meal_id="breakfast-2", name="Breakfast 2", protein_g=20, calories=340),
                make_candidate(meal_id="breakfast-3", name="Breakfast 3", protein_g=22, calories=360),
                make_candidate(meal_id="breakfast-4", name="Breakfast 4", protein_g=60, calories=650, culture_tags=["british"]),
            ],
            "lunch": [
                make_candidate(meal_id="lunch-1", name="Lunch 1", protein_g=22, calories=420),
                make_candidate(meal_id="lunch-2", name="Lunch 2", protein_g=24, calories=440),
                make_candidate(meal_id="lunch-3", name="Lunch 3", protein_g=26, calories=460),
                make_candidate(meal_id="lunch-4", name="Lunch 4", protein_g=52, calories=720, culture_tags=["british"]),
            ],
            "dinner": [
                make_candidate(meal_id="dinner-1", name="Dinner 1", protein_g=24, calories=450),
                make_candidate(meal_id="dinner-2", name="Dinner 2", protein_g=26, calories=470),
                make_candidate(meal_id="dinner-3", name="Dinner 3", protein_g=28, calories=490),
                make_candidate(meal_id="dinner-4", name="Dinner 4", protein_g=58, calories=760, culture_tags=["british"]),
            ],
        }

        ranked = service.rank_bundles(
            slot_candidates=slot_candidates,
            user_context={
                "goal": "build_muscle",
                "weekly_budget": 80,
                "household_size": 2,
                "culture_preferences": ["british"],
                "diet_rules": ["high_protein"],
                "allergies": ["peanut"],
            },
            pantry_items=[],
            country_code="GB",
            requested_culture="british",
            max_bundles=3,
        )

        self.assertEqual(3, len(ranked))
        self.assertTrue(
            all(
                all(not meal["meal_id"].endswith("-4") for meal in bundle["planned_meals"])
                for bundle in ranked
            ),
            "The optimizer should cap the search space before the 4th candidate of each slot.",
        )


if __name__ == "__main__":
    unittest.main()
