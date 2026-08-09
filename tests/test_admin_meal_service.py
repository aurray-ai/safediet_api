from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.grocery import CountryCode, CurrencyCode, NutritionSpec, NutrientType, NutrientUnit
from app.models.measurement import MeasurementType, RoundingRule, ScalingBehavior
from app.data.measurement_seed import (
    DEFAULT_INGREDIENT_CONVERSION_PROFILE_SEEDS,
    DEFAULT_MEASUREMENT_UNIT_SEEDS,
)
from app.models.measurement import IngredientConversionProfile, MeasurementUnitDefinition
from app.models.meal import (
    Meal,
    MealDifficulty,
    MealEstimatedCost,
    MealIngredient,
    MealNutritionSummary,
    MealRecipeStep,
    MealType,
)
from app.schemas.admin_meal import AdminMealCreateRequest
from app.services.admin_meal_service import AdminMealService, AdminMealValidationError
from app.services.measurement_service import MeasurementService


class StubMealRepository:
    def __init__(self) -> None:
        self.create_kwargs: dict[str, object] | None = None
        self.update_kwargs: dict[str, object] | None = None
        self.deleted_meal_ids: list[str] = []
        self.meals_by_id: dict[str, Meal] = {"meal-1": build_meal(), "meal-2": build_meal()}

    @staticmethod
    def build_search_document(payload: dict[str, object]) -> str:
        return f"{payload['name']} | {payload['description']}"

    def create_meal(self, **kwargs):
        self.create_kwargs = dict(kwargs)
        return build_meal()

    def update_meal(self, **kwargs):
        self.update_kwargs = dict(kwargs)
        return build_meal()

    def delete_meal(self, meal_id: str) -> bool:
        self.deleted_meal_ids.append(meal_id)
        return True

    def delete_meals(self, meal_ids: list[str]) -> int:
        self.deleted_meal_ids.extend(meal_ids)
        return len(meal_ids)

    @staticmethod
    def list_categories():
        return []

    @staticmethod
    def get_category(category_id: str):
        return object()

    def get_meal_by_id(self, meal_id: str):
        return self.meals_by_id.get(meal_id)

    @staticmethod
    def list_all_meals(**kwargs):
        return [], 0


class StubGroceryRepository:
    @staticmethod
    def get_product_by_id(product_id: str):
        return type("Product", (), {"id": product_id})()

    @staticmethod
    def list_all_products(page: int, page_size: int):
        return [], 0


class StubMealCatalogEmbeddingService:
    def __init__(self) -> None:
        self.search_documents: list[str] = []

    def create_embedding_payload(self, *, search_document: str) -> dict[str, object]:
        self.search_documents.append(search_document)
        return {
            "search_document": search_document,
            "search_embedding": [0.3, 0.7],
            "search_embedding_model": "test-embed-1",
            "search_embedding_source_hash": "hash-123",
        }


class StubMeasurementRepository:
    @staticmethod
    def list_units():
        now = datetime.now(timezone.utc)
        return [
            MeasurementUnitDefinition(
                code=str(seed["code"]),
                display_name=str(seed["display_name"]),
                measurement_type=MeasurementType(str(seed["measurement_type"])),
                canonical_unit=str(seed["canonical_unit"]),
                multiplier_to_canonical=float(seed["multiplier_to_canonical"]),
                is_fractional_allowed=bool(seed["is_fractional_allowed"]),
                default_rounding_rule=RoundingRule(str(seed["default_rounding_rule"])),
                sort_order=int(seed["sort_order"]),
                aliases=[str(item) for item in list(seed["aliases"])],
                is_active=bool(seed["is_active"]),
                created_at=now,
                updated_at=now,
            )
            for seed in DEFAULT_MEASUREMENT_UNIT_SEEDS
        ]

    @staticmethod
    def list_conversion_profiles():
        now = datetime.now(timezone.utc)
        return [
            IngredientConversionProfile(
                id=str(seed["id"]),
                name=str(seed["name"]),
                ingredient_name=str(seed["ingredient_name"]),
                linked_product_ids=[str(item) for item in list(seed["linked_product_ids"])],
                unit_code=str(seed["unit_code"]),
                canonical_quantity=float(seed["canonical_quantity"]),
                canonical_unit=str(seed["canonical_unit"]),
                notes=str(seed["notes"]),
                is_active=bool(seed["is_active"]),
                created_at=now,
                updated_at=now,
            )
            for seed in DEFAULT_INGREDIENT_CONVERSION_PROFILE_SEEDS
        ]

    @staticmethod
    def get_unit_by_code(unit_code: str):
        return None

    @staticmethod
    def get_conversion_profile(profile_id: str):
        return None


