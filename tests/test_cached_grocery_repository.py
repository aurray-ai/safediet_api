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


def make_product_document(*, product_id: str = "product-1", discount_id: str | None) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "_id": product_id,
        "category_id": "cat-1",
        "img_url": "",
        "product": "Chicken breast",
        "sort_order": 1,
        "product_tags": [],
        "culture_tags": [],
        "nutritional_specs": [],
        "prices": [],
        "description": "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "discount_id": discount_id,
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

    def test_assign_products_to_discount_invalidates_cached_product_entities(self) -> None:
        base_repository = Mock()
        base_repository._categories = Mock()
        base_repository._products = Mock()
        base_repository._products.find_one.return_value = make_product_document(discount_id=None)
        base_repository.assign_products_to_discount.return_value = 1

        repository = CachedGroceryRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first = repository.get_product("product-1")
        self.assertIsNone(first.discount_id)
        self.assertEqual(1, base_repository._products.find_one.call_count)

        base_repository._products.find_one.return_value = make_product_document(discount_id="disc-1")
        repository.assign_products_to_discount(product_ids=["product-1"], discount_id="disc-1")

        second = repository.get_product("product-1")
        self.assertEqual("disc-1", second.discount_id)
        self.assertEqual(2, base_repository._products.find_one.call_count)

    def test_unassign_products_from_discount_invalidates_cached_product_entities(self) -> None:
        base_repository = Mock()
        base_repository._categories = Mock()
        base_repository._products = Mock()
        base_repository._products.find_one.return_value = make_product_document(discount_id="disc-1")
        base_repository.unassign_products_from_discount.return_value = 1

        repository = CachedGroceryRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first = repository.get_product("product-1")
        self.assertEqual("disc-1", first.discount_id)

        base_repository._products.find_one.return_value = make_product_document(discount_id=None)
        repository.unassign_products_from_discount(product_ids=["product-1"])

        second = repository.get_product("product-1")
        self.assertIsNone(second.discount_id)

    def test_unassign_all_products_from_discount_invalidates_affected_products(self) -> None:
        base_repository = Mock()
        base_repository._categories = Mock()
        base_repository._products = Mock()
        base_repository._products.find_one.return_value = make_product_document(discount_id="disc-1")
        base_repository.unassign_all_products_from_discount.return_value = ["product-1"]

        repository = CachedGroceryRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first = repository.get_product("product-1")
        self.assertEqual("disc-1", first.discount_id)

        base_repository._products.find_one.return_value = make_product_document(discount_id=None)
        affected = repository.unassign_all_products_from_discount(discount_id="disc-1")

        self.assertEqual(["product-1"], affected)
        second = repository.get_product("product-1")
        self.assertIsNone(second.discount_id)


if __name__ == "__main__":
    unittest.main()
