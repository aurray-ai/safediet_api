from __future__ import annotations

from typing import Any

from app.cache.cache_keys import (
    grocery_categories,
    grocery_category,
    grocery_list_query,
    grocery_product,
    grocery_query_version,
)
from app.cache.redis_cache import RedisCache
from app.models.grocery import CultureTag, GroceryCategory, GroceryProduct
from app.repositories.grocery_repository import GroceryRepository


class CachedGroceryRepository(GroceryRepository):
    def __init__(
        self,
        base_repository: GroceryRepository,
        cache: RedisCache,
        *,
        entity_ttl_seconds: int,
        query_ttl_seconds: int,
    ) -> None:
        super().__init__(base_repository._categories, base_repository._products)
        self._base_repository = base_repository
        self._cache = cache
        self._entity_ttl_seconds = entity_ttl_seconds
        self._query_ttl_seconds = query_ttl_seconds

    def list_categories(self) -> list[GroceryCategory]:
        return self._list_categories(include_inactive=False)

    def list_all_categories(self) -> list[GroceryCategory]:
        return self._list_categories(include_inactive=True)

    def get_category(self, category_id: str) -> GroceryCategory | None:
        cache_key = grocery_category(category_id)
        cached_document = self._cache.get_json(cache_key)
        if isinstance(cached_document, dict):
            self._cache.record_hit("grocery_category", cache_key)
            return self._to_category_model(cached_document)

        self._cache.record_miss("grocery_category", cache_key)
        document = self._categories.find_one({"_id": category_id, "is_active": True})
        if document is None:
            return None
        self._cache.set_json(cache_key, document, ttl_seconds=self._entity_ttl_seconds)
        self._cache.record_fill("grocery_category", cache_key)
        return self._to_category_model(document)

    def list_products_by_category(
        self,
        *,
        category_id: str,
        culture_tag: CultureTag | None,
        search: str | None,
        product_tag: str | None,
        sort: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[GroceryProduct], int]:
        filters = {
            "public": True,
            "category_id": category_id,
            "culture_tag": culture_tag.value if culture_tag is not None else None,
            "search": search.strip() if search else None,
            "product_tag": product_tag.strip().lower() if product_tag else None,
            "sort": sort.strip().lower() if sort else None,
            "page": page,
            "page_size": page_size,
        }
        version = self._cache.get_int(grocery_query_version(), default=0)
        cache_key = grocery_list_query(filters, version=version)
        cached_payload = self._cache.get_json(cache_key)
        if isinstance(cached_payload, dict):
            self._cache.record_hit("grocery_list_public", cache_key)
            product_ids = [str(product_id) for product_id in cached_payload.get("product_ids", [])]
            products = [self.get_product(product_id) for product_id in product_ids]
            return [product for product in products if product is not None], int(cached_payload.get("total", 0))

        self._cache.record_miss("grocery_list_public", cache_key)
        products, total = self._base_repository.list_products_by_category(
            category_id=category_id,
            culture_tag=culture_tag,
            search=search,
            product_tag=product_tag,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        self._cache.set_json(
            cache_key,
            {
                "product_ids": [product.id for product in products],
                "total": total,
            },
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("grocery_list_public", cache_key)
        return products, total

    def list_products(
        self,
        *,
        culture_tag: CultureTag | None,
        search: str | None,
        product_tag: str | None,
        category_id: str | None,
        sort: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[GroceryProduct], int]:
        filters = {
            "public": True,
            "category_id": category_id,
            "culture_tag": culture_tag.value if culture_tag is not None else None,
            "search": search.strip() if search else None,
            "product_tag": product_tag.strip().lower() if product_tag else None,
            "sort": sort.strip().lower() if sort else None,
            "page": page,
            "page_size": page_size,
            "storefront": True,
        }
        version = self._cache.get_int(grocery_query_version(), default=0)
        cache_key = grocery_list_query(filters, version=version)
        cached_payload = self._cache.get_json(cache_key)
        if isinstance(cached_payload, dict):
            self._cache.record_hit("grocery_list_public", cache_key)
            product_ids = [str(product_id) for product_id in cached_payload.get("product_ids", [])]
            products = [self.get_product(product_id) for product_id in product_ids]
            return [product for product in products if product is not None], int(cached_payload.get("total", 0))

        self._cache.record_miss("grocery_list_public", cache_key)
        products, total = self._base_repository.list_products(
            culture_tag=culture_tag,
            search=search,
            product_tag=product_tag,
            category_id=category_id,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        self._cache.set_json(
            cache_key,
            {
                "product_ids": [product.id for product in products],
                "total": total,
            },
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("grocery_list_public", cache_key)
        return products, total

    def get_product(self, product_id: str) -> GroceryProduct | None:
        return self._get_product_document(product_id, include_inactive=False)

    def get_product_by_id(self, product_id: str) -> GroceryProduct | None:
        return self._get_product_document(product_id, include_inactive=True)

    def list_products_by_ids(self, product_ids: list[str]) -> list[GroceryProduct]:
        if not product_ids:
            return []
        products = [self.get_product(product_id) for product_id in product_ids]
        return [product for product in products if product is not None]

    def list_all_products(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        category_id: str | None = None,
    ) -> tuple[list[GroceryProduct], int]:
        filters = {
            "admin": True,
            "page": page,
            "page_size": page_size,
            "search": search.strip() if search else None,
            "category_id": category_id,
        }
        version = self._cache.get_int(grocery_query_version(), default=0)
        cache_key = grocery_list_query(filters, version=version)
        cached_payload = self._cache.get_json(cache_key)
        if isinstance(cached_payload, dict):
            self._cache.record_hit("grocery_list_admin", cache_key)
            product_ids = [str(product_id) for product_id in cached_payload.get("product_ids", [])]
            products = [self.get_product_by_id(product_id) for product_id in product_ids]
            return [product for product in products if product is not None], int(cached_payload.get("total", 0))

        self._cache.record_miss("grocery_list_admin", cache_key)
        products, total = self._base_repository.list_all_products(
            page=page,
            page_size=page_size,
            search=search,
            category_id=category_id,
        )
        self._cache.set_json(
            cache_key,
            {
                "product_ids": [product.id for product in products],
                "total": total,
            },
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("grocery_list_admin", cache_key)
        return products, total

    def create_product(self, **kwargs: Any) -> GroceryProduct:
        created = self._base_repository.create_product(**kwargs)
        self._cache_product_document(created.id, include_inactive=False)
        self._cache_product_document(created.id, include_inactive=True)
        self._invalidate_query_caches()
        return created

    def update_product(self, **kwargs: Any) -> GroceryProduct | None:
        product_id = str(kwargs["product_id"])
        updated = self._base_repository.update_product(**kwargs)
        self._cache.delete_many(
            grocery_product(product_id, include_inactive=False),
            grocery_product(product_id, include_inactive=True),
        )
        self._invalidate_query_caches()
        if updated is not None:
            self._cache_product_document(updated.id, include_inactive=False)
            self._cache_product_document(updated.id, include_inactive=True)
        return updated

    def delete_product(self, product_id: str) -> bool:
        deleted = self._base_repository.delete_product(product_id)
        self._cache.delete_many(
            grocery_product(product_id, include_inactive=False),
            grocery_product(product_id, include_inactive=True),
        )
        self._invalidate_query_caches()
        return deleted

    def delete_products(self, product_ids: list[str]) -> int:
        deleted = self._base_repository.delete_products(product_ids)
        cache_keys: list[str] = []
        for product_id in product_ids:
            cache_keys.append(grocery_product(product_id, include_inactive=False))
            cache_keys.append(grocery_product(product_id, include_inactive=True))
        self._cache.delete_many(*cache_keys)
        self._invalidate_query_caches()
        return deleted

    def assign_products_to_discount(self, *, product_ids: list[str], discount_id: str) -> int:
        modified = self._base_repository.assign_products_to_discount(
            product_ids=product_ids, discount_id=discount_id
        )
        self._invalidate_product_entity_caches(product_ids)
        return modified

    def unassign_products_from_discount(self, *, product_ids: list[str]) -> int:
        modified = self._base_repository.unassign_products_from_discount(product_ids=product_ids)
        self._invalidate_product_entity_caches(product_ids)
        return modified

    def unassign_all_products_from_discount(self, *, discount_id: str) -> list[str]:
        product_ids = self._base_repository.unassign_all_products_from_discount(discount_id=discount_id)
        self._invalidate_product_entity_caches(product_ids)
        return product_ids

    def list_products_by_discount(
        self,
        *,
        discount_id: str,
        page: int,
        page_size: int,
        search: str | None = None,
    ) -> tuple[list[GroceryProduct], int]:
        return self._base_repository.list_products_by_discount(
            discount_id=discount_id, page=page, page_size=page_size, search=search
        )

    def count_products_by_discount(self, *, discount_id: str) -> int:
        return self._base_repository.count_products_by_discount(discount_id=discount_id)

    def _invalidate_product_entity_caches(self, product_ids: list[str]) -> None:
        if not product_ids:
            return
        cache_keys: list[str] = []
        for product_id in product_ids:
            cache_keys.append(grocery_product(product_id, include_inactive=False))
            cache_keys.append(grocery_product(product_id, include_inactive=True))
        self._cache.delete_many(*cache_keys)

    def _list_categories(self, *, include_inactive: bool) -> list[GroceryCategory]:
        cache_key = grocery_categories(include_inactive=include_inactive)
        cached_ids = self._cache.get_json(cache_key)
        if isinstance(cached_ids, list):
            self._cache.record_hit("grocery_categories", cache_key)
            categories = []
            for category_id in cached_ids:
                if include_inactive:
                    document = self._categories.find_one({"_id": str(category_id)})
                    if document is not None:
                        categories.append(self._to_category_model(document))
                else:
                    category = self.get_category(str(category_id))
                    if category is not None:
                        categories.append(category)
            return categories

        self._cache.record_miss("grocery_categories", cache_key)
        categories = (
            self._base_repository.list_all_categories()
            if include_inactive
            else self._base_repository.list_categories()
        )
        self._cache.set_json(
            cache_key,
            [category.id for category in categories],
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("grocery_categories", cache_key)
        return categories

    def _get_product_document(self, product_id: str, *, include_inactive: bool) -> GroceryProduct | None:
        cache_key = grocery_product(product_id, include_inactive=include_inactive)
        cached_document = self._cache.get_json(cache_key)
        if isinstance(cached_document, dict):
            self._cache.record_hit("grocery_entity", cache_key)
            return self._to_product_model(cached_document)

        self._cache.record_miss("grocery_entity", cache_key)
        query: dict[str, Any] = {"_id": product_id}
        if not include_inactive:
            query["is_active"] = True
        document = self._products.find_one(query)
        if document is None:
            return None
        self._cache.set_json(cache_key, document, ttl_seconds=self._entity_ttl_seconds)
        self._cache.record_fill("grocery_entity", cache_key)
        return self._to_product_model(document)

    def _cache_product_document(self, product_id: str, *, include_inactive: bool) -> None:
        query: dict[str, Any] = {"_id": product_id}
        if not include_inactive:
            query["is_active"] = True
        document = self._products.find_one(query)
        if document is None:
            return
        self._cache.set_json(
            grocery_product(product_id, include_inactive=include_inactive),
            document,
            ttl_seconds=self._entity_ttl_seconds,
        )

    def _invalidate_query_caches(self) -> None:
        self._cache.delete_many(
            grocery_categories(include_inactive=False),
            grocery_categories(include_inactive=True),
        )
        self._cache.increment(grocery_query_version())
