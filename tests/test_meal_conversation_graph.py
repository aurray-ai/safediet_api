from __future__ import annotations

import json
import unittest

from app.agents.meal_conversation.subagents.meal_planner import graph as meal_planner_graph_module
from app.agents.meal_conversation.subagents.meal_planner.graph import MealPlannerGraph


class MealConversationGraphPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = MealPlannerGraph.__new__(MealPlannerGraph)

    def test_build_presentation_meal_detail_for_created_draft(self) -> None:
        meal = {
            "name": "British Breakfast Plate",
            "meal_type": "breakfast",
            "description": "A hearty breakfast with eggs, sausages, and toast.",
            "servings": 1,
            "prep_time_minutes": 10,
            "cook_time_minutes": 20,
            "difficulty": "medium",
            "culture_tags": ["british"],
            "ingredient_items": [
                {
                    "id": "egg",
                    "name": "Eggs",
                    "quantity": 2,
                    "unit": "pcs",
                    "optional": False,
                    "linked_product_ids": ["p1"],
                }
            ],
            "recipe_step_items": [
                {
                    "instruction": "Fry the eggs and sausages.",
                    "ingredient_ids": ["egg"],
                }
            ],
            "nutrition_summary": {
                "calories": 640,
                "protein_g": 32,
                "carbs_g": 24,
                "fat_g": 38,
            },
            "estimated_costs": [
                {
                    "country_code": "GB",
                    "currency_code": "GBP",
                    "amount": 3.2,
                }
            ],
        }
        grocery_items = [
            {
                "id": "p1",
                "name": "Free Range Eggs",
                "img_url": "https://example.com/eggs.jpg",
                "resolved_price": {
                    "country_code": "GB",
                    "currency_code": "GBP",
                    "amount": 1.85,
                },
            }
        ]

        result = self.graph._build_presentation_meal_detail(
            slot="breakfast",
            meal_source="created",
            meal=meal,
            grocery_items=grocery_items,
            nutrition_override=None,
        )

        self.assertEqual(result["total_time_minutes"], 30)
        self.assertEqual(result["estimated_cost_gbp"], 3.2)
        self.assertEqual(result["estimated_nutrition_per_serving"]["protein_g"], 32.0)
        self.assertEqual(result["ingredients"][0]["quantity_label"], "2 pcs")
        self.assertEqual(result["step_by_step"][0]["instruction"], "Fry the eggs and sausages.")
        self.assertEqual(result["shopping_list_grouped"][0]["title"], "Ingredients")
        self.assertEqual(result["shopping_list_grouped"][1]["title"], "Shop items")
        self.assertEqual(result["linked_products"][0]["name"], "Free Range Eggs")

    def test_build_presentation_meal_detail_for_catalog_meal_uses_estimated_costs_fallback(self) -> None:
        meal = {
            "id": "meal-1",
            "name": "Turkey Rice Bowl",
            "meal_type": "lunch",
            "description": "Lean turkey with seasoned rice.",
            "servings": 2,
            "prep_time_minutes": 12,
            "cook_time_minutes": 18,
            "difficulty": "easy",
            "diet_rules_supported": ["high_protein"],
            "allergy_exclusions": ["nuts"],
            "culture_tags": ["mediterranean"],
            "ingredient_items": [],
            "recipe_steps": ["Cook the rice.", "Finish the turkey in the pan."],
            "nutrition_summary": {
                "calories": 520,
                "protein_g": 41,
                "carbs_g": 46,
                "fat_g": 14,
            },
            "estimated_costs": [
                {
                    "country_code": "GB",
                    "currency_code": "GBP",
                    "amount": 4.8,
                }
            ],
            "linked_products": [],
        }

        result = self.graph._build_presentation_meal_detail(
            slot="lunch",
            meal_source="catalog",
            meal=meal,
            grocery_items=[],
            nutrition_override=None,
        )

        self.assertEqual(result["estimated_cost"]["formatted_amount"], "£4.80")
        self.assertEqual(result["estimated_cost_gbp"], 4.8)
        self.assertEqual(result["step_by_step"][1]["instruction"], "Finish the turkey in the pan.")
        self.assertEqual(result["diet_rules_supported"], ["high_protein"])
        self.assertEqual(result["allergy_exclusions"], ["nuts"])


class FakeModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def invoke(self, messages):
        return meal_planner_graph_module.AIMessage(
            content=json.dumps(self.payload),
            tool_calls=[],
        )


