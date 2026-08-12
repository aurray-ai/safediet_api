from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class DiscountAuditRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def append(
        self,
        *,
        discount_id: str,
        action: str,
        details: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        document = {
            "_id": uuid4().hex,
            "discount_id": discount_id,
            "action": action,
            "details": dict(details),
            "actor_user_id": actor_user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self._collection.insert_one(document)
        return document

    def list_for_discount(self, *, discount_id: str) -> list[dict[str, Any]]:
        return list(
            self._collection.find({"discount_id": discount_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )
