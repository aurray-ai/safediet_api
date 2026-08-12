from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryDiscount, GroceryProduct
from app.services.inventory_service import InventoryService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_discount(*, discount_id: str, percent: float) -> GroceryDiscount:
    now = utc_now()
    return GroceryDiscount(
        id=discount_id,
        label=f"{percent:g}% Off",
        percent=percent,
        created_at=now,
        updated_at=now,
    )


def build_product(*, category_id: str = "cat-1", amount: float = 10.0, discount_id: str | None) -> GroceryProduct:
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
        discount_id=discount_id,
    )


class StubDiscountRepository:
    def __init__(self, discount: GroceryDiscount | None) -> None:
        self._discount = discount

    def get_discount(self, discount_id: str) -> GroceryDiscount | None:
        if self._discount is not None and self._discount.id == discount_id:
            return self._discount
        return None


def build_service(*, discount: GroceryDiscount | None) -> InventoryService:
    return InventoryService(
        inventory_repository=None,  # type: ignore[arg-type]
        grocery_repository=None,  # type: ignore[arg-type]
        discount_repository=StubDiscountRepository(discount),
        default_store_id="main_store",
    )


class InventoryServiceMemberPricingTests(unittest.TestCase):
    def test_subscriber_gets_discounted_price_when_product_has_discount(self) -> None:
        discount = build_discount(discount_id="disc-1", percent=10.0)
        product = build_product(amount=10.0, discount_id="disc-1")
        service = build_service(discount=discount)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=True)

        self.assertEqual(1000, resolved.base_price_minor)
        self.assertEqual(900, resolved.unit_price_minor)
        self.assertEqual(10.0, resolved.discount_percent_applied)

    def test_non_subscriber_always_pays_base_price(self) -> None:
        discount = build_discount(discount_id="disc-1", percent=10.0)
        product = build_product(amount=10.0, discount_id="disc-1")
        service = build_service(discount=discount)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=False)

        self.assertEqual(1000, resolved.base_price_minor)
        self.assertEqual(1000, resolved.unit_price_minor)
        self.assertEqual(0.0, resolved.discount_percent_applied)

    def test_subscriber_pays_base_price_when_product_has_no_discount(self) -> None:
        product = build_product(amount=10.0, discount_id=None)
        service = build_service(discount=None)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=True)

        self.assertEqual(1000, resolved.unit_price_minor)
        self.assertEqual(0.0, resolved.discount_percent_applied)

    def test_subscriber_pays_base_price_when_discount_not_found(self) -> None:
        product = build_product(amount=10.0, discount_id="missing-disc")
        service = build_service(discount=None)

        resolved = service.resolve_member_unit_price_minor(product=product, currency="GBP", is_subscriber=True)

        self.assertEqual(1000, resolved.unit_price_minor)
        self.assertEqual(0.0, resolved.discount_percent_applied)


if __name__ == "__main__":
    unittest.main()