def build_payload() -> AdminMealCreateRequest:
    return AdminMealCreateRequest.model_validate(
        {
            "name": "Chicken Rice Bowl",
            "hero_image_url": "",
            "image_urls": [
                "https://cdn.example.com/meal-1.jpg",
                "https://cdn.example.com/meal-2.jpg",
            ],
            "description": "Balanced bowl",
            "meal_types": ["lunch"],
            "category_ids": ["cat-1"],
            "culture_tags": ["british"],
            "diet_rules_supported": ["high_protein"],
            "allergy_exclusions": ["nuts"],
            "prep_time_minutes": 10,
            "cook_time_minutes": 15,
            "difficulty": "easy",
            "servings": 2,
            "nutrition_summary": {
                "calories": 540,
                "protein_g": 34,
                "carbs_g": 52,
                "fat_g": 14,
            },
            "estimated_costs": [
                {
                    "country_code": "GB",
                    "currency_code": "GBP",
                    "amount": 4.2,
                }
            ],
            "recipe_steps": ["Cook the rice"],
            "recipe_step_items": [
                {
                    "instruction": "Cook the rice",
                    "ingredient_ids": ["ingredient_1"],
                    "image_url": " https://cdn.example.com/step-1.jpg ",
                }
            ],
            "ingredient_items": [
                {
                    "id": "ingredient_1",
                    "name": "Rice",
                    "quantity": 120,
                    "unit": "g",
                    "optional": False,
                    "linked_product_ids": ["prod-1"],
                }
            ],
            "chef_available": False,
            "is_active": True,
        }
    )


def build_meal() -> Meal:
    return Meal(
        id="meal-1",
        name="Chicken Rice Bowl",
        hero_image_url="https://cdn.example.com/meal-1.jpg",
        image_urls=[
            "https://cdn.example.com/meal-1.jpg",
            "https://cdn.example.com/meal-2.jpg",
        ],
        description="Balanced bowl",
        meal_type=MealType.LUNCH,
        category_ids=["cat-1"],
        culture_tags=["british"],
        diet_rules_supported=["high_protein"],
        allergy_exclusions=["nuts"],
        prep_time_minutes=10,
        cook_time_minutes=15,
        difficulty=MealDifficulty.EASY,
        servings=2,
        nutritional_specs=[
            NutritionSpec(nutrient_id=NutrientType.CALORIES, amount=540, unit=NutrientUnit.KILOCALORIE),
            NutritionSpec(nutrient_id=NutrientType.PROTEIN, amount=34, unit=NutrientUnit.GRAM),
            NutritionSpec(nutrient_id=NutrientType.CARBOHYDRATES, amount=52, unit=NutrientUnit.GRAM),
            NutritionSpec(nutrient_id=NutrientType.FAT, amount=14, unit=NutrientUnit.GRAM),
            NutritionSpec(nutrient_id=NutrientType.POTASSIUM, amount=470, unit=NutrientUnit.MILLIGRAM),
        ],
        nutrition_summary=MealNutritionSummary(
            calories=540,
            protein_g=34,
            carbs_g=52,
            fat_g=14,
        ),
        estimated_costs=[
            MealEstimatedCost(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=4.2,
            )
        ],
        recipe_steps=["Cook the rice"],
        recipe_step_items=[
            MealRecipeStep(
                instruction="Cook the rice",
                ingredient_ids=["ingredient_1"],
                image_url="https://cdn.example.com/step-1.jpg",
            )
        ],
        ingredient_items=[
            MealIngredient(
                id="ingredient_1",
                name="Rice",
                quantity=120,
                unit="g",
                optional=False,
                linked_product_ids=["prod-1"],
                measurement_type=MeasurementType.WEIGHT,
                unit_code="g",
                canonical_quantity=120,
                canonical_unit="g",
                conversion_profile_id=None,
                scaling_behavior=ScalingBehavior.LINEAR,
                rounding_rule=RoundingRule.NEAREST_1,
            )
        ],
        linked_product_ids=["prod-1"],
        chef_available=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        meal_types=[MealType.LUNCH],
    )


class AdminMealServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.meal_repository = StubMealRepository()
        self.embedding_service = StubMealCatalogEmbeddingService()
        self.service = AdminMealService(
            meal_repository=self.meal_repository,
            grocery_repository=StubGroceryRepository(),
            measurement_service=MeasurementService(StubMeasurementRepository()),
            meal_catalog_embedding_service=self.embedding_service,
        )

    def test_payload_normalizes_primary_image_and_step_image(self) -> None:
        payload = build_payload()

        self.assertEqual(payload.hero_image_url, "https://cdn.example.com/meal-1.jpg")
        self.assertEqual(payload.image_urls[1], "https://cdn.example.com/meal-2.jpg")
        self.assertEqual(payload.recipe_step_items[0].image_url, "https://cdn.example.com/step-1.jpg")
        self.assertEqual(payload.meal_type, MealType.LUNCH)
        self.assertEqual(payload.meal_types, [MealType.LUNCH])

    def test_payload_accepts_multiple_meal_types_and_derives_primary(self) -> None:
        payload = AdminMealCreateRequest.model_validate(
            {
                **build_payload().model_dump(mode="json"),
                "meal_type": None,
                "meal_types": ["breakfast", "lunch"],
            }
        )

        self.assertEqual(payload.meal_type, MealType.BREAKFAST)
        self.assertEqual(payload.meal_types, [MealType.BREAKFAST, MealType.LUNCH])

    def test_validation_requires_linked_products_for_planner_readiness(self) -> None:
        payload = build_payload().model_copy(
            update={
                "ingredient_items": [
                    build_payload().ingredient_items[0].model_copy(
                        update={"linked_product_ids": []}
                    )
                ]
            }
        )

        with self.assertRaises(AdminMealValidationError):
            AdminMealService._validate_meal_payload(payload, [])

    def test_create_meal_persists_embedding_payload_immediately(self) -> None:
        self.service.create_meal(build_payload())

        self.assertIsNotNone(self.meal_repository.create_kwargs)
        assert self.meal_repository.create_kwargs is not None
        self.assertEqual(
            "Chicken Rice Bowl | Balanced bowl",
            self.embedding_service.search_documents[0],
        )
        self.assertEqual(540, self.meal_repository.create_kwargs["nutrition_summary"]["calories"])
        self.assertEqual(34.0, self.meal_repository.create_kwargs["nutrition_summary"]["protein_g"])
        self.assertEqual(52.0, self.meal_repository.create_kwargs["nutrition_summary"]["carbs_g"])
        self.assertEqual(14.0, self.meal_repository.create_kwargs["nutrition_summary"]["fat_g"])
        self.assertEqual(
            [0.3, 0.7],
            self.meal_repository.create_kwargs["search_embedding"],
        )
        self.assertEqual(
            ["lunch"],
            self.meal_repository.create_kwargs["meal_types"],
        )
        self.assertEqual(
            "test-embed-1",
            self.meal_repository.create_kwargs["search_embedding_model"],
        )
        self.assertEqual(
            "g",
            self.meal_repository.create_kwargs["ingredient_items"][0]["unit_code"],
        )
        self.assertEqual(
            120.0,
            self.meal_repository.create_kwargs["ingredient_items"][0]["canonical_quantity"],
        )

    def test_create_meal_always_generates_id(self) -> None:
        payload = build_payload().model_copy(update={"meal_id": "custom_meal_id"})

        self.service.create_meal(payload)

        assert self.meal_repository.create_kwargs is not None
        generated_meal_id = self.meal_repository.create_kwargs["meal_id"]
        self.assertTrue(str(generated_meal_id).startswith("meal_chicken_rice_bowl_"))
        self.assertNotEqual(generated_meal_id, "custom_meal_id")

    def test_update_meal_persists_embedding_payload_immediately(self) -> None:
        self.service.update_meal(meal_id="meal-1", payload=build_payload())

        self.assertIsNotNone(self.meal_repository.update_kwargs)
        assert self.meal_repository.update_kwargs is not None
        self.assertEqual(
            [0.3, 0.7],
            self.meal_repository.update_kwargs["search_embedding"],
        )
        self.assertEqual(
            "hash-123",
            self.meal_repository.update_kwargs["search_embedding_source_hash"],
        )

    def test_response_includes_image_gallery_and_step_images(self) -> None:
        response = AdminMealService._to_response(build_meal())

        self.assertEqual(response.image_urls[0], "https://cdn.example.com/meal-1.jpg")
        self.assertEqual(response.recipe_step_items[0].image_url, "https://cdn.example.com/step-1.jpg")
        self.assertEqual(response.meal_types, [MealType.LUNCH])
        self.assertEqual(response.ingredient_items[0].unit_code, "g")
        self.assertEqual(response.ingredient_items[0].canonical_unit, "g")

    def test_metadata_includes_measurement_settings(self) -> None:
        metadata = self.service.get_metadata()

        self.assertTrue(len(metadata.measurement_units) > 0)
        self.assertTrue(any(unit.code == "cup_us" for unit in metadata.measurement_units))
        self.assertTrue(any(profile.id == "profile_rice_cup_uncooked" for profile in metadata.ingredient_conversion_profiles))

    def test_delete_meal_deletes_existing_record(self) -> None:
        self.service.delete_meal("meal-1")

        self.assertEqual(["meal-1"], self.meal_repository.deleted_meal_ids)

    def test_delete_meals_deletes_existing_records_and_skips_missing(self) -> None:
        response = self.service.delete_meals(["meal-1", "missing-meal", "meal-2"])

        self.assertEqual(["meal-1", "meal-2"], response.deleted_meal_ids)
        self.assertEqual(["missing-meal"], response.missing_meal_ids)
        self.assertEqual(2, response.deleted_count)
        self.assertEqual(["meal-1", "meal-2"], self.meal_repository.deleted_meal_ids)


if __name__ == "__main__":
    unittest.main()
