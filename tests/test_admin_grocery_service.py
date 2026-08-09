from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryProduct, NutritionSpec, NutrientType, NutrientUnit
from app.schemas.admin_grocery import AdminGroceryProductCreateRequest
from app.services.admin_grocery_service import (
    AdminGroceryBulkDeleteResponse,
    AdminGroceryProductNotFoundError,
    AdminGroceryService,
    AdminGroceryValidationError,
)


class AdminGroceryServiceTests(unittest.TestCase):
    def test_product_payload_requires_image(self) -> None:
        with self.assertRaises(ValueError):
            AdminGroceryProductCreateRequest.model_validate(
                {
                    "category_id": "cat-1",
                    "img_url": "",
                    "product": "Greek Yogurt",
                    "description": "Protein-rich yogurt",
                    "product_tags": ["dairy"],
                    "culture_tags": ["british"],
                    "nutritional_specs": [],
                    "prices": [
                        {
                            "country_code": "GB",
                            "currency_code": "GBP",
                            "amount": 2.5,
                            "price_unit": "500g",
                        }
                    ],
                    "is_active": True,
                }
            )

    def test_validation_requires_positive_price_entry(self) -> None:
        payload = AdminGroceryProductCreateRequest.model_validate(
            {
                "category_id": "cat-1",
                "img_url": "https://cdn.example.com/yogurt.jpg",
                "product": "Greek Yogurt",
                "description": "Protein-rich yogurt",
                "product_tags": ["dairy"],
                "culture_tags": ["british"],
                "nutritional_specs": [],
                "prices": [
                    {
                        "country_code": "GB",
                        "currency_code": "GBP",
                        "amount": 1.0,
                        "price_unit": "500g",
                    }
                ],
                "is_active": True,
            }
        )

        payload.prices = []

        with self.assertRaises(AdminGroceryValidationError):
            AdminGroceryService._validate_product_payload(payload)

    def test_response_includes_image_url(self) -> None:
        product = GroceryProduct(
            id="prod-1",
            category_id="cat-1",
            img_url="https://cdn.example.com/yogurt.jpg",
            product="Greek Yogurt",
            description="Protein-rich yogurt",
            product_tags=["dairy"],
            culture_tags=["british"],
            nutritional_specs=[
                NutritionSpec(
                    nutrient_id=NutrientType.PROTEIN,
                    amount=10,
                    unit=NutrientUnit.GRAM,
                )
            ],
            prices=[
                CountryPrice(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=2.5,
                    price_unit="500g",
                    source="admin_dashboard",
                    updated_at=datetime.now(timezone.utc),
                    is_active=True,
                )
            ],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        response = AdminGroceryService._to_response(product)

        self.assertEqual(response.img_url, "https://cdn.example.com/yogurt.jpg")

    def test_response_allows_missing_image_url_for_seeded_product(self) -> None:
        product = GroceryProduct(
            id="prod-1",
            category_id="cat-1",
            img_url="",
            product="Greek Yogurt",
            description="Protein-rich yogurt",
            product_tags=["dairy"],
            culture_tags=["british"],
            nutritional_specs=[],
            prices=[
                CountryPrice(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=2.5,
                    price_unit="500g",
                    source="admin_dashboard",
                    updated_at=datetime.now(timezone.utc),
                    is_active=True,
                )
            ],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        response = AdminGroceryService._to_response(product)

        self.assertEqual(response.img_url, "")

    def test_create_product_always_generates_id(self) -> None:
        payload = AdminGroceryProductCreateRequest.model_validate(
            {
                "product_id": "custom_product_id",
                "category_id": "cat-1",
                "img_url": "https://cdn.example.com/yogurt.jpg",
                "product": "Greek Yogurt",
                "description": "Protein-rich yogurt",
                "product_tags": ["dairy"],
                "culture_tags": ["british"],
                "nutritional_specs": [],
                "prices": [
                    {
                        "country_code": "GB",
                        "currency_code": "GBP",
                        "amount": 2.5,
                        "price_unit": "500g",
                    }
                ],
                "is_active": True,
            }
        )
        repository = Mock()
        repository.get_category.return_value = Mock()
        repository.create_product.return_value = GroceryProduct(
            id="prod_greek_yogurt_12345678",
            category_id="cat-1",
            img_url="https://cdn.example.com/yogurt.jpg",
            product="Greek Yogurt",
            description="Protein-rich yogurt",
            product_tags=["dairy"],
            culture_tags=["british"],
            nutritional_specs=[],
            prices=[
                CountryPrice(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=2.5,
                    price_unit="500g",
                    source="admin_dashboard",
                    updated_at=datetime.now(timezone.utc),
                    is_active=True,
                )
            ],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        service = AdminGroceryService(repository)
        service.create_product(payload)

        repository.create_product.assert_called_once()
        generated_product_id = repository.create_product.call_args.kwargs["product_id"]
        self.assertTrue(generated_product_id.startswith("prod_greek_yogurt_"))
        self.assertNotEqual(generated_product_id, "custom_product_id")

    def test_get_metadata_includes_extended_micronutrients(self) -> None:
        repository = Mock()
        repository.list_all_categories.return_value = []

        service = AdminGroceryService(repository)

        response = service.get_metadata()

        potassium = next((item for item in response.nutrients if item["slug"] == "potassium"), None)
        vitamin_c = next((item for item in response.nutrients if item["slug"] == "vitamin_c"), None)
        vitamin_a = next((item for item in response.nutrients if item["slug"] == "vitamin_a"), None)
        self.assertIsNotNone(potassium)
        self.assertIsNotNone(vitamin_c)
        self.assertIsNotNone(vitamin_a)
        self.assertEqual(potassium["display_name"], "Potassium")
        self.assertEqual(potassium["default_unit"], "mg")
        self.assertEqual(vitamin_c["display_name"], "Vitamin C")
        self.assertEqual(vitamin_c["default_unit"], "mg")
        self.assertEqual(vitamin_a["display_name"], "Vitamin A")
        self.assertEqual(vitamin_a["default_unit"], "mg")

    def test_delete_product_deletes_existing_product(self) -> None:
        repository = Mock()
        repository.delete_product.return_value = True

        service = AdminGroceryService(repository)

        service.delete_product("prod-1")

        repository.delete_product.assert_called_once_with("prod-1")

    def test_delete_product_raises_when_missing(self) -> None:
        repository = Mock()
        repository.delete_product.return_value = False

        service = AdminGroceryService(repository)

        with self.assertRaises(AdminGroceryProductNotFoundError):
            service.delete_product("missing-product")

    def test_delete_products_returns_deleted_and_missing_ids(self) -> None:
        repository = Mock()
        repository.get_product_by_id.side_effect = [Mock(id="prod-1"), None, Mock(id="prod-3")]
        repository.delete_products.return_value = 2

        service = AdminGroceryService(repository)

        response = service.delete_products(["prod-1", "prod-2", "prod-3"])

        self.assertIsInstance(response, AdminGroceryBulkDeleteResponse)
        self.assertEqual(response.deleted_product_ids, ["prod-1", "prod-3"])
        self.assertEqual(response.missing_product_ids, ["prod-2"])
        self.assertEqual(response.deleted_count, 2)
        repository.delete_products.assert_called_once_with(["prod-1", "prod-3"])

    def test_delete_products_raises_when_delete_count_mismatches(self) -> None:
        repository = Mock()
        repository.get_product_by_id.side_effect = [Mock(id="prod-1"), Mock(id="prod-2")]
        repository.delete_products.return_value = 1

        service = AdminGroceryService(repository)

        with self.assertRaises(AdminGroceryValidationError):
            service.delete_products(["prod-1", "prod-2"])


if __name__ == "__main__":
    unittest.main()
