from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryCategory, GroceryCategorySlug, GroceryProduct
from app.services.inventory_service import InventoryService


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


def build_product(*, category_id: str, amount: float = 10.0) -> GroceryProduct:
    now = utc_now()
    return GroceryProduct(
        id="product-1",
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
    def __init__(self, category: GroceryCategory | None) -> None:
        self._category = category

    def get_category(self, category_id: str) -> GroceryCategory | None:
        if self._category is not None and self._category.id == category_id:
            return self._category
        return None


def build_service(*, category: GroceryCategory | None) -> InventoryService:
    return InventoryService(
        inventory_repository=None,  # type: ignore[arg-type]
        grocery_repository=StubGroceryRepository(category),
        default_store_id="main_store",
    )


class InventoryServiceMemberPricingTests(unittest.TestCase):
    def test_subscriber_gets_discounted_price_when_category_has_discount(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=10.0)
        product = build_product(category_id="cat-1", amount=10.0)
        service = build_service(category=category)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=True)

        self.assertEqual(1000, resolved.base_price_minor)
        self.assertEqual(900, resolved.unit_price_minor)
        self.assertEqual(10.0, resolved.discount_percent_applied)

    def test_non_subscriber_always_pays_base_price(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=10.0)
        product = build_product(category_id="cat-1", amount=10.0)
        service = build_service(category=category)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=False)

        self.assertEqual(1000, resolved.base_price_minor)
        self.assertEqual(1000, resolved.unit_price_minor)
        self.assertEqual(0.0, resolved.discount_percent_applied)

    def test_subscriber_pays_base_price_when_category_has_no_discount_configured(self) -> None:
        category = build_category(category_id="cat-1", discount_percent=None)
        product = build_product(category_id="cat-1", amount=10.0)
        service = build_service(category=category)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=True)

        self.assertEqual(1000, resolved.unit_price_minor)
        self.assertEqual(0.0, resolved.discount_percent_applied)

    def test_subscriber_pays_base_price_when_category_not_found(self) -> None:
        product = build_product(category_id="missing-cat", amount=10.0)
        service = build_service(category=None)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=True)

        self.assertEqual(1000, resolved.unit_price_minor)
        self.assertEqual(0.0, resolved.discount_percent_applied)


if __name__ == "__main__":
    unittest.main()
