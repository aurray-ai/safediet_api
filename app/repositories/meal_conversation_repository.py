from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection


class MealConversationRepository:
    def __init__(
        self,
        conversations_collection: Collection[dict[str, Any]],
        messages_collection: Collection[dict[str, Any]],
    ) -> None:
        self._conversations = conversations_collection
        self._messages = messages_collection

    def create_conversation(
        self,
        *,
        user_id: str,
        user_goal: str | None,
        agent_type: str,
        status: str,
        current_summary: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "user_goal": user_goal,
            "agent_type": agent_type,
            "status": status,
            "current_summary": current_summary,
            "created_at": now,
            "updated_at": now,
            "last_message_at": None,
            "message_count": 0,
        }
        self._conversations.insert_one(document)
        return document

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._conversations.find_one({"_id": conversation_id})

    def find_reusable_conversation(
        self,
        *,
        user_id: str,
        user_goal: str,
    ) -> dict[str, Any] | None:
        return self._conversations.find_one(
            {"user_id": user_id, "user_goal": user_goal},
            sort=[("updated_at", DESCENDING), ("_id", DESCENDING)],
        )

    def append_message(
        self,
        *,
        conversation_id: str,
        role: str,
        text: str,
        ui_blocks: list[dict[str, Any]],
        quick_actions: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "conversation_id": conversation_id,
            "role": role,
            "text": text,
            "ui_blocks": ui_blocks,
            "metadata": metadata or {},
            "created_at": now,
        }
        if quick_actions:
            document["quick_actions"] = quick_actions
        self._messages.insert_one(document)
        self._conversations.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                    "latest_message_id": document["_id"],
                },
                "$inc": {"message_count": 1},
            },
        )
        return document

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        cursor = self._messages.find({"conversation_id": conversation_id}).sort(
            [("created_at", ASCENDING), ("_id", ASCENDING)]
        )
        return list(cursor)

    def list_recent_messages(self, conversation_id: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        documents = list(
            self._messages.find({"conversation_id": conversation_id})
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return list(reversed(documents))

    def list_messages_page(
        self,
        conversation_id: str,
        *,
        before: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        query: dict[str, Any] = {"conversation_id": conversation_id}
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]

        cursor = (
            self._messages.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        documents = list(cursor)
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return list(reversed(page)), next_cursor

    def update_conversation_summary(
        self,
        *,
        conversation_id: str,
        user_goal: str | None,
        agent_type: str,
        status: str,
        current_summary: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        self._conversations.update_one(
            {"_id": conversation_id},
            {
                "$set": {
                    "user_goal": user_goal,
                    "agent_type": agent_type,
                    "status": status,
                    "current_summary": current_summary,
                    "updated_at": now,
                }
            },
        )
        return self.get_conversation(conversation_id)

    def store_turn_result(
        self,
        *,
        conversation_id: str,
        user_goal: str | None,
        agent_type: str,
        status: str,
        current_summary: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self.update_conversation_summary(
            conversation_id=conversation_id,
            user_goal=user_goal,
            agent_type=agent_type,
            status=status,
            current_summary=current_summary,
        )

    def get_current_conversation(
        self,
        *,
        user_id: str,
        user_goal: str | None = None,
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {"user_id": user_id, "status": "active"}
        if user_goal is not None:
            query["user_goal"] = user_goal

        return self._conversations.find_one(
            query,
            sort=[("updated_at", DESCENDING), ("_id", DESCENDING)],
        )

    def list_recent_conversations(self, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        cursor = (
            self._conversations.find({"user_id": user_id})
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return list(cursor)

    def list_conversations_with_latest_blocks_before(
        self,
        *,
        before: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = (
            self._conversations.find(
                {
                    "status": "active",
                    "updated_at": {"$lte": before},
                    "current_summary.latest_ui_blocks.0": {"$exists": True},
                }
            )
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return list(cursor)

    def find_latest_message_block_by_snapshot_id(
        self,
        *,
        conversation_id: str,
        snapshot_id: str,
    ) -> tuple[str | None, str | None]:
        document = self._messages.find_one(
            {
                "conversation_id": conversation_id,
                "ui_blocks.payload.snapshot_id": snapshot_id,
            },
            sort=[("created_at", DESCENDING), ("_id", DESCENDING)],
        )
        if document is None:
            return None, None

        for block in list(document.get("ui_blocks") or []):
            payload = dict(block.get("payload") or {})
            if str(payload.get("snapshot_id") or "").strip() == snapshot_id:
                return str(document["_id"]), str(block.get("id") or "")
        return str(document["_id"]), None

    @staticmethod
    def _encode_cursor(document: dict[str, Any]) -> str:
        created_at = document["created_at"]
        created_at_iso = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return f"{created_at_iso}|{document['_id']}"

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        try:
            created_at_raw, message_id = cursor.split("|", 1)
        except ValueError as exc:
            raise ValueError("Invalid message cursor.") from exc

        normalized = created_at_raw.replace("Z", "+00:00")
        try:
            created_at = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("Invalid message cursor timestamp.") from exc
        return created_at, message_id
