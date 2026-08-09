from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from app.models.grocery import (
    CountryCode,
    CountryPrice,
    CurrencyCode,
    GroceryCategory,
    GroceryCategorySlug,
    GroceryProduct,
)
from app.services.grocery_service import GroceryService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_category(*, category_id: str, discount_percent: float | None) -> GroceryCategory:
    now = utc_now()
    return GroceryCategory(
        id=category_id,
        slug=GroceryCategorySlug.PROTEIN,
        name="Protein",
        icon_name="protein",
        img_url="",
        description="",
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
        discount_percent=discount_percent,
    )


def build_product(*, product_id: str = "product-1", category_id: str, amount: float = 10.0) -> GroceryProduct:
    now = utc_now()
    return GroceryProduct(
        id=product_id,
        category_id=category_id,
        img_url="",
        product="Chicken breast",
        product_tags=[],
        culture_tags=[],
        nutritional_specs=[],
        prices=[
            CountryPrice(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=amount,
                price_unit="pack",
                source="test",
                updated_at=now,
                is_active=True,
            )
        ],
        description="",
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


class StubGroceryRepository:
    def __init__(
        self,
        *,
        category: GroceryCategory,
        products: list[GroceryProduct],
        extra_categories: list[GroceryCategory] | None = None,
    ) -> None:
        self._categories = {category.id: category}
        for extra_category in extra_categories or []:
            self._categories[extra_category.id] = extra_category
        self._products = products
        self.get_category_calls: list[str] = []

    def get_category(self, category_id: str):
        self.get_category_calls.append(category_id)
        return self._categories.get(category_id)

    def list_products(self, **_kwargs):
        return self._products, len(self._products)

    def list_products_by_category(self, **_kwargs):
        return self._products, len(self._products)

    def get_product(self, product_id: str):
        return next((product for product in self._products if product.id == product_id), None)


class GroceryServiceTests(unittest.TestCase):
    def test_list_nutrients_includes_extended_micronutrients(self) -> None:
        service = GroceryService(Mock())

        response = service.list_nutrients()

        potassium = next((item for item in response if item.slug == "potassium"), None)
        vitamin_c = next((item for item in response if item.slug == "vitamin_c"), None)
        vitamin_a = next((item for item in response if item.slug == "vitamin_a"), None)
        self.assertIsNotNone(potassium)
        self.assertIsNotNone(vitamin_c)
        self.assertIsNotNone(vitamin_a)
        self.assertEqual(potassium.display_name, "Potassium")
        self.assertEqual(potassium.default_unit.value, "mg")
        self.assertEqual(vitamin_c.display_name, "Vitamin C")
        self.assertEqual(vitamin_c.default_unit.value, "mg")
        self.assertEqual(vitamin_a.display_name, "Vitamin A")
        self.assertEqual(vitamin_a.default_unit.value, "mg")

    def test_list_products_includes_member_price_when_category_discounted(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=10.0)
        product = build_product(category_id="cat-1", amount=10.0)
        repository = StubGroceryRepository(category=category, products=[product])
        service = GroceryService(repository)

        response = service.list_products(
            country=CountryCode.UNITED_KINGDOM,
            culture=None,
            search=None,
            product_tag=None,
            category_id=None,
            sort=None,
            page=1,
            page_size=20,
        )

        resolved = response.items[0].resolved_price
        self.assertIsNotNone(resolved)
        self.assertEqual(10.0, resolved.amount)
        self.assertEqual(9.0, resolved.member_amount)
        self.assertEqual(10.0, resolved.discount_percent)

    def test_list_products_omits_member_price_when_category_has_no_discount(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=None)
        product = build_product(category_id="cat-1", amount=10.0)
        repository = StubGroceryRepository(category=category, products=[product])
        service = GroceryService(repository)

        response = service.list_products(
            country=CountryCode.UNITED_KINGDOM,
            culture=None,
            search=None,
            product_tag=None,
            category_id=None,
            sort=None,
            page=1,
            page_size=20,
        )

        resolved = response.items[0].resolved_price
        self.assertIsNotNone(resolved)
        self.assertIsNone(resolved.member_amount)

    def test_get_product_includes_member_price_when_category_discounted(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=10.0)
        product = build_product(category_id="cat-1", amount=10.0)
        repository = StubGroceryRepository(category=category, products=[product])
        service = GroceryService(repository)

        response = service.get_product("product-1")

        price = response.prices[0]
        self.assertEqual(10.0, price.amount)
        self.assertEqual(9.0, price.member_amount)
        self.assertEqual(10.0, price.discount_percent)

    def test_get_product_omits_member_price_when_category_has_no_discount(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=None)
        product = build_product(category_id="cat-1", amount=10.0)
        repository = StubGroceryRepository(category=category, products=[product])
        service = GroceryService(repository)

        response = service.get_product("product-1")

        price = response.prices[0]
        self.assertIsNone(price.member_amount)
        self.assertIsNone(price.discount_percent)

    def test_list_products_by_category_resolves_category_once_for_many_products(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=10.0)
        products = [build_product(product_id=f"product-{i}", category_id="cat-1") for i in range(25)]
        repository = StubGroceryRepository(category=category, products=products)
        service = GroceryService(repository)

        response = service.list_products_by_category(
            category_id="cat-1",
            country=CountryCode.UNITED_KINGDOM,
            culture=None,
            search=None,
            product_tag=None,
            sort=None,
            page=1,
            page_size=25,
        )

        self.assertEqual(25, len(response.items))
        self.assertTrue(all(item.resolved_price.member_amount == 9.0 for item in response.items))
        self.assertEqual(1, len(repository.get_category_calls))

    def test_list_products_resolves_each_distinct_category_once_for_many_products(self) -> None:
        category_a = build_category(category_id="cat-a", discount_percent=10.0)
        category_b = build_category(category_id="cat-b", discount_percent=None)
        products = [
            build_product(product_id=f"product-a-{i}", category_id="cat-a") for i in range(10)
        ] + [
            build_product(product_id=f"product-b-{i}", category_id="cat-b") for i in range(10)
        ]
        repository = StubGroceryRepository(category=category_a, products=products, extra_categories=[category_b])
        service = GroceryService(repository)

        response = service.list_products(
            country=CountryCode.UNITED_KINGDOM,
            culture=None,
            search=None,
            product_tag=None,
            category_id=None,
            sort=None,
            page=1,
            page_size=20,
        )

        self.assertEqual(20, len(response.items))
        self.assertEqual(sorted(["cat-a", "cat-b"]), sorted(set(repository.get_category_calls)))
        self.assertEqual(2, len(repository.get_category_calls))


if __name__ == "__main__":
    unittest.main()
