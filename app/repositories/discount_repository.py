from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection

from app.models.grocery import GroceryDiscount


class DiscountRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._discounts = collection

    def list_discounts(self) -> list[GroceryDiscount]:
        documents = self._discounts.find({}).sort("created_at", ASCENDING)
        return [self._to_discount_model(document) for document in documents]

    def get_discount(self, discount_id: str) -> GroceryDiscount | None:
        document = self._discounts.find_one({"_id": discount_id})
        if document is None:
            return None
        return self._to_discount_model(document)

    def create_discount(self, *, discount_id: str, label: str, percent: float) -> GroceryDiscount:
        now = datetime.now(timezone.utc)
        payload = {
            "_id": discount_id,
            "label": label,
            "percent": percent,
            "created_at": now,
            "updated_at": now,
        }
        self._discounts.insert_one(payload)
        return self._to_discount_model(payload)

    def update_discount(self, *, discount_id: str, label: str, percent: float) -> GroceryDiscount | None:
        existing = self._discounts.find_one({"_id": discount_id})
        if existing is None:
            return None

        self._discounts.update_one(
            {"_id": discount_id},
            {"$set": {"label": label, "percent": percent, "updated_at": datetime.now(timezone.utc)}},
        )
        updated = self._discounts.find_one({"_id": discount_id})
        return None if updated is None else self._to_discount_model(updated)

    def delete_discount(self, discount_id: str) -> bool:
        result = self._discounts.delete_one({"_id": discount_id})
        return result.deleted_count > 0

    @staticmethod
    def _to_discount_model(document: dict[str, Any]) -> GroceryDiscount:
        return GroceryDiscount(
            id=str(document["_id"]),
            label=str(document["label"]),
            percent=float(document["percent"]),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
