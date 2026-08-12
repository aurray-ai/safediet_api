from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.cache.redis_cache import RedisCache
from app.repositories.cached_discount_repository import CachedDiscountRepository


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


def make_discount(*, discount_id: str = "disc-1", percent: float):
    from datetime import datetime, timezone

    from app.models.grocery import GroceryDiscount

    now = datetime.now(timezone.utc)
    return GroceryDiscount(id=discount_id, label=f"{percent:g}% Off", percent=percent, created_at=now, updated_at=now)


class CachedDiscountRepositoryTests(unittest.TestCase):
    def test_get_discount_caches_and_returns_fresh_value_after_update(self) -> None:
        base_repository = Mock()
        base_repository.get_discount.return_value = make_discount(percent=10.0)
        base_repository.update_discount.return_value = make_discount(percent=15.0)

        repository = CachedDiscountRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first = repository.get_discount("disc-1")
        self.assertEqual(10.0, first.percent)
        self.assertEqual(1, base_repository.get_discount.call_count)

        # Second read within TTL should be served from cache, not hit the base repository again.
        second = repository.get_discount("disc-1")
        self.assertEqual(10.0, second.percent)
        self.assertEqual(1, base_repository.get_discount.call_count)

        repository.update_discount(discount_id="disc-1", label="15% Off", percent=15.0)

        third = repository.get_discount("disc-1")
        self.assertEqual(15.0, third.percent)

    def test_delete_discount_invalidates_cached_entity(self) -> None:
        base_repository = Mock()
        base_repository.get_discount.return_value = make_discount(percent=10.0)
        base_repository.delete_discount.return_value = True

        repository = CachedDiscountRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        repository.get_discount("disc-1")
        self.assertEqual(1, base_repository.get_discount.call_count)

        repository.delete_discount("disc-1")

        base_repository.get_discount.return_value = None
        repository.get_discount("disc-1")
        self.assertEqual(2, base_repository.get_discount.call_count)

    def test_list_discounts_caches_and_invalidates_on_create(self) -> None:
        base_repository = Mock()
        base_repository.list_discounts.return_value = [make_discount(discount_id="disc-1", percent=10.0)]
        base_repository.create_discount.return_value = make_discount(discount_id="disc-2", percent=20.0)
        base_repository.get_discount.side_effect = lambda discount_id: {
            "disc-1": make_discount(discount_id="disc-1", percent=10.0),
            "disc-2": make_discount(discount_id="disc-2", percent=20.0),
        }.get(discount_id)

        repository = CachedDiscountRepository(
            base_repository=base_repository,
            cache=RedisCache(FakeRedisClient()),
            entity_ttl_seconds=3600,
            query_ttl_seconds=600,
        )

        first_list = repository.list_discounts()
        self.assertEqual(1, len(first_list))
        self.assertEqual(1, base_repository.list_discounts.call_count)

        repository.create_discount(discount_id="disc-2", label="20% Off", percent=20.0)

        base_repository.list_discounts.return_value = [
            make_discount(discount_id="disc-1", percent=10.0),
            make_discount(discount_id="disc-2", percent=20.0),
        ]
        second_list = repository.list_discounts()
        self.assertEqual(2, len(second_list))
        self.assertEqual(2, base_repository.list_discounts.call_count)


if __name__ == "__main__":
    unittest.main()
