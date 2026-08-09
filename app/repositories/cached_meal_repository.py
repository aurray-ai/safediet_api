from __future__ import annotations

from typing import Any

from app.cache.cache_keys import meal, meal_categories, meal_category, meal_list_query, meal_query_version
from app.cache.redis_cache import RedisCache
from app.models.grocery import CountryCode
from app.models.meal import Meal, MealCategory, MealType
from app.repositories.meal_repository import MealRepository


class CachedMealRepository(MealRepository):
    def __init__(
        self,
        base_repository: MealRepository,
        cache: RedisCache,
        *,
        entity_ttl_seconds: int,
        query_ttl_seconds: int,
    ) -> None:
        super().__init__(base_repository._categories, base_repository._meals)
        self._base_repository = base_repository
        self._cache = cache
        self._entity_ttl_seconds = entity_ttl_seconds
        self._query_ttl_seconds = query_ttl_seconds

    def list_categories(self) -> list[MealCategory]:
        cache_key = meal_categories()
        cached_ids = self._cache.get_json(cache_key)
        if isinstance(cached_ids, list):
            self._cache.record_hit("meal_categories", cache_key)
            categories = [self.get_category(str(category_id)) for category_id in cached_ids]
            return [category for category in categories if category is not None]

        self._cache.record_miss("meal_categories", cache_key)
        categories = self._base_repository.list_categories()
        self._cache.set_json(
            cache_key,
            [category.id for category in categories],
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("meal_categories", cache_key)
        return categories

    def get_category(self, category_id: str) -> MealCategory | None:
        cache_key = meal_category(category_id)
        cached_document = self._cache.get_json(cache_key)
        if isinstance(cached_document, dict):
            self._cache.record_hit("meal_category", cache_key)
            return self._to_category_model(cached_document)

        self._cache.record_miss("meal_category", cache_key)
        document = self._categories.find_one({"_id": category_id, "is_active": True})
        if document is None:
            return None
        self._cache.set_json(cache_key, document, ttl_seconds=self._entity_ttl_seconds)
        self._cache.record_fill("meal_category", cache_key)
        return self._to_category_model(document)

    def list_meals(
        self,
        *,
        meal_type: MealType | None,
        category_id: str | None,
        culture: str | None,
        dietary: list[str] | None = None,
        nutrition_focus: list[str] | None = None,
        cook_time_max: int | None = None,
        budget_tier: str | None = None,
        country: CountryCode | None = None,
        search: str | None,
        sort: str | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[Meal], int]:
        filters = {
            "meal_type": meal_type.value if meal_type is not None else None,
            "category_id": category_id,
            "culture": culture,
            "dietary": sorted(dietary) if dietary else None,
            "nutrition_focus": sorted(nutrition_focus) if nutrition_focus else None,
            "cook_time_max": cook_time_max,
            "budget_tier": budget_tier,
            "country": country.value if country is not None else None,
            "sort": sort,
            "search": search.strip() if search else None,
            "page": page,
            "page_size": page_size,
        }
        version = self._cache.get_int(meal_query_version(), default=0)
        cache_key = meal_list_query(filters, version=version)
        cached_payload = self._cache.get_json(cache_key)
        if isinstance(cached_payload, dict):
            self._cache.record_hit("meal_list", cache_key)
            meal_ids = [str(meal_id) for meal_id in cached_payload.get("meal_ids", [])]
            meals = [self.get_meal(meal_id) for meal_id in meal_ids]
            return [item for item in meals if item is not None], int(cached_payload.get("total", 0))

        self._cache.record_miss("meal_list", cache_key)
        meals, total = self._base_repository.list_meals(
            meal_type=meal_type,
            category_id=category_id,
            culture=culture,
            dietary=dietary,
            nutrition_focus=nutrition_focus,
            cook_time_max=cook_time_max,
            budget_tier=budget_tier,
            country=country,
            sort=sort,
            search=search,
            page=page,
            page_size=page_size,
        )
        self._cache.set_json(
            cache_key,
            {
                "meal_ids": [item.id for item in meals],
                "total": total,
            },
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("meal_list", cache_key)
        return meals, total

    def get_meal(self, meal_id: str) -> Meal | None:
        return self._get_meal_document(meal_id, include_inactive=False)

    def get_meal_by_id(self, meal_id: str) -> Meal | None:
        return self._get_meal_document(meal_id, include_inactive=True)

    def list_all_meals(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        meal_type: MealType | None = None,
        category_id: str | None = None,
    ) -> tuple[list[Meal], int]:
        filters = {
            "admin": True,
            "page": page,
            "page_size": page_size,
            "search": search.strip() if search else None,
            "meal_type": meal_type.value if meal_type is not None else None,
            "category_id": category_id,
        }
        version = self._cache.get_int(meal_query_version(), default=0)
        cache_key = meal_list_query(filters, version=version)
        cached_payload = self._cache.get_json(cache_key)
        if isinstance(cached_payload, dict):
            self._cache.record_hit("meal_list_admin", cache_key)
            meal_ids = [str(meal_id) for meal_id in cached_payload.get("meal_ids", [])]
            meals = [self.get_meal_by_id(meal_id) for meal_id in meal_ids]
            return [item for item in meals if item is not None], int(cached_payload.get("total", 0))

        self._cache.record_miss("meal_list_admin", cache_key)
        meals, total = self._base_repository.list_all_meals(
            page=page,
            page_size=page_size,
            search=search,
            meal_type=meal_type,
            category_id=category_id,
        )
        self._cache.set_json(
            cache_key,
            {
                "meal_ids": [item.id for item in meals],
                "total": total,
            },
            ttl_seconds=self._query_ttl_seconds,
        )
        self._cache.record_fill("meal_list_admin", cache_key)
        return meals, total

    def get_meal_search_candidate_by_id(self, meal_id: str):
        return self._base_repository.get_meal_search_candidate_by_id(meal_id)

    def create_meal(self, **kwargs: Any) -> Meal:
        created = self._base_repository.create_meal(**kwargs)
        self._cache_meal_document(created.id, include_inactive=False)
        self._cache_meal_document(created.id, include_inactive=True)
        self._invalidate_query_caches()
        return created

    def update_meal(self, **kwargs: Any) -> Meal | None:
        meal_id = str(kwargs["meal_id"])
        updated = self._base_repository.update_meal(**kwargs)
        self._cache.delete_many(
            meal(meal_id, include_inactive=False),
            meal(meal_id, include_inactive=True),
        )
        self._invalidate_query_caches()
        if updated is not None:
            self._cache_meal_document(updated.id, include_inactive=False)
            self._cache_meal_document(updated.id, include_inactive=True)
        return updated

    def update_meal_search_embedding(
        self,
        *,
        meal_id: str,
        search_document: str,
        search_embedding: list[float],
        embedding_model: str,
    ) -> None:
        self._base_repository.update_meal_search_embedding(
            meal_id=meal_id,
            search_document=search_document,
            search_embedding=search_embedding,
            embedding_model=embedding_model,
        )
        self._cache.delete_many(
            meal(meal_id, include_inactive=False),
            meal(meal_id, include_inactive=True),
        )

    def _get_meal_document(self, meal_id: str, *, include_inactive: bool) -> Meal | None:
        cache_key = meal(meal_id, include_inactive=include_inactive)
        cached_document = self._cache.get_json(cache_key)
        if isinstance(cached_document, dict):
            self._cache.record_hit("meal_entity", cache_key)
            return self._to_meal_model(cached_document)

        self._cache.record_miss("meal_entity", cache_key)
        query: dict[str, Any] = {"_id": meal_id}
        if not include_inactive:
            query["is_active"] = True
        document = self._meals.find_one(query)
        if document is None:
            return None
        self._cache.set_json(cache_key, document, ttl_seconds=self._entity_ttl_seconds)
        self._cache.record_fill("meal_entity", cache_key)
        return self._to_meal_model(document)

    def _cache_meal_document(self, meal_id: str, *, include_inactive: bool) -> None:
        query: dict[str, Any] = {"_id": meal_id}
        if not include_inactive:
            query["is_active"] = True
        document = self._meals.find_one(query)
        if document is None:
            return
        self._cache.set_json(
            meal(meal_id, include_inactive=include_inactive),
            document,
            ttl_seconds=self._entity_ttl_seconds,
        )

    def _invalidate_query_caches(self) -> None:
        self._cache.delete_many(meal_categories())
        self._cache.increment(meal_query_version())
