from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.models.grocery import CountryCode
from app.models.user_pantry_item import UserPantryItem


class UserPantryRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def list_items(self, *, user_id: str) -> list[UserPantryItem]:
        documents = list(
            self._collection.find({"user_id": user_id})
            .sort([("updated_at", DESCENDING), ("product_name", ASCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def upsert_item(
        self,
        *,
        user_id: str,
        product_id: str,
        product_name: str,
        quantity: float,
        unit: str,
        country_code: str | None,
    ) -> UserPantryItem:
        now = datetime.now(timezone.utc)
        query = {
            "user_id": user_id,
            "product_id": product_id,
        }
        self._collection.update_one(
            query,
            {
                "$set": {
                    "user_id": user_id,
                    "product_id": product_id,
                    "product_name": product_name,
                    "quantity": quantity,
                    "unit": unit,
                    "country_code": country_code,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "_id": uuid4().hex,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        document = self._collection.find_one(query)
        if document is None:
            raise RuntimeError("User pantry upsert did not return a document.")
        return self._to_model(document)

    def delete_item(self, *, user_id: str, product_id: str) -> bool:
        result = self._collection.delete_one({"user_id": user_id, "product_id": product_id})
        return result.deleted_count > 0

    def replace_items(
        self,
        *,
        user_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(timezone.utc)
        self._collection.delete_many({"user_id": user_id})
        if not items:
            return
        documents = [
            {
                "_id": uuid4().hex,
                "user_id": user_id,
                "product_id": str(item.get("product_id") or ""),
                "product_name": str(item.get("product_name") or ""),
                "quantity": float(item.get("quantity") or 0.0),
                "unit": str(item.get("unit") or ""),
                "country_code": item.get("country_code"),
                "created_at": now,
                "updated_at": now,
            }
            for item in items
            if str(item.get("product_id") or "").strip()
        ]
        if documents:
            self._collection.insert_many(documents)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> UserPantryItem:
        country_code = document.get("country_code")
        return UserPantryItem(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            product_id=str(document["product_id"]),
            product_name=str(document.get("product_name") or ""),
            quantity=float(document.get("quantity") or 0),
            unit=str(document.get("unit") or ""),
            country_code=CountryCode(str(country_code)) if country_code else None,
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
