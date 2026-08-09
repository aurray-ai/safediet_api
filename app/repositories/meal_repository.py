from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.data.meal_seed import MEAL_CATEGORY_SEEDS, MEAL_SEEDS
from app.models.grocery import CountryCode, CurrencyCode, NutritionSpec, NutrientType, NutrientUnit
from app.models.measurement import MeasurementType, RoundingRule, ScalingBehavior
from app.models.meal import (
    Meal,
    MealCategory,
    MealCategorySlug,
    MealDifficulty,
    MealEstimatedCost,
    MealHighlightTag,
    MealIngredient,
    MealNutritionSummary,
    MealRecipeStep,
    MealSellingPrice,
    MealType,
)
from app.services.measurement_service import MeasurementService


@dataclass(frozen=True, slots=True)
class MealSearchCandidate:
    meal: Meal
    search_document: str
    search_document_hash: str
    search_embedding: tuple[float, ...] | None
    search_embedding_model: str | None
    search_embedding_source_hash: str | None
    search_embedding_updated_at: datetime | None


class MealRepository:
    def __init__(
        self,
        categories_collection: Collection[dict[str, Any]],
        meals_collection: Collection[dict[str, Any]],
    ) -> None:
        self._categories = categories_collection
        self._meals = meals_collection

    def ensure_seed_data(self) -> None:
        now = datetime.now(timezone.utc)

        for category in MEAL_CATEGORY_SEEDS:
            category_id = str(category["id"])
            payload = {
                "slug": category["slug"],
                "name": category["name"],
                "description": category["description"],
                "img_url": category["img_url"],
                "sort_order": category["sort_order"],
                "is_active": category["is_active"],
                "updated_at": now,
            }
            self._categories.update_one(
                {"_id": category_id},
                {"$set": payload, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )

        # Meal seeding is temporarily disabled. Category seeding above remains active.
        # for meal in MEAL_SEEDS:
        #     meal_id = str(meal["id"])
        #     search_document_payload = {key: value for key, value in meal.items() if key not in {"id"}}
        #     search_document = self._build_search_document(search_document_payload)
        #     search_document_hash = self._hash_search_document(search_document)
        #     existing = self._meals.find_one(
        #         {"_id": meal_id},
        #         {
        #             "search_document_hash": 1,
        #             "search_embedding": 1,
        #             "search_embedding_model": 1,
        #             "search_embedding_source_hash": 1,
        #             "search_embedding_updated_at": 1,
        #         },
        #     )
        #     payload = {
        #         **search_document_payload,
        #         "search_document": search_document,
        #         "search_document_hash": search_document_hash,
        #         "updated_at": now,
        #     }
        #     if (
        #         existing is None
        #         or str(existing.get("search_document_hash") or "").strip() != search_document_hash
        #     ):
        #         payload.update(
        #             {
        #                 "search_embedding": None,
        #                 "search_embedding_model": None,
        #                 "search_embedding_source_hash": None,
        #                 "search_embedding_updated_at": None,
        #             }
        #         )
        #     self._meals.update_one(
        #         {"_id": meal_id},
        #         {"$set": payload, "$setOnInsert": {"created_at": now}},
        #         upsert=True,
        #     )

    def list_categories(self) -> list[MealCategory]:
        documents = self._categories.find({"is_active": True}).sort("sort_order", ASCENDING)
        return [self._to_category_model(document) for document in documents]

    def get_category(self, category_id: str) -> MealCategory | None:
        document = self._categories.find_one({"_id": category_id, "is_active": True})
        return None if document is None else self._to_category_model(document)

    _BUDGET_TIER_BOUNDS: dict[str, tuple[int, int]] = {
        "$": (0, 500),
        "$$": (501, 1000),
        "$$$": (1001, 1500),
        "$$$$": (1501, 10**9),
    }

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
        query: dict[str, Any] = {"is_active": True}

        if meal_type is not None:
            self._append_and_clause(
                query,
                {
                    "$or": [
                        {"meal_type": meal_type.value},
                        {"meal_types": meal_type.value},
                    ]
                },
            )
        if category_id:
            query["category_ids"] = category_id
        if culture:
            query["culture_tags"] = culture
        if dietary:
            query["diet_rules_supported"] = {"$all": dietary}
        if nutrition_focus:
            query["highlight_tags"] = {"$in": nutrition_focus}
        if cook_time_max is not None:
            self._append_and_clause(query, {"cook_time_minutes": {"$lte": cook_time_max}})
        if budget_tier and country is not None:
            low, high = self._BUDGET_TIER_BOUNDS.get(budget_tier, (0, 10**9))
            self._append_and_clause(
                query,
                {
                    "selling_prices": {
                        "$elemMatch": {
                            "country_code": country.value,
                            "amount_minor": {"$gte": low, "$lte": high},
                        }
                    }
                },
            )
        if search:
            normalized = search.strip()
            self._append_and_clause(
                query,
                {
                    "$or": [
                        {"name": {"$regex": normalized, "$options": "i"}},
                        {"description": {"$regex": normalized, "$options": "i"}},
                    ]
                },
            )

        total = self._meals.count_documents(query)

        if sort in {"price_low_high", "price_high_low"} and country is not None:
            documents = self._list_meals_sorted_by_price(
                query=query,
                country=country,
                descending=sort == "price_high_low",
                page=page,
                page_size=page_size,
            )
        else:
            documents = (
                self._meals.find(query)
                .sort(self._sort_spec(sort))
                .skip((page - 1) * page_size)
                .limit(page_size)
            )
        return [self._to_meal_model(document) for document in documents], total

    def _list_meals_sorted_by_price(
        self,
        *,
        query: dict[str, Any],
        country: CountryCode,
        descending: bool,
        page: int,
        page_size: int,
    ) -> list[dict[str, Any]]:
        pipeline = [
            {"$match": query},
            {
                "$addFields": {
                    "_sort_price": {
                        "$let": {
                            "vars": {
                                "matched": {
                                    "$first": {
                                        "$filter": {
                                            "input": "$selling_prices",
                                            "as": "price",
                                            "cond": {"$eq": ["$$price.country_code", country.value]},
                                        }
                                    }
                                }
                            },
                            "in": "$$matched.amount_minor",
                        }
                    }
                }
            },
            {"$sort": {"_sort_price": DESCENDING if descending else ASCENDING, "name": ASCENDING}},
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
        ]
        return list(self._meals.aggregate(pipeline))

    @staticmethod
    def _sort_spec(sort: str | None) -> list[tuple[str, int]]:
        if sort == "popular":
            return [("rating_count", DESCENDING), ("name", ASCENDING)]
        if sort == "rating":
            return [("rating_average", DESCENDING), ("name", ASCENDING)]
        if sort == "quickest":
            return [("cook_time_minutes", ASCENDING), ("name", ASCENDING)]
        return [("meal_type", ASCENDING), ("name", ASCENDING)]

    def list_semantic_search_candidates(
        self,
        *,
        meal_type: MealType | None,
        limit: int,
    ) -> list[MealSearchCandidate]:
        query: dict[str, Any] = {"is_active": True}
        if meal_type is not None:
            self._append_and_clause(
                query,
                {
                    "$or": [
                        {"meal_type": meal_type.value},
                        {"meal_types": meal_type.value},
                    ]
                },
            )

        documents = (
            self._meals.find(query)
            .sort([("updated_at", DESCENDING), ("name", ASCENDING)])
            .limit(max(limit, 1))
        )
        return [self._to_search_candidate(document) for document in documents]

    def get_meal_search_candidate_by_id(self, meal_id: str) -> MealSearchCandidate | None:
        document = self._meals.find_one({"_id": meal_id})
        return None if document is None else self._to_search_candidate(document)

    def update_meal_search_embedding(
        self,
        *,
        meal_id: str,
        search_document: str,
        search_embedding: list[float],
        embedding_model: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._meals.update_one(
            {"_id": meal_id},
            {
                "$set": {
                    "search_document": search_document,
                    "search_document_hash": self._hash_search_document(search_document),
                    "search_embedding": list(search_embedding),
                    "search_embedding_model": embedding_model,
                    "search_embedding_source_hash": self._hash_search_document(search_document),
                    "search_embedding_updated_at": now,
                }
            },
        )

    def get_meal(self, meal_id: str) -> Meal | None:
        document = self._meals.find_one({"_id": meal_id, "is_active": True})
        return None if document is None else self._to_meal_model(document)

    def get_meal_by_id(self, meal_id: str) -> Meal | None:
        document = self._meals.find_one({"_id": meal_id})
        return None if document is None else self._to_meal_model(document)

    def list_all_meals(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        meal_type: MealType | None = None,
        category_id: str | None = None,
    ) -> tuple[list[Meal], int]:
        query: dict[str, Any] = {}

        if meal_type is not None:
            self._append_and_clause(
                query,
                {
                    "$or": [
                        {"meal_type": meal_type.value},
                        {"meal_types": meal_type.value},
                    ]
                },
            )
        if category_id:
            query["category_ids"] = category_id
        if search:
            normalized = search.strip()
            self._append_and_clause(
                query,
                {
                    "$or": [
                        {"name": {"$regex": normalized, "$options": "i"}},
                        {"description": {"$regex": normalized, "$options": "i"}},
                    ]
                },
            )

        total = self._meals.count_documents(query)
        documents = (
            self._meals.find(query)
            .sort([("updated_at", DESCENDING), ("name", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_meal_model(document) for document in documents], total

    def create_meal(
        self,
        *,
        meal_id: str,
        name: str,
        hero_image_url: str,
        image_urls: list[str],
        description: str,
        meal_type: str,
        meal_types: list[str],
        category_ids: list[str],
        culture_tags: list[str],
        diet_rules_supported: list[str],
        allergy_exclusions: list[str],
        prep_time_minutes: int,
        cook_time_minutes: int,
        difficulty: str,
        servings: int,
        nutritional_specs: list[dict[str, Any]],
        nutrition_summary: dict[str, Any],
        estimated_costs: list[dict[str, Any]],
        recipe_steps: list[str],
        recipe_step_items: list[dict[str, Any]],
        ingredient_items: list[dict[str, Any]],
        linked_product_ids: list[str],
        chef_available: bool,
        is_active: bool,
        selling_prices: list[dict[str, Any]] | None = None,
        rating_average: float = 0.0,
        rating_count: int = 0,
        highlight_tags: list[str] | None = None,
        search_document: str | None = None,
        search_embedding: list[float] | None = None,
        search_embedding_model: str | None = None,
        search_embedding_source_hash: str | None = None,
    ) -> Meal:
        now = datetime.now(timezone.utc)
        resolved_search_document = search_document or self._build_search_document(
            {
                "name": name,
                "description": description,
                "meal_type": meal_type,
                "meal_types": meal_types,
                "culture_tags": culture_tags,
                "diet_rules_supported": diet_rules_supported,
                "ingredient_items": ingredient_items,
                "recipe_steps": recipe_steps,
                "recipe_step_items": recipe_step_items,
                "nutritional_specs": nutritional_specs,
                "nutrition_summary": nutrition_summary,
                "estimated_costs": estimated_costs,
                "prep_time_minutes": prep_time_minutes,
                "cook_time_minutes": cook_time_minutes,
            }
        )
        payload = {
            "_id": meal_id,
            "name": name,
            "hero_image_url": hero_image_url,
            "image_urls": image_urls,
            "description": description,
            "meal_type": meal_type,
            "meal_types": meal_types,
            "category_ids": category_ids,
            "culture_tags": culture_tags,
            "diet_rules_supported": diet_rules_supported,
            "allergy_exclusions": allergy_exclusions,
            "prep_time_minutes": prep_time_minutes,
            "cook_time_minutes": cook_time_minutes,
            "difficulty": difficulty,
            "servings": servings,
            "nutritional_specs": nutritional_specs,
            "nutrition_summary": nutrition_summary,
            "estimated_costs": estimated_costs,
            "recipe_steps": recipe_steps,
            "recipe_step_items": recipe_step_items,
            "ingredient_items": ingredient_items,
            "linked_product_ids": linked_product_ids,
            "chef_available": chef_available,
            "is_active": is_active,
            "selling_prices": selling_prices or [],
            "rating_average": rating_average,
            "rating_count": rating_count,
            "highlight_tags": highlight_tags or [],
            "search_document": resolved_search_document,
            "search_document_hash": self._hash_search_document(resolved_search_document),
            "search_embedding": list(search_embedding) if search_embedding is not None else None,
            "search_embedding_model": search_embedding_model,
            "search_embedding_source_hash": search_embedding_source_hash,
            "search_embedding_updated_at": now if search_embedding is not None else None,
            "created_at": now,
            "updated_at": now,
        }
        self._meals.insert_one(payload)
        return self._to_meal_model(payload)

    def update_meal(
        self,
        *,
        meal_id: str,
        name: str,
        hero_image_url: str,
        image_urls: list[str],
        description: str,
        meal_type: str,
        meal_types: list[str],
        category_ids: list[str],
        culture_tags: list[str],
        diet_rules_supported: list[str],
        allergy_exclusions: list[str],
        prep_time_minutes: int,
        cook_time_minutes: int,
        difficulty: str,
        servings: int,
        nutritional_specs: list[dict[str, Any]],
        nutrition_summary: dict[str, Any],
        estimated_costs: list[dict[str, Any]],
        recipe_steps: list[str],
        recipe_step_items: list[dict[str, Any]],
        ingredient_items: list[dict[str, Any]],
        linked_product_ids: list[str],
        chef_available: bool,
        is_active: bool,
        selling_prices: list[dict[str, Any]] | None = None,
        rating_average: float = 0.0,
        rating_count: int = 0,
        highlight_tags: list[str] | None = None,
        search_document: str | None = None,
        search_embedding: list[float] | None = None,
        search_embedding_model: str | None = None,
        search_embedding_source_hash: str | None = None,
    ) -> Meal | None:
        existing = self._meals.find_one({"_id": meal_id})
        if existing is None:
            return None

        resolved_search_document = search_document or self._build_search_document(
            {
                "name": name,
                "description": description,
                "meal_type": meal_type,
                "meal_types": meal_types,
                "culture_tags": culture_tags,
                "diet_rules_supported": diet_rules_supported,
                "ingredient_items": ingredient_items,
                "recipe_steps": recipe_steps,
                "recipe_step_items": recipe_step_items,
                "nutritional_specs": nutritional_specs,
                "nutrition_summary": nutrition_summary,
                "estimated_costs": estimated_costs,
                "prep_time_minutes": prep_time_minutes,
                "cook_time_minutes": cook_time_minutes,
            }
        )
        payload = {
            "name": name,
            "hero_image_url": hero_image_url,
            "image_urls": image_urls,
            "description": description,
            "meal_type": meal_type,
            "meal_types": meal_types,
            "category_ids": category_ids,
            "culture_tags": culture_tags,
            "diet_rules_supported": diet_rules_supported,
            "allergy_exclusions": allergy_exclusions,
            "prep_time_minutes": prep_time_minutes,
            "cook_time_minutes": cook_time_minutes,
            "difficulty": difficulty,
            "servings": servings,
            "nutritional_specs": nutritional_specs,
            "nutrition_summary": nutrition_summary,
            "estimated_costs": estimated_costs,
            "recipe_steps": recipe_steps,
            "recipe_step_items": recipe_step_items,
            "ingredient_items": ingredient_items,
            "linked_product_ids": linked_product_ids,
            "chef_available": chef_available,
            "is_active": is_active,
            "selling_prices": selling_prices or [],
            "rating_average": rating_average,
            "rating_count": rating_count,
            "highlight_tags": highlight_tags or [],
            "search_document": resolved_search_document,
            "search_document_hash": self._hash_search_document(resolved_search_document),
            "search_embedding": list(search_embedding) if search_embedding is not None else None,
            "search_embedding_model": search_embedding_model,
            "search_embedding_source_hash": search_embedding_source_hash,
            "search_embedding_updated_at": datetime.now(timezone.utc)
            if search_embedding is not None
            else None,
            "updated_at": datetime.now(timezone.utc),
        }
        self._meals.update_one({"_id": meal_id}, {"$set": payload})
        updated = self._meals.find_one({"_id": meal_id})
        return None if updated is None else self._to_meal_model(updated)

    def delete_meal(self, meal_id: str) -> bool:
        result = self._meals.delete_one({"_id": meal_id})
        return result.deleted_count == 1

    def delete_meals(self, meal_ids: list[str]) -> int:
        if not meal_ids:
            return 0
        result = self._meals.delete_many({"_id": {"$in": meal_ids}})
        return result.deleted_count

    @classmethod
    def build_search_document(cls, payload: dict[str, Any]) -> str:
        return cls._build_search_document(payload)

    @classmethod
    def hash_search_document(cls, search_document: str) -> str:
        return cls._hash_search_document(search_document)

    @staticmethod
    def _build_search_document(payload: dict[str, Any]) -> str:
        nutrition_summary = dict(payload.get("nutrition_summary", {}) or {})
        ingredient_items = list(payload.get("ingredient_items", []) or [])
        recipe_steps = list(payload.get("recipe_steps", []) or [])
        recipe_step_items = list(payload.get("recipe_step_items", []) or [])
        estimated_costs = list(payload.get("estimated_costs", []) or [])
        prep_time_minutes = int(payload.get("prep_time_minutes", 0) or 0)
        cook_time_minutes = int(payload.get("cook_time_minutes", 0) or 0)
        total_time_minutes = prep_time_minutes + cook_time_minutes

        traits: list[str] = []
        if float(nutrition_summary.get("protein_g", 0) or 0) >= 25:
            traits.append("high protein protein rich")
        if int(nutrition_summary.get("calories", 0) or 0) >= 500:
            traits.append("filling hearty calorie dense weight gain")
        if total_time_minutes and total_time_minutes <= 30:
            traits.append("quick easy weekday low effort")
        if any(float(cost.get("amount", 0) or 0) <= 4.5 for cost in estimated_costs):
            traits.append("budget affordable cheap value")

        ingredient_names = " ".join(str(item.get("name", "")) for item in ingredient_items)
        step_text = " ".join(str(step) for step in recipe_steps)
        step_item_text = " ".join(str(step.get("instruction", "")) for step in recipe_step_items)
        diet_rules = " ".join(str(item) for item in list(payload.get("diet_rules_supported", []) or []))
        cultures = " ".join(str(item) for item in list(payload.get("culture_tags", []) or []))
        meal_types = " ".join(str(item) for item in list(payload.get("meal_types", []) or []))
        primary_meal_type = str(payload.get("meal_type", "") or "")

        parts = [
            str(payload.get("name", "") or ""),
            str(payload.get("description", "") or ""),
            meal_types or primary_meal_type,
            cultures,
            diet_rules,
            ingredient_names,
            step_text,
            step_item_text,
            " ".join(traits),
        ]
        return " ".join(part.strip() for part in parts if str(part).strip())

    @classmethod
    def _hash_search_document(cls, search_document: str) -> str:
        return sha256(search_document.encode("utf-8")).hexdigest()

    @staticmethod
    def _append_and_clause(query: dict[str, Any], clause: dict[str, Any]) -> None:
        query.setdefault("$and", []).append(clause)

    def _to_search_candidate(self, document: dict[str, Any]) -> MealSearchCandidate:
        search_document = str(document.get("search_document") or "").strip()
        if not search_document:
            search_document = self._build_search_document(document)
        search_document_hash = str(document.get("search_document_hash") or "").strip()
        if not search_document_hash:
            search_document_hash = self._hash_search_document(search_document)
        raw_embedding = document.get("search_embedding")
        search_embedding = (
            tuple(float(value) for value in list(raw_embedding))
            if isinstance(raw_embedding, list) and raw_embedding
            else None
        )
        return MealSearchCandidate(
            meal=self._to_meal_model(document),
            search_document=search_document,
            search_document_hash=search_document_hash,
            search_embedding=search_embedding,
            search_embedding_model=(
                str(document.get("search_embedding_model"))
                if document.get("search_embedding_model") is not None
                else None
            ),
            search_embedding_source_hash=(
                str(document.get("search_embedding_source_hash"))
                if document.get("search_embedding_source_hash") is not None
                else None
            ),
            search_embedding_updated_at=document.get("search_embedding_updated_at"),
        )

    @staticmethod
    def _to_category_model(document: dict[str, Any]) -> MealCategory:
        return MealCategory(
            id=str(document["_id"]),
            slug=MealCategorySlug(str(document["slug"])),
            name=str(document["name"]),
            description=str(document.get("description", "")),
            img_url=str(document.get("img_url", "")),
            sort_order=int(document["sort_order"]),
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _to_meal_model(document: dict[str, Any]) -> Meal:
        primary_meal_type = MealType(str(document["meal_type"]))
        meal_types = [
            MealType(str(entry))
            for entry in document.get("meal_types", [])
            if str(entry).strip()
        ]
        if not meal_types:
            meal_types = [primary_meal_type]
        elif primary_meal_type not in meal_types:
            meal_types = [primary_meal_type, *meal_types]

        nutrition = document.get("nutrition_summary", {})
        nutritional_specs = [
            NutritionSpec(
                nutrient_id=NutrientType(int(entry["nutrient_id"])),
                amount=float(entry["amount"]),
                unit=NutrientUnit(str(entry["unit"])),
            )
            for entry in document.get("nutritional_specs", [])
        ]
        ingredient_items = [
            MealRepository._to_ingredient_model(item, index=index)
            for index, item in enumerate(document.get("ingredient_items", []))
        ]
        fallback_recipe_steps = [
            MealRecipeStep(instruction=str(step), ingredient_ids=[], image_url=None)
            for step in document.get("recipe_steps", [])
        ]
        return Meal(
            id=str(document["_id"]),
            name=str(document["name"]),
            hero_image_url=str(document.get("hero_image_url", "")),
            image_urls=[
                str(image_url)
                for image_url in (
                    document.get("image_urls")
                    or ([str(document.get("hero_image_url", ""))] if str(document.get("hero_image_url", "")).strip() else [])
                )
                if str(image_url).strip()
            ],
            description=str(document.get("description", "")),
            meal_type=primary_meal_type,
            category_ids=[str(category_id) for category_id in document.get("category_ids", [])],
            culture_tags=[str(tag) for tag in document.get("culture_tags", [])],
            diet_rules_supported=[str(rule) for rule in document.get("diet_rules_supported", [])],
            allergy_exclusions=[str(item) for item in document.get("allergy_exclusions", [])],
            prep_time_minutes=int(document.get("prep_time_minutes", 0)),
            cook_time_minutes=int(document.get("cook_time_minutes", 0)),
            difficulty=MealDifficulty(str(document.get("difficulty", MealDifficulty.EASY.value))),
            servings=int(document.get("servings", 1)),
            nutritional_specs=nutritional_specs,
            nutrition_summary=MealNutritionSummary(
                calories=int(nutrition.get("calories", 0)),
                protein_g=float(nutrition.get("protein_g", 0)),
                carbs_g=float(nutrition.get("carbs_g", 0)),
                fat_g=float(nutrition.get("fat_g", 0)),
            ),
            estimated_costs=[
                MealEstimatedCost(
                    country_code=CountryCode(str(entry["country_code"])),
                    currency_code=CurrencyCode(str(entry["currency_code"])),
                    amount=float(entry["amount"]),
                )
                for entry in document.get("estimated_costs", [])
            ],
            recipe_steps=[str(step) for step in document.get("recipe_steps", [])],
            recipe_step_items=[
                MealRecipeStep(
                    instruction=str(item.get("instruction", "")),
                    ingredient_ids=[str(ingredient_id) for ingredient_id in item.get("ingredient_ids", [])],
                    image_url=(str(item.get("image_url", "")).strip() or None),
                )
                for item in document.get("recipe_step_items", [])
            ]
            or fallback_recipe_steps,
            ingredient_items=ingredient_items,
            linked_product_ids=[str(product_id) for product_id in document.get("linked_product_ids", [])],
            chef_available=bool(document.get("chef_available", False)),
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            meal_types=meal_types,
            selling_prices=[
                MealSellingPrice(
                    country_code=CountryCode(str(entry["country_code"])),
                    currency_code=CurrencyCode(str(entry["currency_code"])),
                    amount_minor=int(entry["amount_minor"]),
                )
                for entry in document.get("selling_prices", [])
            ],
            rating_average=float(document.get("rating_average", 0.0) or 0.0),
            rating_count=int(document.get("rating_count", 0) or 0),
            highlight_tags=[
                MealHighlightTag(str(tag))
                for tag in document.get("highlight_tags", [])
                if str(tag) in {member.value for member in MealHighlightTag}
            ],
        )

    @staticmethod
    def _to_ingredient_model(item: dict[str, Any], *, index: int) -> MealIngredient:
        quantity = float(item["quantity"])
        unit = str(item["unit"])
        unit_code = (
            str(item["unit_code"]).strip()
            if item.get("unit_code") is not None
            else MeasurementService.normalize_unit_code(unit)
        )
        seed = MeasurementService.default_unit_seed(unit_code) if unit_code else None
        canonical_unit = (
            str(item["canonical_unit"]).strip()
            if item.get("canonical_unit") is not None
            else (str(seed["canonical_unit"]) if seed is not None else None)
        )
        canonical_quantity = (
            float(item["canonical_quantity"])
            if item.get("canonical_quantity") is not None
            else (
                quantity * float(seed["multiplier_to_canonical"])
                if seed is not None
                else None
            )
        )
        measurement_type = (
            MeasurementType(str(item["measurement_type"]))
            if item.get("measurement_type") is not None
            else (
                MeasurementType(str(seed["measurement_type"]))
                if seed is not None
                else None
            )
        )
        rounding_rule = (
            RoundingRule(str(item["rounding_rule"]))
            if item.get("rounding_rule") is not None
            else (
                RoundingRule(str(seed["default_rounding_rule"]))
                if seed is not None
                else None
            )
        )
        scaling_behavior = (
            ScalingBehavior(str(item["scaling_behavior"]))
            if item.get("scaling_behavior") is not None
            else (
                ScalingBehavior.DISCRETE
                if seed is not None and not bool(seed["is_fractional_allowed"])
                else ScalingBehavior.LINEAR
            )
        )
        return MealIngredient(
            id=str(item.get("id", f"ingredient_{index + 1}")),
            name=str(item["name"]),
            quantity=quantity,
            unit=unit,
            optional=bool(item.get("optional", False)),
            linked_product_ids=[str(product_id) for product_id in item.get("linked_product_ids", [])],
            measurement_type=measurement_type,
            unit_code=unit_code,
            canonical_quantity=canonical_quantity,
            canonical_unit=canonical_unit,
            conversion_profile_id=(
                str(item["conversion_profile_id"]).strip()
                if item.get("conversion_profile_id") is not None
                else None
            ),
            scaling_behavior=scaling_behavior,
            rounding_rule=rounding_rule,
        )
