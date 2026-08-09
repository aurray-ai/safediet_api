from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class PromotionDraftRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_draft(
        self,
        *,
        campaign_id: str,
        user_id: str,
        context_snapshot_id: str,
        generated_payload: dict[str, Any],
        validation_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        generation_version = self.next_generation_version(campaign_id=campaign_id, user_id=user_id)
        document = {
            "_id": uuid4().hex,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "context_snapshot_id": context_snapshot_id,
            "generated_payload": generated_payload,
            "working_payload": dict(generated_payload),
            "approved_payload": None,
            "is_admin_edited": False,
            "edited_by_admin_id": None,
            "edited_at": None,
            "approved_by_admin_id": None,
            "approved_at": None,
            "generation_version": generation_version,
            "edit_version": 0,
            "status": "generated",
            "validation_warnings": validation_warnings or [],
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return document

    def create_failed_draft(
        self,
        *,
        campaign_id: str,
        user_id: str,
        context_snapshot_id: str,
        failure_reason: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        fallback_payload = {
            "title": "Generation failed",
            "short_message": "",
            "full_message": "",
            "summary": failure_reason[:600],
            "highlights": [],
            "cta_primary": "Review",
            "cta_secondary": "",
            "delivery_type": "notification",
            "location": "ios.home",
            "specs": [],
            "image_urls": [],
            "meal_data": {},
            "grocery_data": {},
            "metadata": {},
        }
        document = {
            "_id": uuid4().hex,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "context_snapshot_id": context_snapshot_id,
            "generated_payload": fallback_payload,
            "working_payload": fallback_payload,
            "approved_payload": None,
            "is_admin_edited": False,
            "edited_by_admin_id": None,
            "edited_at": None,
            "approved_by_admin_id": None,
            "approved_at": None,
            "generation_version": self.next_generation_version(campaign_id=campaign_id, user_id=user_id),
            "edit_version": 0,
            "status": "failed",
            "validation_warnings": [],
            "failure_reason": failure_reason,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return document

    def next_generation_version(self, *, campaign_id: str, user_id: str) -> int:
        latest = self._collection.find_one(
            {"campaign_id": campaign_id, "user_id": user_id},
            sort=[("generation_version", DESCENDING), ("_id", DESCENDING)],
        )
        return int(latest.get("generation_version") or 0) + 1 if latest else 1

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self._collection.find_one({"_id": draft_id})

    def list_campaign_drafts(self, *, campaign_id: str) -> tuple[list[dict[str, Any]], int]:
        items = list(
            self._collection.find({"campaign_id": campaign_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )
        total = self._collection.count_documents({"campaign_id": campaign_id})
        return items, total

    def list_campaign_drafts_by_status(self, *, campaign_id: str, status: str) -> list[dict[str, Any]]:
        return list(self._collection.find({"campaign_id": campaign_id, "status": status}))

    def update_draft(self, draft_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.now(timezone.utc)
        self._collection.update_one({"_id": draft_id}, {"$set": updates})
        return self.get_draft(draft_id)