class StubRuntime:
    def __init__(self, model: FakeModel | None = None) -> None:
        self.model = model

    def set_active_user_id(self, user_id: str | None) -> None:
        return None

    def build_model(self):
        return self.model

    @property
    def model_name(self) -> str:
        return "stub-model"


def sample_candidate(*, meal_id: str, name: str, slot: str, protein: float, calories: int) -> dict[str, object]:
    return {
        "id": meal_id,
        "name": name,
        "meal_type": slot,
        "description": f"{name} description",
        "culture_tags": ["british"],
        "diet_rules_supported": ["high_protein"],
        "allergy_exclusions": ["nuts"],
        "estimated_costs": [
            {
                "country_code": "GB",
                "currency_code": "GBP",
                "amount": 4.5,
            }
        ],
        "ingredient_items": [
            {
                "id": "ingredient-1",
                "name": "Chicken",
                "quantity": 200,
                "unit": "g",
                "linked_product_ids": ["prod-1"],
            }
        ],
        "linked_product_ids": ["prod-1"],
        "nutrition_summary": {
            "calories": calories,
            "protein_g": protein,
            "carbs_g": 30,
            "fat_g": 12,
        },
        "cook_time_minutes": 20,
        "recipe_steps": ["Cook it."],
    }


class MealConversationGraphPlannerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = MealPlannerGraph.__new__(MealPlannerGraph)
        self.graph.runtime = StubRuntime()

    def test_prepare_planner_input_requires_user_context(self) -> None:
        state = {
            "action_payload": {
                "breakfast_slots": [sample_candidate(meal_id="meal-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)],
            },
            "run_context": {
                "user_id": "user-1",
            },
        }

        result = self.graph._prepare_planner_input(state)

        self.assertEqual("clarification_request", result["final_plan"]["turn_mode"])
        self.assertEqual("missing_user_context", result["final_plan"]["issue"])

    def test_prepare_planner_input_uses_only_explicit_slot_payloads(self) -> None:
        state = {
            "action_payload": {
                "user_context": {
                    "goal": "high_protein",
                    "weekly_budget": 80,
                    "diet_rules": ["high_protein"],
                    "allergies": ["peanut"],
                    "culture_preferences": ["british"],
                },
                "breakfast_slots": [sample_candidate(meal_id="meal-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)],
                "dinner_slots": [sample_candidate(meal_id="meal-2", name="Chicken Tray Bake", slot="dinner", protein=40, calories=610)],
            },
            "run_context": {
                "user_id": "user-1",
            },
        }

        result = self.graph._prepare_planner_input(state)
        constraint_state = result["constraint_state"]

        self.assertEqual(["breakfast", "dinner"], constraint_state["target_meal_types"])
        self.assertNotIn("lunch", result["candidate_meals_by_slot"])
        self.assertNotIn("snack", result["candidate_meals_by_slot"])
        self.assertNotIn("final_plan", result)

    def test_prepare_planner_input_preserves_effective_date_for_weekly_requests(self) -> None:
        state = {
            "action_payload": {
                "request_kind": "week_plan_request",
                "effective_date": "2026-06-29",
                "user_context": {
                    "goal": "high_protein",
                    "weekly_budget": 80,
                    "diet_rules": ["high_protein"],
                    "allergies": ["peanut"],
                    "culture_preferences": ["british"],
                },
                "breakfast_slots": [sample_candidate(meal_id="meal-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)],
            },
            "run_context": {
                "user_id": "user-1",
            },
        }

        result = self.graph._prepare_planner_input(state)

        self.assertEqual("week_plan_request", result["constraint_state"]["request_kind"])
        self.assertEqual("2026-06-29", result["constraint_state"]["effective_date"])

    def test_build_week_plan_days_rotates_fresh_days_and_carries_leftovers(self) -> None:
        breakfast_base = sample_candidate(meal_id="breakfast-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)
        breakfast_alt = sample_candidate(meal_id="breakfast-2", name="Yogurt Pot", slot="breakfast", protein=18, calories=310)
        lunch_base = sample_candidate(meal_id="lunch-1", name="Turkey Rice Bowl", slot="lunch", protein=34, calories=540)
        lunch_alt = sample_candidate(meal_id="lunch-2", name="Pasta Salad", slot="lunch", protein=22, calories=460)
        dinner_base = sample_candidate(meal_id="dinner-1", name="Chicken Tray Bake", slot="dinner", protein=40, calories=610)
        dinner_alt = sample_candidate(meal_id="dinner-2", name="Lentil Curry", slot="dinner", protein=26, calories=530)

        sections = [
            {
                "slot": "breakfast",
                "title": "Breakfast",
                "calories": 420,
                "items": [self.graph._build_weekly_section_item_from_candidate(slot="breakfast", meal=breakfast_base)],
            },
            {
                "slot": "lunch",
                "title": "Lunch",
                "calories": 540,
                "items": [self.graph._build_weekly_section_item_from_candidate(slot="lunch", meal=lunch_base)],
            },
            {
                "slot": "dinner",
                "title": "Dinner",
                "calories": 610,
                "items": [self.graph._build_weekly_section_item_from_candidate(slot="dinner", meal=dinner_base)],
            },
        ]
        state = {
            "constraint_state": {
                "target_meal_types": ["breakfast", "lunch", "dinner"],
                "effective_date": "2026-06-29",
                "household_size": 1,
            },
            "user_context": {
                "household_size": 1,
            },
            "candidate_meals_by_slot": {
                "breakfast": [breakfast_base, breakfast_alt],
                "lunch": [lunch_base, lunch_alt],
                "dinner": [dinner_base, dinner_alt],
            },
            "ranked_bundles": [
                {
                    "bundle_id": "bundle-alt",
                    "meals_by_slot": {
                        "breakfast": breakfast_alt,
                        "lunch": lunch_alt,
                        "dinner": dinner_alt,
                    },
                }
            ],
        }

        days = self.graph._build_week_plan_days(
            state=state,
            sections=sections,
            totals={"calories": 1570},
        )

        self.assertEqual("2026-06-29", days[0]["date"])
        self.assertEqual("Turkey Rice Bowl", days[0]["sections"][1]["items"][0]["name"])
        self.assertEqual("Yogurt Pot", days[1]["sections"][0]["items"][0]["name"])
        self.assertEqual("leftover", days[1]["sections"][1]["items"][0]["source_type"])
        self.assertEqual("Turkey Rice Bowl", days[1]["sections"][1]["items"][0]["name"])
        self.assertEqual("Pasta Salad", days[2]["sections"][1]["items"][0]["name"])
        self.assertEqual("fresh", days[2]["sections"][1]["items"][0]["source_type"])
        self.assertNotEqual(
            days[0]["sections"][2]["items"][0]["name"],
            days[2]["sections"][2]["items"][0]["name"],
        )
        self.assertEqual(
            days[0]["sections"][2]["items"][0]["batch_id"],
            days[1]["sections"][2]["items"][0]["origin_batch_id"],
        )

    def test_build_week_plan_days_scales_batch_servings_to_household_size(self) -> None:
        lunch = sample_candidate(meal_id="lunch-1", name="Turkey Rice Bowl", slot="lunch", protein=34, calories=540)
        sections = [
            {
                "slot": "lunch",
                "title": "Lunch",
                "calories": 540,
                "items": [self.graph._build_weekly_section_item_from_candidate(slot="lunch", meal=lunch)],
            }
        ]
        state = {
            "constraint_state": {
                "target_meal_types": ["lunch"],
                "effective_date": "2026-06-29",
                "household_size": 3,
            },
            "user_context": {
                "household_size": 3,
            },
            "candidate_meals_by_slot": {
                "lunch": [lunch],
            },
            "ranked_bundles": [],
        }

        days = self.graph._build_week_plan_days(
            state=state,
            sections=sections,
            totals={"calories": 540},
        )

        day_zero_lunch = days[0]["sections"][0]["items"][0]
        day_one_lunch = days[1]["sections"][0]["items"][0]

        self.assertEqual(3.0, day_zero_lunch["consumed_servings"])
        self.assertEqual(6.0, day_zero_lunch["yield_servings"])
        self.assertEqual(3.0, day_one_lunch["consumed_servings"])
        self.assertEqual(day_zero_lunch["batch_id"], day_one_lunch["origin_batch_id"])

    def test_materialize_selected_meals_maps_model_choice_to_candidate_payload(self) -> None:
        breakfast = sample_candidate(meal_id="meal-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)
        dinner = sample_candidate(meal_id="meal-2", name="Chicken Tray Bake", slot="dinner", protein=40, calories=610)
        state = {
            "constraint_state": {
                "target_meal_types": ["breakfast", "dinner"],
            },
            "candidate_meals_by_slot": {
                "breakfast": [breakfast],
                "dinner": [dinner],
            },
            "final_plan": {
                "turn_mode": "day_plan_generated",
                "assistant_text": "I picked meals for breakfast and dinner.",
                "rationale": "High protein and practical.",
                "requested_culture": "british",
                "planned_meals": [
                    {
                        "slot": "breakfast",
                        "meal_id": "meal-1",
                        "meal_name": "Egg Bowl",
                        "meal_source": "catalog",
                        "created_meal_draft": None,
                    },
                    {
                        "slot": "dinner",
                        "meal_id": "meal-2",
                        "meal_name": "Chicken Tray Bake",
                        "meal_source": "catalog",
                        "created_meal_draft": None,
                    },
                ],
                "totals": {},
            },
        }

        result = self.graph._materialize_selected_meals(state)

        self.assertEqual("meal-1", result["selected_meal_ids"]["breakfast"])
        self.assertEqual("Egg Bowl", result["selected_meal_details"]["breakfast"]["meal"]["name"])
        self.assertEqual(1030, result["final_plan"]["totals"]["calories"])
        self.assertEqual(65.0, result["final_plan"]["totals"]["protein_g"])

    def test_materialize_selected_meals_uses_ranked_bundle_selection_when_present(self) -> None:
        breakfast = sample_candidate(meal_id="meal-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)
        dinner = sample_candidate(meal_id="meal-2", name="Chicken Tray Bake", slot="dinner", protein=40, calories=610)
        state = {
            "constraint_state": {
                "target_meal_types": ["breakfast", "dinner"],
            },
            "ranked_bundles": [
                {
                    "bundle_id": "bundle-1",
                    "meals_by_slot": {
                        "breakfast": breakfast,
                        "dinner": dinner,
                    },
                    "planned_meals": [
                        {
                            "slot": "breakfast",
                            "meal_id": "meal-1",
                            "meal_name": "Egg Bowl",
                            "meal_source": "catalog",
                            "created_meal_draft": None,
                        },
                        {
                            "slot": "dinner",
                            "meal_id": "meal-2",
                            "meal_name": "Chicken Tray Bake",
                            "meal_source": "catalog",
                            "created_meal_draft": None,
                        },
                    ],
                    "totals": {
                        "calories": 1030,
                        "protein_g": 65.0,
                        "carbs_g": 60.0,
                        "fat_g": 24.0,
                    },
                    "bundle_summary": {"household_size": 2},
                    "inventory_summary": {"used_items_count": 1},
                    "cart_summary": {"items_to_buy_count": 2},
                }
            ],
            "final_plan": {
                "turn_mode": "day_plan_generated",
                "assistant_text": "I picked a ranked bundle.",
                "rationale": "Best overall fit.",
                "selected_bundle_id": "bundle-1",
                "planned_meals": [],
                "totals": {},
            },
        }

        result = self.graph._materialize_selected_meals(state)

        self.assertEqual("meal-1", result["selected_meal_ids"]["breakfast"])
        self.assertEqual("bundle-1", result["final_plan"]["selected_bundle_id"])
        self.assertEqual(1030, result["final_plan"]["totals"]["calories"])
        self.assertEqual(2, result["final_plan"]["cart_summary"]["items_to_buy_count"])

    def test_agent_returns_explicit_failure_when_model_is_unavailable(self) -> None:
        self.graph.runtime = StubRuntime(model=None)
        state = {
            "constraint_state": {
                "target_domain": "meal_planning",
                "request_kind": "day_plan_request",
                "target_meal_types": ["breakfast"],
                "slot_candidate_counts": {"breakfast": 1},
                "goal": "high_protein",
                "diet_rules": ["high_protein"],
                "allergies": [],
                "culture_preferences": ["british"],
                "requested_culture": "british",
                "weekly_budget": 80,
                "prompt_constraints": [],
            },
            "candidate_meals_by_slot": {
                "breakfast": [sample_candidate(meal_id="meal-1", name="Egg Bowl", slot="breakfast", protein=25, calories=420)],
            },
            "user_context": {
                "goal": "high_protein",
                "weekly_budget": 80,
                "diet_rules": ["high_protein"],
                "allergies": [],
                "culture_preferences": ["british"],
            },
            "messages": [],
            "agent_type": "meal_planner_agent",
            "latest_user_message": "Plan my breakfast.",
            "run_context": {
                "conversation_id": "conversation-1",
                "country_code": "GB",
            },
        }

        result = self.graph._agent(state)
        payload = json.loads(result["llm_raw"])

        self.assertEqual("conversation_reply", payload["turn_mode"])
        self.assertEqual([], payload["planned_meals"])
        self.assertEqual("llm_unavailable", payload["issue"])


if __name__ == "__main__":
    unittest.main()
