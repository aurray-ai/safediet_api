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
    GroceryDiscount,
    GroceryProduct,
)
from app.services.grocery_service import GroceryCategoryNotFoundError, GroceryService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_category(*, category_id: str) -> GroceryCategory:
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
    )


def build_discount(*, discount_id: str, percent: float) -> GroceryDiscount:
    now = utc_now()
    return GroceryDiscount(
        id=discount_id,
        label=f"{percent:g}% Off",
        percent=percent,
        created_at=now,
        updated_at=now,
    )


def build_product(
    *,
    product_id: str = "product-1",
    category_id: str,
    amount: float = 10.0,
    discount_id: str | None = None,
) -> GroceryProduct:
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
        discount_id=discount_id,
    )


class StubGroceryRepository:
    def __init__(self, *, categories: list[GroceryCategory], products: list[GroceryProduct]) -> None:
        self._categories = {category.id: category for category in categories}
        self._products = products

    def get_category(self, category_id: str):
        return self._categories.get(category_id)

    def list_products(self, **_kwargs):
        return self._products, len(self._products)

    def list_products_by_category(self, **_kwargs):
        return self._products, len(self._products)

    def get_product(self, product_id: str):
        return next((product for product in self._products if product.id == product_id), None)


class StubDiscountRepository:
    def __init__(self, *, discounts: list[GroceryDiscount]) -> None:
        self._discounts = {discount.id: discount for discount in discounts}
        self.get_discount_calls: list[str] = []

    def get_discount(self, discount_id: str):
        self.get_discount_calls.append(discount_id)
        return self._discounts.get(discount_id)


class GroceryServiceTests(unittest.TestCase):
    def test_list_nutrients_includes_extended_micronutrients(self) -> None:
        service = GroceryService(Mock(), Mock())

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

    def test_list_products_includes_member_price_when_product_discounted(self) -> None:
        category = build_category(category_id="cat-1")
        discount = build_discount(discount_id="disc-1", percent=10.0)
        product = build_product(category_id="cat-1", amount=10.0, discount_id="disc-1")
        repository = StubGroceryRepository(categories=[category], products=[product])
        discount_repository = StubDiscountRepository(discounts=[discount])
        service = GroceryService(repository, discount_repository)

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

    def test_list_products_omits_member_price_when_product_has_no_discount(self) -> None:
        category = build_category(category_id="cat-1")
        product = build_product(category_id="cat-1", amount=10.0, discount_id=None)
        repository = StubGroceryRepository(categories=[category], products=[product])
        discount_repository = StubDiscountRepository(discounts=[])
        service = GroceryService(repository, discount_repository)

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
        self.assertEqual([], discount_repository.get_discount_calls)

    def test_get_product_includes_member_price_when_product_discounted(self) -> None:
        category = build_category(category_id="cat-1")
        discount = build_discount(discount_id="disc-1", percent=10.0)
        product = build_product(category_id="cat-1", amount=10.0, discount_id="disc-1")
        repository = StubGroceryRepository(categories=[category], products=[product])
        discount_repository = StubDiscountRepository(discounts=[discount])
        service = GroceryService(repository, discount_repository)

        response = service.get_product("product-1")

        price = response.prices[0]
        self.assertEqual(10.0, price.amount)
        self.assertEqual(9.0, price.member_amount)
        self.assertEqual(10.0, price.discount_percent)

    def test_get_product_omits_member_price_when_product_has_no_discount(self) -> None:
        category = build_category(category_id="cat-1")
        product = build_product(category_id="cat-1", amount=10.0, discount_id=None)
        repository = StubGroceryRepository(categories=[category], products=[product])
        discount_repository = StubDiscountRepository(discounts=[])
        service = GroceryService(repository, discount_repository)

        response = service.get_product("product-1")

        price = response.prices[0]
        self.assertIsNone(price.member_amount)
        self.assertIsNone(price.discount_percent)

    def test_list_products_by_category_raises_when_category_missing(self) -> None:
        repository = StubGroceryRepository(categories=[], products=[])
        discount_repository = StubDiscountRepository(discounts=[])
        service = GroceryService(repository, discount_repository)

        with self.assertRaises(GroceryCategoryNotFoundError):
            service.list_products_by_category(
                category_id="missing",
                country=CountryCode.UNITED_KINGDOM,
                culture=None,
                search=None,
                product_tag=None,
                sort=None,
                page=1,
                page_size=20,
            )

    def test_list_products_by_category_resolves_each_distinct_discount_once_for_many_products(self) -> None:
        category = build_category(category_id="cat-1")
        discount = build_discount(discount_id="disc-1", percent=10.0)
        products = (
            [
                build_product(product_id=f"product-discounted-{i}", category_id="cat-1", discount_id="disc-1")
                for i in range(15)
            ]
            + [build_product(product_id=f"product-plain-{i}", category_id="cat-1") for i in range(10)]
        )
        repository = StubGroceryRepository(categories=[category], products=products)
        discount_repository = StubDiscountRepository(discounts=[discount])
        service = GroceryService(repository, discount_repository)

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
        discounted_items = [item for item in response.items if item.resolved_price.member_amount is not None]
        plain_items = [item for item in response.items if item.resolved_price.member_amount is None]
        self.assertEqual(15, len(discounted_items))
        self.assertEqual(10, len(plain_items))
        self.assertEqual(1, len(discount_repository.get_discount_calls))

    def test_list_products_resolves_each_distinct_discount_once_for_many_products(self) -> None:
        category = build_category(category_id="cat-1")
        discount_a = build_discount(discount_id="disc-a", percent=10.0)
        discount_b = build_discount(discount_id="disc-b", percent=20.0)
        products = (
            [build_product(product_id=f"product-a-{i}", category_id="cat-1", discount_id="disc-a") for i in range(10)]
            + [build_product(product_id=f"product-b-{i}", category_id="cat-1", discount_id="disc-b") for i in range(10)]
        )
        repository = StubGroceryRepository(categories=[category], products=products)
        discount_repository = StubDiscountRepository(discounts=[discount_a, discount_b])
        service = GroceryService(repository, discount_repository)

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
        self.assertEqual(
            sorted(["disc-a", "disc-b"]), sorted(set(discount_repository.get_discount_calls))
        )
        self.assertEqual(2, len(discount_repository.get_discount_calls))


if __name__ == "__main__":
    unittest.main()
