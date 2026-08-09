from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from app.cache.redis_cache import RedisCache
from app.repositories.cached_grocery_repository import CachedGroceryRepository


class FakeRedisClient:
    """In-memory stand-in for a redis client, so cache reads/writes/deletes are real."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value: object, ex: int | None = None) -> None:
        self._store[key] = value

    def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)

    def incr(self, key: str) -> int:
        current = int(self._store.get(key, 0)) + 1
        self._store[key] = current
        return current


def make_category_document(*, category_id: str = "cat-1", discount_percent: float | None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "_id": category_id,
        "slug": "protein",
        "name": "Protein",
        "icon_name": "protein",
        "img_url": "",
        "description": "",
        "sort_order": 1,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "discount_percent": discount_percent,
    }


class CachedGroceryRepositoryTests(unittest.TestCase):
    def test_list_products_by_category_forwards_sort_to_base_repository(self) -> None:
        base_repository = Mock()
        base_repository._categories = Mock()
        base_repository._products = Mock()
        base_repository.list_products_by_category.return_value = ([], 0)

        repository = CachedGroceryRepository(
            base_repository=base_repository,
            cache=RedisCache(None),
            entity_ttl_seconds=60,
            query_ttl_seconds=60,
        )

        repository.list_products_by_category(
            category_id="grains_carbs",
            culture_tag=None,
            search=None,
            product_tag=None,
            sort="price_low_to_high",
            page=1,
            page_size=20,
        )

        base_repository.list_products_by_category.assert_called_once_with(
            category_id="grains_carbs",
            culture_tag=None,
            search=None,
            product_tag=None,
            sort="price_low_to_high",
            page=1,
            page_size=20,
        )

    def test_set_category_discount_invalidates_cached_category(self) -> None:
        base_repository = Mock()
        base_repository._categories = Mock()
        base_repository._products = Mock()
        base_repository._categories.find_one.return_value = make_category_document(discount_percent=None)
        base_repository.set_category_discount.return_value = None

        repository = CachedGroceryRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first = repository.get_category("cat-1")
        self.assertIsNone(first.discount_percent)
        self.assertEqual(1, base_repository._categories.find_one.call_count)

        base_repository._categories.find_one.return_value = make_category_document(discount_percent=15.0)
        repository.set_category_discount(category_id="cat-1", discount_percent=15.0)

        second = repository.get_category("cat-1")
        self.assertEqual(15.0, second.discount_percent)
        self.assertEqual(2, base_repository._categories.find_one.call_count)

    def test_clear_category_discount_invalidates_cached_category(self) -> None:
        base_repository = Mock()
        base_repository._categories = Mock()
        base_repository._products = Mock()
        base_repository._categories.find_one.return_value = make_category_document(discount_percent=15.0)
        base_repository.clear_category_discount.return_value = None

        repository = CachedGroceryRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first = repository.get_category("cat-1")
        self.assertEqual(15.0, first.discount_percent)

        base_repository._categories.find_one.return_value = make_category_document(discount_percent=None)
        repository.clear_category_discount(category_id="cat-1")

        second = repository.get_category("cat-1")
        self.assertIsNone(second.discount_percent)
        self.assertEqual(2, base_repository._categories.find_one.call_count)


if __name__ == "__main__":
    unittest.main()
