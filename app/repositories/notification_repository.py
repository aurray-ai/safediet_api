from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.notification import (
    AppNotification,
    NotificationCategory,
    NotificationNavigationMode,
    NotificationType,
)


class NotificationRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_notification(
        self,
        *,
        category: NotificationCategory,
        notification_type: NotificationType,
        title: str,
        message: str,
        navigation_mode: NotificationNavigationMode,
        recipient_user_ids: list[str],
        target: dict[str, Any],
        details: dict[str, Any],
        metadata: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> AppNotification:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "category": category.value,
            "notification_type": notification_type.value,
            "title": title,
            "message": message,
            "navigation_mode": navigation_mode.value,
            "recipient_user_ids": list(recipient_user_ids),
            "read_by_user_ids": [],
            "target": dict(target),
            "details": dict(details),
            "metadata": dict(metadata),
            "idempotency_key": idempotency_key,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_idempotency_key(self, idempotency_key: str) -> AppNotification | None:
        document = self._collection.find_one({"idempotency_key": idempotency_key})
        return None if document is None else self._to_model(document)

    def update_notification_content(
        self,
        *,
        notification_id: str,
        title: str,
        message: str,
        target: dict[str, Any],
        details: dict[str, Any],
        metadata: dict[str, Any],
        navigation_mode: NotificationNavigationMode | None = None,
    ) -> AppNotification | None:
        now = datetime.now(timezone.utc)
        updates: dict[str, Any] = {
            "title": title,
            "message": message,
            "target": dict(target),
            "details": dict(details),
            "metadata": dict(metadata),
            "updated_at": now,
        }
        if navigation_mode is not None:
            updates["navigation_mode"] = navigation_mode.value
        self._collection.update_one(
            {"_id": notification_id},
            {"$set": updates},
        )
        document = self._collection.find_one({"_id": notification_id})
        return None if document is None else self._to_model(document)

    def get_notification_for_user(self, *, notification_id: str, user_id: str) -> AppNotification | None:
        document = self._collection.find_one(
            {
                "_id": notification_id,
                "recipient_user_ids": user_id,
            }
        )
        return None if document is None else self._to_model(document)

    def list_for_user(
        self,
        *,
        user_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[AppNotification], str | None]:
        query: dict[str, Any] = {"recipient_user_ids": user_id}
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]

        documents = list(
            self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return [self._to_model(document) for document in page], next_cursor

    def mark_read(self, *, notification_id: str, user_id: str) -> AppNotification | None:
        now = datetime.now(timezone.utc)
        self._collection.update_one(
            {
                "_id": notification_id,
                "recipient_user_ids": user_id,
            },
            {
                "$addToSet": {"read_by_user_ids": user_id},
                "$set": {"updated_at": now},
            },
        )
        return self.get_notification_for_user(notification_id=notification_id, user_id=user_id)

    def unread_count_for_user(self, *, user_id: str) -> int:
        return int(
            self._collection.count_documents(
                {
                    "recipient_user_ids": user_id,
                    "read_by_user_ids": {"$ne": user_id},
                }
            )
        )

    @staticmethod
    def _encode_cursor(document: dict[str, Any]) -> str:
        created_at = document["created_at"]
        created_at_iso = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return f"{created_at_iso}|{document['_id']}"

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        created_at_raw, notification_id = cursor.split("|", 1)
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        return created_at, notification_id

    @staticmethod
    def _to_model(document: dict[str, Any]) -> AppNotification:
        raw_category = str(document.get("category") or NotificationCategory.SYSTEM.value)
        raw_type = str(document.get("notification_type") or NotificationType.GENERAL.value)
        raw_navigation_mode = str(
            document.get("navigation_mode") or NotificationNavigationMode.DETAIL.value
        )
        return AppNotification(
            id=str(document["_id"]),
            category=NotificationCategory(raw_category)
            if raw_category in NotificationCategory._value2member_map_
            else NotificationCategory.SYSTEM,
            notification_type=NotificationType(raw_type)
            if raw_type in NotificationType._value2member_map_
            else NotificationType.GENERAL,
            title=str(document.get("title") or "Notification"),
            message=str(document.get("message") or ""),
            navigation_mode=NotificationNavigationMode(raw_navigation_mode)
            if raw_navigation_mode in NotificationNavigationMode._value2member_map_
            else NotificationNavigationMode.DETAIL,
            recipient_user_ids=[str(item) for item in list(document.get("recipient_user_ids") or [])],
            read_by_user_ids=[str(item) for item in list(document.get("read_by_user_ids") or [])],
            target=dict(document.get("target") or {}),
            details=dict(document.get("details") or {}),
            metadata=dict(document.get("metadata") or {}),
            idempotency_key=(
                str(document["idempotency_key"])
                if document.get("idempotency_key") is not None
                else None
            ),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
