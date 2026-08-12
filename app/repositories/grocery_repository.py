from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.data.grocery_seed import CATEGORY_SEEDS, PRODUCT_SEEDS
from app.models.grocery import (
    CountryCode,
    CountryPrice,
    CultureTag,
    CurrencyCode,
    GroceryCategory,
    GroceryCategorySlug,
    GroceryProduct,
    NutritionSpec,
    NutrientType,
    NutrientUnit,
)


@dataclass(frozen=True, slots=True)
class GrocerySearchCandidate:
    product: GroceryProduct
    search_document: str
    search_document_hash: str
    search_embedding: tuple[float, ...] | None
    search_embedding_model: str | None
    search_embedding_source_hash: str | None
    search_embedding_updated_at: datetime | None


class GroceryRepository:
    def __init__(
        self,
        categories_collection: Collection[dict[str, Any]],
        products_collection: Collection[dict[str, Any]],
    ) -> None:
        self._categories = categories_collection
        self._products = products_collection

    def ensure_seed_data(self) -> None:
        now = datetime.now(timezone.utc)

        for category in CATEGORY_SEEDS:
            category_id = str(category["id"])
            payload = {
                "slug": category["slug"],
                "name": category["name"],
                "icon_name": category["icon_name"],
                "img_url": category["img_url"],
                "description": category["description"],
                "sort_order": category["sort_order"],
                "is_active": category["is_active"],
                "updated_at": now,
            }
            self._categories.update_one(
                {"_id": category_id},
                {
                    "$set": payload,
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )

        self._seed_missing_products(now=now)

    def _seed_missing_products(self, *, now: datetime) -> None:
        for product in PRODUCT_SEEDS:
            product_id = str(product["id"])
            seed_img_url = str(product.get("img_url", "")).strip()
            existing = self._products.find_one({"_id": product_id})
            img_url = str(existing.get("img_url", "")).strip() if existing is not None else ""
            if seed_img_url:
                img_url = seed_img_url
            payload = {
                "category_id": product["category_id"],
                "img_url": img_url,
                "product": product["product"],
                "sort_order": int(product.get("sort_order", 0)),
                "product_tags": product["product_tags"],
                "culture_tags": product["culture_tags"],
                "nutritional_specs": product["nutritional_specs"],
                "description": product["description"],
                "is_active": product["is_active"],
                "updated_at": now,
                "prices": [
                    {
                        **price,
                        "updated_at": now,
                    }
                    for price in list(product["prices"])
                ],
            }
            self._products.update_one(
                {"_id": product_id},
                {
                    "$set": payload,
                    "$setOnInsert": {
                        "_id": product_id,
                        "created_at": now,
                    },
                },
                upsert=True,
            )

    def list_categories(self) -> list[GroceryCategory]:
        documents = self._categories.find({"is_active": True}).sort("sort_order", ASCENDING)
        return [self._to_category_model(document) for document in documents]

    def list_all_categories(self) -> list[GroceryCategory]:
        documents = self._categories.find({}).sort("sort_order", ASCENDING)
        return [self._to_category_model(document) for document in documents]

    def get_category(self, category_id: str) -> GroceryCategory | None:
        document = self._categories.find_one({"_id": category_id, "is_active": True})
        if document is None:
            return None
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
        query: dict[str, Any] = {
            "category_id": category_id,
            "is_active": True,
        }

        if culture_tag is not None:
            query["culture_tags"] = culture_tag.value

        if product_tag:
            query["product_tags"] = product_tag.strip().lower()

        if search:
            normalized_search = search.strip()
            query["$or"] = [
                {"product": {"$regex": normalized_search, "$options": "i"}},
                {"product_tags": {"$regex": normalized_search, "$options": "i"}},
            ]

        sort_spec = self._product_sort_spec(sort)
        total = self._products.count_documents(query)
        documents = (
            self._products.find(query)
            .sort(sort_spec)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_product_model(document) for document in documents], total

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
        query = self._build_product_query(
            category_id=category_id,
            culture_tag=culture_tag,
            search=search,
            product_tag=product_tag,
            include_inactive=False,
        )
        sort_spec = self._product_sort_spec(sort)
        total = self._products.count_documents(query)
        documents = (
            self._products.find(query)
            .sort(sort_spec)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_product_model(document) for document in documents], total

    @staticmethod
    def _build_product_query(
        *,
        category_id: str | None,
        culture_tag: CultureTag | None,
        search: str | None,
        product_tag: str | None,
        include_inactive: bool,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if category_id:
            query["category_id"] = category_id

        if not include_inactive:
            query["is_active"] = True

        if culture_tag is not None:
            query["culture_tags"] = culture_tag.value

        if product_tag:
            query["product_tags"] = product_tag.strip().lower()

        if search:
            normalized_search = search.strip()
            query["$or"] = [
                {"product": {"$regex": normalized_search, "$options": "i"}},
                {"product_tags": {"$regex": normalized_search, "$options": "i"}},
            ]

        return query

    @staticmethod
    def _product_sort_spec(sort: str | None) -> list[tuple[str, int]]:
        normalized_sort = (sort or "featured").strip().lower()
        sort_spec: list[tuple[str, int]] = [("sort_order", ASCENDING), ("product", ASCENDING)]
        if normalized_sort == "name_desc":
            sort_spec = [("product", DESCENDING)]
        elif normalized_sort == "newest":
            sort_spec = [("updated_at", DESCENDING), ("sort_order", ASCENDING), ("product", ASCENDING)]
        elif normalized_sort == "price_low_to_high":
            sort_spec = [("prices.0.amount", ASCENDING), ("sort_order", ASCENDING), ("product", ASCENDING)]
        elif normalized_sort == "price_high_to_low":
            sort_spec = [("prices.0.amount", DESCENDING), ("sort_order", ASCENDING), ("product", ASCENDING)]
        return sort_spec

    def get_product(self, product_id: str) -> GroceryProduct | None:
        document = self._products.find_one({"_id": product_id, "is_active": True})
        if document is None:
            return None
        return self._to_product_model(document)

    def get_product_by_id(self, product_id: str) -> GroceryProduct | None:
        document = self._products.find_one({"_id": product_id})
        if document is None:
            return None
        return self._to_product_model(document)

    def list_products_by_ids(self, product_ids: list[str]) -> list[GroceryProduct]:
        if not product_ids:
            return []

        documents = self._products.find({"_id": {"$in": product_ids}, "is_active": True})
        mapped = {
            str(document["_id"]): self._to_product_model(document)
            for document in documents
        }
        return [mapped[product_id] for product_id in product_ids if product_id in mapped]

    def list_all_products(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        category_id: str | None = None,
    ) -> tuple[list[GroceryProduct], int]:
        query: dict[str, Any] = {}

        if category_id:
            query["category_id"] = category_id

        if search:
            normalized_search = search.strip()
            query["$or"] = [
                {"product": {"$regex": normalized_search, "$options": "i"}},
                {"product_tags": {"$regex": normalized_search, "$options": "i"}},
            ]

        total = self._products.count_documents(query)
        documents = (
            self._products.find(query)
            .sort([("sort_order", ASCENDING), ("updated_at", DESCENDING), ("product", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_product_model(document) for document in documents], total

    def create_product(
        self,
        *,
        product_id: str,
        category_id: str,
        img_url: str,
        product: str,
        sort_order: int,
        product_tags: list[str],
        culture_tags: list[str],
        nutritional_specs: list[dict[str, Any]],
        prices: list[dict[str, Any]],
        description: str,
        is_active: bool,
        search_document: str | None = None,
        search_embedding: list[float] | None = None,
        search_embedding_model: str | None = None,
        search_embedding_source_hash: str | None = None,
    ) -> GroceryProduct:
        now = datetime.now(timezone.utc)
        resolved_search_document = search_document or self._build_search_document(
            {
                "product": product,
                "description": description,
                "product_tags": product_tags,
                "culture_tags": culture_tags,
            }
        )
        payload = {
            "_id": product_id,
            "category_id": category_id,
            "img_url": img_url,
            "product": product,
            "sort_order": sort_order,
            "product_tags": product_tags,
            "culture_tags": culture_tags,
            "nutritional_specs": nutritional_specs,
            "prices": [
                {
                    **price,
                    "source": price.get("source", "admin_dashboard"),
                    "updated_at": now,
                    "is_active": price.get("is_active", True),
                }
                for price in prices
            ],
            "description": description,
            "is_active": is_active,
            "search_document": resolved_search_document,
            "search_document_hash": self._hash_search_document(resolved_search_document),
            "search_embedding": list(search_embedding) if search_embedding is not None else None,
            "search_embedding_model": search_embedding_model,
            "search_embedding_source_hash": search_embedding_source_hash,
            "search_embedding_updated_at": now if search_embedding is not None else None,
            "created_at": now,
            "updated_at": now,
        }
        self._products.insert_one(payload)
        return self._to_product_model(payload)

    def update_product(
        self,
        *,
        product_id: str,
        category_id: str,
        img_url: str,
        product: str,
        sort_order: int,
        product_tags: list[str],
        culture_tags: list[str],
        nutritional_specs: list[dict[str, Any]],
        prices: list[dict[str, Any]],
        description: str,
        is_active: bool,
        search_document: str | None = None,
        search_embedding: list[float] | None = None,
        search_embedding_model: str | None = None,
        search_embedding_source_hash: str | None = None,
    ) -> GroceryProduct | None:
        now = datetime.now(timezone.utc)
        existing = self._products.find_one({"_id": product_id})
        if existing is None:
            return None

        resolved_search_document = search_document or self._build_search_document(
            {
                "product": product,
                "description": description,
                "product_tags": product_tags,
                "culture_tags": culture_tags,
            }
        )
        payload = {
            "category_id": category_id,
            "img_url": img_url,
            "product": product,
            "sort_order": sort_order,
            "product_tags": product_tags,
            "culture_tags": culture_tags,
            "nutritional_specs": nutritional_specs,
            "prices": [
                {
                    **price,
                    "source": price.get("source", "admin_dashboard"),
                    "updated_at": now,
                    "is_active": price.get("is_active", True),
                }
                for price in prices
            ],
            "description": description,
            "is_active": is_active,
            "search_document": resolved_search_document,
            "search_document_hash": self._hash_search_document(resolved_search_document),
            "search_embedding": list(search_embedding) if search_embedding is not None else None,
            "search_embedding_model": search_embedding_model,
            "search_embedding_source_hash": search_embedding_source_hash,
            "search_embedding_updated_at": now if search_embedding is not None else None,
            "updated_at": now,
        }
        self._products.update_one({"_id": product_id}, {"$set": payload})
        updated = self._products.find_one({"_id": product_id})
        return None if updated is None else self._to_product_model(updated)

    def delete_product(self, product_id: str) -> bool:
        result = self._products.delete_one({"_id": product_id})
        return result.deleted_count > 0

    def delete_products(self, product_ids: list[str]) -> int:
        if not product_ids:
            return 0
        result = self._products.delete_many({"_id": {"$in": product_ids}})
        return int(result.deleted_count)

    def assign_products_to_discount(self, *, product_ids: list[str], discount_id: str) -> int:
        if not product_ids:
            return 0
        result = self._products.update_many(
            {"_id": {"$in": product_ids}},
            {"$set": {"discount_id": discount_id, "updated_at": datetime.now(timezone.utc)}},
        )
        return int(result.modified_count)

    def unassign_products_from_discount(self, *, product_ids: list[str]) -> int:
        if not product_ids:
            return 0
        result = self._products.update_many(
            {"_id": {"$in": product_ids}},
            {"$set": {"discount_id": None, "updated_at": datetime.now(timezone.utc)}},
        )
        return int(result.modified_count)

    def unassign_all_products_from_discount(self, *, discount_id: str) -> list[str]:
        product_ids = [
            str(document["_id"])
            for document in self._products.find({"discount_id": discount_id}, {"_id": 1})
        ]
        if not product_ids:
            return []
        self._products.update_many(
            {"_id": {"$in": product_ids}},
            {"$set": {"discount_id": None, "updated_at": datetime.now(timezone.utc)}},
        )
        return product_ids

    def list_products_by_discount(
        self,
        *,
        discount_id: str,
        page: int,
        page_size: int,
        search: str | None = None,
    ) -> tuple[list[GroceryProduct], int]:
        query: dict[str, Any] = {"discount_id": discount_id}
        if search:
            normalized_search = search.strip()
            query["$or"] = [
                {"product": {"$regex": normalized_search, "$options": "i"}},
                {"product_tags": {"$regex": normalized_search, "$options": "i"}},
            ]

        total = self._products.count_documents(query)
        documents = (
            self._products.find(query)
            .sort([("sort_order", ASCENDING), ("product", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_product_model(document) for document in documents], total

    def count_products_by_discount(self, *, discount_id: str) -> int:
        return self._products.count_documents({"discount_id": discount_id})

    def list_similar_product_candidates(
        self,
        *,
        category_id: str | None,
        exclude_product_id: str,
        limit: int,
    ) -> list[GrocerySearchCandidate]:
        query: dict[str, Any] = {"is_active": True, "_id": {"$ne": exclude_product_id}}
        if category_id:
            query["category_id"] = category_id

        documents = (
            self._products.find(query)
            .sort([("updated_at", DESCENDING), ("product", ASCENDING)])
            .limit(max(limit, 1))
        )
        return [self._to_search_candidate(document) for document in documents]

    def get_product_search_candidate_by_id(self, product_id: str) -> GrocerySearchCandidate | None:
        document = self._products.find_one({"_id": product_id})
        return None if document is None else self._to_search_candidate(document)

    def update_product_search_embedding(
        self,
        *,
        product_id: str,
        search_document: str,
        search_embedding: list[float],
        embedding_model: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._products.update_one(
            {"_id": product_id},
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

    @classmethod
    def build_search_document(cls, payload: dict[str, Any]) -> str:
        return cls._build_search_document(payload)

    @classmethod
    def hash_search_document(cls, search_document: str) -> str:
        return cls._hash_search_document(search_document)

    @staticmethod
    def _build_search_document(payload: dict[str, Any]) -> str:
        product_tags = " ".join(str(tag) for tag in list(payload.get("product_tags", []) or []))
        culture_tags = " ".join(str(tag) for tag in list(payload.get("culture_tags", []) or []))
        parts = [
            str(payload.get("product", "") or ""),
            str(payload.get("description", "") or ""),
            product_tags,
            culture_tags,
        ]
        return " ".join(part.strip() for part in parts if str(part).strip())

    @classmethod
    def _hash_search_document(cls, search_document: str) -> str:
        return sha256(search_document.encode("utf-8")).hexdigest()

    def _to_search_candidate(self, document: dict[str, Any]) -> GrocerySearchCandidate:
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
        return GrocerySearchCandidate(
            product=self._to_product_model(document),
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
    def _to_category_model(document: dict[str, Any]) -> GroceryCategory:
        category_id = str(document["_id"])
        return GroceryCategory(
            id=category_id,
            slug=GroceryCategorySlug(str(document["slug"])),
            name=str(document["name"]),
            icon_name=str(document["icon_name"]),
            img_url=str(document.get("img_url", "")),
            description=str(document.get("description", "")),
            sort_order=int(document["sort_order"]),
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _to_product_model(document: dict[str, Any]) -> GroceryProduct:
        return GroceryProduct(
            id=str(document["_id"]),
            category_id=str(document["category_id"]),
            img_url=str(document["img_url"]),
            product=str(document["product"]),
            sort_order=int(document.get("sort_order", 0)),
            product_tags=[str(tag) for tag in document.get("product_tags", [])],
            culture_tags=[CultureTag(str(tag)) for tag in document.get("culture_tags", [])],
            nutritional_specs=[
                NutritionSpec(
                    nutrient_id=NutrientType(int(spec["nutrient_id"])),
                    amount=float(spec["amount"]),
                    unit=NutrientUnit(str(spec["unit"])),
                )
                for spec in document.get("nutritional_specs", [])
            ],
            prices=[
                CountryPrice(
                    country_code=CountryCode(str(price["country_code"])),
                    currency_code=CurrencyCode(str(price["currency_code"])),
                    amount=float(price["amount"]),
                    price_unit=str(price["price_unit"]),
                    source=str(price["source"]),
                    updated_at=price["updated_at"],
                    is_active=bool(price.get("is_active", True)),
                    region=str(price["region"]) if price.get("region") else None,
                    city=str(price["city"]) if price.get("city") else None,
                )
                for price in document.get("prices", [])
            ],
            description=str(document.get("description", "")),
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            discount_id=str(document["discount_id"]) if document.get("discount_id") else None,
        )
