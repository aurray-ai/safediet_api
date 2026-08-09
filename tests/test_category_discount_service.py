from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.grocery import GroceryCategory, GroceryCategorySlug
from app.services.category_discount_service import CategoryDiscountService, CategoryNotFoundError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_category(*, category_id: str, discount_percent: float | None = None) -> GroceryCategory:
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


class StubGroceryRepository:
    def __init__(self, categories: dict[str, GroceryCategory]) -> None:
        self.categories = dict(categories)

    def list_all_categories(self) -> list[GroceryCategory]:
        return list(self.categories.values())

    def get_any_category(self, category_id: str) -> GroceryCategory | None:
        return self.categories.get(category_id)

    def set_category_discount(self, *, category_id: str, discount_percent: float) -> GroceryCategory | None:
        current = self.categories.get(category_id)
        if current is None:
            return None
        updated = build_category(category_id=category_id, discount_percent=discount_percent)
        self.categories[category_id] = updated
        return updated

    def clear_category_discount(self, *, category_id: str) -> GroceryCategory | None:
        current = self.categories.get(category_id)
        if current is None:
            return None
        updated = build_category(category_id=category_id, discount_percent=None)
        self.categories[category_id] = updated
        return updated


class StubAuditRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, *, category_id, action, previous_percent, new_percent, actor_user_id) -> dict:
        entry = {
            "category_id": category_id,
            "action": action,
            "previous_percent": previous_percent,
            "new_percent": new_percent,
            "actor_user_id": actor_user_id,
            "created_at": utc_now(),
        }
        self.entries.append(entry)
        return entry

    def list_for_category(self, *, category_id: str) -> list[dict]:
        return [entry for entry in self.entries if entry["category_id"] == category_id]


def build_service(*, categories: dict[str, GroceryCategory]):
    grocery_repository = StubGroceryRepository(categories)
    audit_repository = StubAuditRepository()
    service = CategoryDiscountService(grocery_repository=grocery_repository, audit_repository=audit_repository)
    return service, grocery_repository, audit_repository


class CategoryDiscountServiceTests(unittest.TestCase):
    def test_list_discounts_returns_all_categories(self) -> None:
        service, _, _ = build_service(
            categories={"cat-1": build_category(category_id="cat-1", discount_percent=10.0)}
        )

        items = service.list_discounts()

        self.assertEqual(1, len(items))
        self.assertEqual(10.0, items[0].discount_percent)

    def test_set_discount_updates_category_and_logs_audit_entry(self) -> None:
        service, repository, audit = build_service(categories={"cat-1": build_category(category_id="cat-1")})

        updated = service.set_discount(category_id="cat-1", discount_percent=15.0, actor_user_id="admin-1")

        self.assertEqual(15.0, updated.discount_percent)
        self.assertEqual(15.0, repository.categories["cat-1"].discount_percent)
        self.assertEqual(1, len(audit.entries))
        self.assertEqual("discount_set", audit.entries[0]["action"])
        self.assertIsNone(audit.entries[0]["previous_percent"])
        self.assertEqual(15.0, audit.entries[0]["new_percent"])
        self.assertEqual("admin-1", audit.entries[0]["actor_user_id"])

    def test_set_discount_raises_for_missing_category(self) -> None:
        service, _, _ = build_service(categories={})

        with self.assertRaises(CategoryNotFoundError):
            service.set_discount(category_id="missing", discount_percent=10.0, actor_user_id="admin-1")

    def test_reset_discount_clears_override_and_logs_audit_entry(self) -> None:
        service, repository, audit = build_service(
            categories={"cat-1": build_category(category_id="cat-1", discount_percent=20.0)}
        )

        updated = service.reset_discount(category_id="cat-1", actor_user_id="admin-1")

        self.assertIsNone(updated.discount_percent)
        self.assertIsNone(repository.categories["cat-1"].discount_percent)
        self.assertEqual(1, len(audit.entries))
        self.assertEqual("discount_reset", audit.entries[0]["action"])
        self.assertEqual(20.0, audit.entries[0]["previous_percent"])
        self.assertIsNone(audit.entries[0]["new_percent"])

    def test_reset_discount_raises_for_missing_category(self) -> None:
        service, _, _ = build_service(categories={})

        with self.assertRaises(CategoryNotFoundError):
            service.reset_discount(category_id="missing", actor_user_id="admin-1")

    def test_discount_history_reflects_changes_in_order_and_does_not_mutate_past_entries(self) -> None:
        service, _, _ = build_service(categories={"cat-1": build_category(category_id="cat-1")})

        service.set_discount(category_id="cat-1", discount_percent=10.0, actor_user_id="admin-1")
        service.set_discount(category_id="cat-1", discount_percent=20.0, actor_user_id="admin-2")
        service.reset_discount(category_id="cat-1", actor_user_id="admin-1")

        history = service.get_discount_history(category_id="cat-1")

        self.assertEqual(3, len(history))
        # The first change's recorded previous/new values must never be rewritten by later changes.
        first_change = next(entry for entry in history if entry["new_percent"] == 10.0)
        self.assertIsNone(first_change["previous_percent"])
        second_change = next(entry for entry in history if entry["new_percent"] == 20.0)
        self.assertEqual(10.0, second_change["previous_percent"])


if __name__ == "__main__":
    unittest.main()
