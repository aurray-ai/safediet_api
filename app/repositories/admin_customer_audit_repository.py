from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class AdminCustomerAuditRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def append(
        self,
        *,
        user_id: str,
        action: str,
        details: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "action": action,
            "details": dict(details),
            "actor_user_id": actor_user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self._collection.insert_one(document)
        return document

    def list_for_user(self, *, user_id: str) -> list[dict[str, Any]]:
        return list(
            self._collection.find({"user_id": user_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )
