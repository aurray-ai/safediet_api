from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class PromotionCampaignRepository:
    def __init__(
        self,
        campaigns_collection: Collection[dict[str, Any]],
        campaign_users_collection: Collection[dict[str, Any]],
        context_snapshots_collection: Collection[dict[str, Any]],
        audit_logs_collection: Collection[dict[str, Any]],
    ) -> None:
        self._campaigns = campaigns_collection
        self._campaign_users = campaign_users_collection
        self._context_snapshots = context_snapshots_collection
        self._audit_logs = audit_logs_collection

    def create_campaign(
        self,
        *,
        created_by_admin_id: str,
        name: str,
        status: str,
        promotion_type: str,
        delivery_type: str,
        target_location: str,
        admin_instruction: str,
        tone: str,
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "created_by_admin_id": created_by_admin_id,
            "name": name,
            "status": status,
            "promotion_type": promotion_type,
            "delivery_type": delivery_type,
            "target_location": target_location,
            "admin_instruction": admin_instruction,
            "tone": tone,
            "constraints": constraints,
            "selected_user_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self._campaigns.insert_one(document)
        return document

    def list_campaigns(
        self,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        skip = (page - 1) * page_size
        items = list(
            self._campaigns.find({})
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .skip(skip)
            .limit(page_size)
        )
        total = self._campaigns.count_documents({})
        return items, total

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return self._campaigns.find_one({"_id": campaign_id})

    def update_campaign(self, campaign_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        if not updates:
            return self.get_campaign(campaign_id)
        updates["updated_at"] = datetime.now(timezone.utc)
        self._campaigns.update_one({"_id": campaign_id}, {"$set": updates})
        return self.get_campaign(campaign_id)

    def add_campaign_users(self, *, campaign_id: str, user_ids: list[str]) -> int:
        if not user_ids:
            return 0
        now = datetime.now(timezone.utc)
        inserted = 0
        for user_id in user_ids:
            result = self._campaign_users.update_one(
                {"campaign_id": campaign_id, "user_id": user_id},
                {
                    "$setOnInsert": {
                        "_id": uuid4().hex,
                        "campaign_id": campaign_id,
                        "user_id": user_id,
                        "context_status": "pending",
                        "generation_status": "pending",
                        "review_status": "pending",
                        "delivery_status": "pending",
                        "created_at": now,
                    },
                    "$set": {"updated_at": now},
                },
                upsert=True,
            )
            if result.upserted_id is not None:
                inserted += 1
        if inserted:
            self._campaigns.update_one(
                {"_id": campaign_id},
                {"$inc": {"selected_user_count": inserted}, "$set": {"updated_at": now}},
            )
        return inserted

    def remove_campaign_user(self, *, campaign_id: str, user_id: str) -> bool:
        result = self._campaign_users.delete_one({"campaign_id": campaign_id, "user_id": user_id})
        if result.deleted_count:
            now = datetime.now(timezone.utc)
            self._campaigns.update_one(
                {"_id": campaign_id},
                {"$inc": {"selected_user_count": -1}, "$set": {"updated_at": now}},
            )
            self._context_snapshots.delete_many({"campaign_id": campaign_id, "user_id": user_id})
        return result.deleted_count > 0

    def list_campaign_users(self, *, campaign_id: str) -> list[dict[str, Any]]:
        return list(
            self._campaign_users.find({"campaign_id": campaign_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )

    def get_campaign_user(self, *, campaign_id: str, user_id: str) -> dict[str, Any] | None:
        return self._campaign_users.find_one({"campaign_id": campaign_id, "user_id": user_id})

    def update_campaign_user(self, *, campaign_id: str, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.now(timezone.utc)
        self._campaign_users.update_one(
            {"campaign_id": campaign_id, "user_id": user_id},
            {"$set": updates},
        )
        return self.get_campaign_user(campaign_id=campaign_id, user_id=user_id)

    def save_context_snapshot(
        self,
        *,
        campaign_id: str,
        user_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "campaign_id": campaign_id,
            "user_id": user_id,
            **snapshot,
            "created_at": now,
        }
        self._context_snapshots.insert_one(document)
        self.update_campaign_user(
            campaign_id=campaign_id,
            user_id=user_id,
            updates={"context_status": "ready"},
        )
        return document

    def replace_context_snapshot(
        self,
        *,
        campaign_id: str,
        user_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        self._context_snapshots.delete_many({"campaign_id": campaign_id, "user_id": user_id})
        return self.save_context_snapshot(campaign_id=campaign_id, user_id=user_id, snapshot=snapshot)

    def get_latest_context_snapshot(self, *, campaign_id: str, user_id: str) -> dict[str, Any] | None:
        return self._context_snapshots.find_one(
            {"campaign_id": campaign_id, "user_id": user_id},
            sort=[("created_at", DESCENDING), ("_id", DESCENDING)],
        )

    def append_audit_log(
        self,
        *,
        campaign_id: str,
        actor_admin_id: str,
        action: str,
        draft_id: str | None = None,
        user_id: str | None = None,
        before_payload: dict[str, Any] | None = None,
        after_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        document = {
            "_id": uuid4().hex,
            "campaign_id": campaign_id,
            "draft_id": draft_id,
            "user_id": user_id,
            "actor_admin_id": actor_admin_id,
            "action": action,
            "before_payload": before_payload,
            "after_payload": after_payload,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc),
        }
        self._audit_logs.insert_one(document)
        return document

    def list_audit_logs(self, *, campaign_id: str) -> tuple[list[dict[str, Any]], int]:
        items = list(
            self._audit_logs.find({"campaign_id": campaign_id}).sort(
                [("created_at", DESCENDING), ("_id", DESCENDING)]
            )
        )
        total = self._audit_logs.count_documents({"campaign_id": campaign_id})
        return items, total
