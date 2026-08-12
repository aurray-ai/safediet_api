from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryDiscount, GroceryProduct
from app.services.discount_service import DiscountNotFoundError, DiscountService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_product(*, product_id: str, discount_id: str | None = None) -> GroceryProduct:
    now = utc_now()
    return GroceryProduct(
        id=product_id,
        category_id="cat-1",
        img_url="",
        product="Chicken breast",
        product_tags=[],
        culture_tags=[],
        nutritional_specs=[],
        prices=[
            CountryPrice(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=10.0,
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


class FakeDiscountRepository:
    def __init__(self) -> None:
        self.items: dict[str, GroceryDiscount] = {}

    def list_discounts(self) -> list[GroceryDiscount]:
        return list(self.items.values())

    def get_discount(self, discount_id: str) -> GroceryDiscount | None:
        return self.items.get(discount_id)

    def create_discount(self, *, discount_id: str, label: str, percent: float) -> GroceryDiscount:
        now = utc_now()
        discount = GroceryDiscount(id=discount_id, label=label, percent=percent, created_at=now, updated_at=now)
        self.items[discount_id] = discount
        return discount

    def update_discount(self, *, discount_id: str, label: str, percent: float) -> GroceryDiscount | None:
        existing = self.items.get(discount_id)
        if existing is None:
            return None
        updated = GroceryDiscount(
            id=discount_id, label=label, percent=percent, created_at=existing.created_at, updated_at=utc_now()
        )
        self.items[discount_id] = updated
        return updated

    def delete_discount(self, discount_id: str) -> bool:
        return self.items.pop(discount_id, None) is not None


class FakeGroceryRepository:
    def __init__(self, *, products: list[GroceryProduct] | None = None) -> None:
        self.products: dict[str, GroceryProduct] = {product.id: product for product in (products or [])}

    def count_products_by_discount(self, *, discount_id: str) -> int:
        return sum(1 for product in self.products.values() if product.discount_id == discount_id)

    def list_products_by_discount(
        self, *, discount_id: str, page: int, page_size: int, search: str | None = None
    ) -> tuple[list[GroceryProduct], int]:
        matches = [product for product in self.products.values() if product.discount_id == discount_id]
        start = (page - 1) * page_size
        return matches[start : start + page_size], len(matches)

    def assign_products_to_discount(self, *, product_ids: list[str], discount_id: str) -> int:
        modified = 0
        for product_id in product_ids:
            product = self.products.get(product_id)
            if product is None:
                continue
            self.products[product_id] = build_product(product_id=product_id, discount_id=discount_id)
            modified += 1
        return modified

    def unassign_products_from_discount(self, *, product_ids: list[str]) -> int:
        modified = 0
        for product_id in product_ids:
            product = self.products.get(product_id)
            if product is None:
                continue
            self.products[product_id] = build_product(product_id=product_id, discount_id=None)
            modified += 1
        return modified

    def unassign_all_products_from_discount(self, *, discount_id: str) -> list[str]:
        affected = [product_id for product_id, product in self.products.items() if product.discount_id == discount_id]
        for product_id in affected:
            self.products[product_id] = build_product(product_id=product_id, discount_id=None)
        return affected


class FakeDiscountAuditRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, *, discount_id: str, action: str, details: dict, actor_user_id: str) -> dict:
        entry = {
            "discount_id": discount_id,
            "action": action,
            "details": details,
            "actor_user_id": actor_user_id,
            "created_at": utc_now(),
        }
        self.entries.append(entry)
        return entry

    def list_for_discount(self, *, discount_id: str) -> list[dict]:
        return [entry for entry in self.entries if entry["discount_id"] == discount_id]


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, object] = {}

    def find_by_id(self, user_id: str):
        return self.users.get(user_id)


class DiscountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discount_repository = FakeDiscountRepository()
        self.grocery_repository = FakeGroceryRepository()
        self.audit_repository = FakeDiscountAuditRepository()
        self.user_repository = FakeUserRepository()
        self.service = DiscountService(
            discount_repository=self.discount_repository,
            grocery_repository=self.grocery_repository,
            audit_repository=self.audit_repository,
            user_repository=self.user_repository,
        )

    def test_create_discount_writes_audit_entry(self) -> None:
        created = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")

        self.assertEqual("10% Off", created.label)
        self.assertEqual(10.0, created.percent)
        self.assertEqual(1, len(self.audit_repository.entries))
        self.assertEqual("discount_created", self.audit_repository.entries[0]["action"])

    def test_get_discount_raises_when_missing(self) -> None:
        with self.assertRaises(DiscountNotFoundError):
            self.service.get_discount("missing")

    def test_update_discount_writes_audit_entry_with_previous_values(self) -> None:
        created = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")

        updated = self.service.update_discount(
            discount_id=created.id, label="15% Off", percent=15.0, actor_user_id="admin-2"
        )

        self.assertEqual(15.0, updated.percent)
        self.assertEqual(2, len(self.audit_repository.entries))
        update_entry = self.audit_repository.entries[-1]
        self.assertEqual("discount_updated", update_entry["action"])
        self.assertEqual(10.0, update_entry["details"]["previous_percent"])
        self.assertEqual(15.0, update_entry["details"]["percent"])

    def test_assign_products_overwrites_any_previous_discount(self) -> None:
        discount_a = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")
        discount_b = self.service.create_discount(label="20% Off", percent=20.0, actor_user_id="admin-1")
        self.grocery_repository.products["product-1"] = build_product(
            product_id="product-1", discount_id=discount_a.id
        )

        modified = self.service.assign_products(
            discount_id=discount_b.id, product_ids=["product-1"], actor_user_id="admin-1"
        )

        self.assertEqual(1, modified)
        self.assertEqual(discount_b.id, self.grocery_repository.products["product-1"].discount_id)

    def test_assign_products_raises_when_discount_missing(self) -> None:
        with self.assertRaises(DiscountNotFoundError):
            self.service.assign_products(discount_id="missing", product_ids=["product-1"], actor_user_id="admin-1")

    def test_unassign_products_clears_discount_id(self) -> None:
        discount = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")
        self.grocery_repository.products["product-1"] = build_product(product_id="product-1", discount_id=discount.id)

        modified = self.service.unassign_products(
            discount_id=discount.id, product_ids=["product-1"], actor_user_id="admin-1"
        )

        self.assertEqual(1, modified)
        self.assertIsNone(self.grocery_repository.products["product-1"].discount_id)

    def test_delete_discount_unassigns_all_tied_products_and_removes_discount(self) -> None:
        discount = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")
        self.grocery_repository.products["product-1"] = build_product(product_id="product-1", discount_id=discount.id)
        self.grocery_repository.products["product-2"] = build_product(product_id="product-2", discount_id=discount.id)

        self.service.delete_discount(discount_id=discount.id, actor_user_id="admin-1")

        self.assertIsNone(self.grocery_repository.products["product-1"].discount_id)
        self.assertIsNone(self.grocery_repository.products["product-2"].discount_id)
        with self.assertRaises(DiscountNotFoundError):
            self.service.get_discount(discount.id)
        delete_entry = self.audit_repository.entries[-1]
        self.assertEqual("discount_deleted", delete_entry["action"])
        self.assertEqual(2, delete_entry["details"]["unassigned_product_count"])

    def test_list_discounts_includes_product_count(self) -> None:
        discount = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")
        self.grocery_repository.products["product-1"] = build_product(product_id="product-1", discount_id=discount.id)
        self.grocery_repository.products["product-2"] = build_product(product_id="product-2", discount_id=discount.id)
        self.grocery_repository.products["product-3"] = build_product(product_id="product-3", discount_id=None)

        pairs = self.service.list_discounts()

        self.assertEqual(1, len(pairs))
        _, count = pairs[0]
        self.assertEqual(2, count)

    def test_get_audit_log_resolves_actor_name(self) -> None:
        from types import SimpleNamespace

        discount = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="admin-1")
        self.user_repository.users["admin-1"] = SimpleNamespace(name="Favour Emmanuel")

        entries = self.service.get_audit_log(discount_id=discount.id)

        self.assertEqual(1, len(entries))
        self.assertEqual("Favour Emmanuel", entries[0]["actor_name"])

    def test_get_audit_log_falls_back_when_actor_not_found(self) -> None:
        discount = self.service.create_discount(label="10% Off", percent=10.0, actor_user_id="missing-admin")

        entries = self.service.get_audit_log(discount_id=discount.id)

        self.assertEqual("Unknown admin", entries[0]["actor_name"])


if __name__ == "__main__":
    unittest.main()
