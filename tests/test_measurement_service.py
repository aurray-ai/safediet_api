from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.measurement import MeasurementType, RoundingRule
from app.models.meal import Meal, MealDifficulty, MealEstimatedCost, MealIngredient, MealNutritionSummary, MealRecipeStep, MealType
from app.models.grocery import CountryCode, CurrencyCode
from app.repositories.measurement_repository import MeasurementRepository
from app.services.meal_scaling_service import MealScalingService
from app.services.measurement_service import MeasurementService


class FakeCollection:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        key = str(query["_id"])
        existing = self.items.get(key)
        if existing is None:
            payload = dict(update.get("$setOnInsert", {}))
            payload["_id"] = key
            self.items[key] = payload

    def find(self, query: dict):
        values = [item for item in self.items.values() if item.get("is_active", True) == query.get("is_active", True)]
        return FakeCursor(values)

    def find_one(self, query: dict):
        if "_id" in query:
            item = self.items.get(str(query["_id"]))
            if item is None:
                return None
            if query.get("is_active") is not None and item.get("is_active") != query.get("is_active"):
                return None
            return item
        if "code" in query:
            for item in self.items.values():
                if item.get("code") == query["code"] and item.get("is_active", True) == query.get("is_active", True):
                    return item
        return None


class FakeCursor:
    def __init__(self, values: list[dict]) -> None:
        self.values = values

    def sort(self, key: str, _direction):
        self.values.sort(key=lambda item: item.get(key))
        return self.values


class MeasurementServiceTests(unittest.TestCase):
    def test_seed_data_only_inserts_once_without_overwriting_existing_changes(self) -> None:
        units = FakeCollection()
        profiles = FakeCollection()
        repository = MeasurementRepository(units, profiles)

        repository.ensure_seed_data()
        original_display_name = units.items["g"]["display_name"]
        units.items["g"]["display_name"] = "My Custom Gram Label"
        repository.ensure_seed_data()

        self.assertEqual("My Custom Gram Label", units.items["g"]["display_name"])
        self.assertNotEqual(original_display_name, units.items["g"]["display_name"])

    def test_measurement_service_resolves_profile_backed_canonical_quantity(self) -> None:
        units = FakeCollection()
        profiles = FakeCollection()
        now = datetime.now(timezone.utc)
        units.items["cup_us"] = {
            "_id": "cup_us",
            "code": "cup_us",
            "display_name": "Cup (US)",
            "measurement_type": "volume",
            "canonical_unit": "ml",
            "multiplier_to_canonical": 236.588,
            "is_fractional_allowed": True,
            "default_rounding_rule": "nearest_0_25",
            "sort_order": 70,
            "aliases": ["cup"],
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        profiles.items["profile_rice_cup_uncooked"] = {
            "_id": "profile_rice_cup_uncooked",
            "name": "Uncooked rice cup to grams",
            "ingredient_name": "Rice",
            "linked_product_ids": [],
            "unit_code": "cup_us",
            "canonical_quantity": 185.0,
            "canonical_unit": "g",
            "notes": "Default uncooked rice conversion profile.",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        service = MeasurementService(MeasurementRepository(units, profiles))

        resolved = service.resolve_ingredient_measurement(
            quantity=2,
            unit="cup",
            unit_code="cup_us",
            measurement_type=None,
            canonical_quantity=None,
            canonical_unit=None,
            conversion_profile_id="profile_rice_cup_uncooked",
            scaling_behavior=None,
            rounding_rule=None,
        )

        self.assertEqual(MeasurementType.VOLUME, resolved.measurement_type)
        self.assertEqual("cup_us", resolved.unit_code)
        self.assertEqual(370.0, resolved.canonical_quantity)
        self.assertEqual("g", resolved.canonical_unit)

    def test_meal_scaling_service_scales_linear_ingredients_from_base_servings(self) -> None:
        now = datetime.now(timezone.utc)
        meal = Meal(
            id="meal-1",
            name="Rice Bowl",
            hero_image_url="",
            image_urls=[],
            description="",
            meal_type=MealType.LUNCH,
            category_ids=[],
            culture_tags=[],
            diet_rules_supported=[],
            allergy_exclusions=[],
            prep_time_minutes=0,
            cook_time_minutes=0,
            difficulty=MealDifficulty.EASY,
            servings=2,
            nutritional_specs=[],
            nutrition_summary=MealNutritionSummary(calories=0, protein_g=0, carbs_g=0, fat_g=0),
            estimated_costs=[
                MealEstimatedCost(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=1.0,
                )
            ],
            recipe_steps=[],
            recipe_step_items=[MealRecipeStep(instruction="", ingredient_ids=[])],
            ingredient_items=[
                MealIngredient(
                    id="ingredient_1",
                    name="Rice",
                    quantity=120,
                    unit="g",
                    optional=False,
                    linked_product_ids=["prod_rice"],
                    canonical_quantity=120,
                    canonical_unit="g",
                )
            ],
            linked_product_ids=["prod_rice"],
            chef_available=False,
            is_active=True,
            created_at=now,
            updated_at=now,
            meal_types=[MealType.LUNCH],
        )

        scaled = MealScalingService().scale_ingredients(meal=meal, target_servings=5)

        self.assertEqual(1, len(scaled))
        self.assertEqual(300, scaled[0].scaled_quantity)
        self.assertEqual(300.0, scaled[0].canonical_quantity)

    def test_meal_scaling_service_rounds_discrete_units_up(self) -> None:
        ingredient = MealIngredient(
            id="ingredient_egg",
            name="Egg",
            quantity=1,
            unit="whole",
            optional=False,
            linked_product_ids=["prod_egg"],
            canonical_quantity=1,
            canonical_unit="pcs",
            rounding_rule=RoundingRule.CEIL_WHOLE,
        )

        scaled = MealScalingService().scale_ingredient(ingredient=ingredient, scale_factor=1.6)

        self.assertEqual(2.0, scaled.scaled_quantity)


if __name__ == "__main__":
    unittest.main()
