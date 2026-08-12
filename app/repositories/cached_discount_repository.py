from __future__ import annotations

from app.cache.cache_keys import grocery_discount, grocery_discounts
from app.cache.redis_cache import RedisCache
from app.models.grocery import GroceryDiscount
from app.repositories.discount_repository import DiscountRepository


class CachedDiscountRepository(DiscountRepository):
    def __init__(
        self,
        *,
        base_repository: DiscountRepository,
        cache: RedisCache,
        entity_ttl_seconds: int,
        query_ttl_seconds: int,
    ) -> None:
        self._base_repository = base_repository
        self._cache = cache
        self._entity_ttl_seconds = entity_ttl_seconds
        self._query_ttl_seconds = query_ttl_seconds

    def list_discounts(self) -> list[GroceryDiscount]:
        cache_key = grocery_discounts()
        cached_ids = self._cache.get_json(cache_key)
        if isinstance(cached_ids, list):
            self._cache.record_hit("grocery_discounts", cache_key)
            discounts = []
            for discount_id in cached_ids:
                discount = self.get_discount(str(discount_id))
                if discount is not None:
                    discounts.append(discount)
            return discounts

        self._cache.record_miss("grocery_discounts", cache_key)
        discounts = self._base_repository.list_discounts()
        self._cache.set_json(
            cache_key,
            [discount.id for discount in discounts],
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("grocery_discounts", cache_key)
        return discounts

    def get_discount(self, discount_id: str) -> GroceryDiscount | None:
        cache_key = grocery_discount(discount_id)
        cached_document = self._cache.get_json(cache_key)
        if isinstance(cached_document, dict):
            self._cache.record_hit("grocery_discount", cache_key)
            return self._to_discount_model(cached_document)

        self._cache.record_miss("grocery_discount", cache_key)
        discount = self._base_repository.get_discount(discount_id)
        if discount is None:
            return None
        self._cache_discount(discount)
        self._cache.record_fill("grocery_discount", cache_key)
        return discount

    def create_discount(self, *, discount_id: str, label: str, percent: float) -> GroceryDiscount:
        created = self._base_repository.create_discount(discount_id=discount_id, label=label, percent=percent)
        self._cache_discount(created)
        self._invalidate_list_cache()
        return created

    def update_discount(self, *, discount_id: str, label: str, percent: float) -> GroceryDiscount | None:
        updated = self._base_repository.update_discount(discount_id=discount_id, label=label, percent=percent)
        self._cache.delete_many(grocery_discount(discount_id))
        if updated is not None:
            self._cache_discount(updated)
        self._invalidate_list_cache()
        return updated

    def delete_discount(self, discount_id: str) -> bool:
        deleted = self._base_repository.delete_discount(discount_id)
        self._cache.delete_many(grocery_discount(discount_id))
        self._invalidate_list_cache()
        return deleted

    def _cache_discount(self, discount: GroceryDiscount) -> None:
        self._cache.set_json(
            grocery_discount(discount.id),
            {
                "_id": discount.id,
                "label": discount.label,
                "percent": discount.percent,
                "created_at": discount.created_at,
                "updated_at": discount.updated_at,
            },
            ttl_seconds=self._entity_ttl_seconds,
        )

    def _invalidate_list_cache(self) -> None:
        self._cache.delete_many(grocery_discounts())
