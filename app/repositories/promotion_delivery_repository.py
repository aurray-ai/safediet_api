from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class PromotionDeliveryRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_delivery(
        self,
        *,
        campaign_id: str,
        draft_id: str,
        user_id: str,
        delivery_type: str,
        location: str,
        payload_sent: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "campaign_id": campaign_id,
            "draft_id": draft_id,
            "user_id": user_id,
            "delivery_type": delivery_type,
            "location": location,
            "payload_sent": payload_sent,
            "delivery_status": "queued",
            "trace_id": None,
            "chat_message_id": None,
            "sent_at": None,
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return document

    def update_delivery(self, delivery_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.now(timezone.utc)
        self._collection.update_one({"_id": delivery_id}, {"$set": updates})
        return self.get_delivery(delivery_id)

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        return self._collection.find_one({"_id": delivery_id})

    def list_campaign_deliveries(self, *, campaign_id: str) -> tuple[list[dict[str, Any]], int]:
        items = list(
            self._collection.find({"campaign_id": campaign_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )
        total = self._collection.count_documents({"campaign_id": campaign_id})
        return items, total

