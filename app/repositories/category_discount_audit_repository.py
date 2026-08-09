from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class CategoryDiscountAuditRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def append(
        self,
        *,
        category_id: str,
        action: str,
        previous_percent: float | None,
        new_percent: float | None,
        actor_user_id: str,
    ) -> dict[str, Any]:
        document = {
            "_id": uuid4().hex,
            "category_id": category_id,
            "action": action,
            "previous_percent": previous_percent,
            "new_percent": new_percent,
            "actor_user_id": actor_user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self._collection.insert_one(document)
        return document

    def list_for_category(self, *, category_id: str) -> list[dict[str, Any]]:
        return list(
            self._collection.find({"category_id": category_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )
