from __future__ import annotations

from datetime import datetime
from typing import Any

from app.cache.cache_keys import (
    planner_conversation,
    planner_current_conversation,
    planner_recent_messages,
)
from app.cache.redis_cache import RedisCache
from app.repositories.meal_conversation_repository import MealConversationRepository


class CachedMealConversationRepository(MealConversationRepository):
    def __init__(
        self,
        base_repository: MealConversationRepository,
        cache: RedisCache,
        *,
        conversation_ttl_seconds: int,
        recent_messages_ttl_seconds: int,
        recent_messages_limit: int,
    ) -> None:
        super().__init__(base_repository._conversations, base_repository._messages)
        self._base_repository = base_repository
        self._cache = cache
        self._conversation_ttl_seconds = conversation_ttl_seconds
        self._recent_messages_ttl_seconds = recent_messages_ttl_seconds
        self._recent_messages_limit = max(recent_messages_limit, 1)

    def create_conversation(
        self,
        *,
        user_id: str,
        user_goal: str | None,
        agent_type: str,
        status: str,
        current_summary: dict[str, Any],
    ) -> dict[str, Any]:
        document = self._base_repository.create_conversation(
            user_id=user_id,
            user_goal=user_goal,
            agent_type=agent_type,
            status=status,
            current_summary=current_summary,
        )
        self._cache_conversation(document)
        return document

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        cached_document = self._cache.get_json(planner_conversation(conversation_id))
        if isinstance(cached_document, dict):
            return cached_document

        document = self._base_repository.get_conversation(conversation_id)
        if document is not None:
            self._cache_conversation(document)
        return document

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
        document = self._base_repository.append_message(
            conversation_id=conversation_id,
            role=role,
            text=text,
            ui_blocks=ui_blocks,
            quick_actions=quick_actions,
            metadata=metadata,
        )
        self._append_recent_message(document)
        return document

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._base_repository.list_messages(conversation_id)

    def list_recent_messages(self, conversation_id: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        cached_messages = self._cache.get_json(planner_recent_messages(conversation_id))
        if isinstance(cached_messages, list):
            return cached_messages[-limit:]

        hydrate_limit = max(limit, self._recent_messages_limit)
        messages = self._base_repository.list_recent_messages(conversation_id, limit=hydrate_limit)
        self._cache_recent_messages(conversation_id, messages)
        return messages[-limit:]

    def list_messages_page(
        self,
        conversation_id: str,
        *,
        before: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        return self._base_repository.list_messages_page(
            conversation_id,
            before=before,
            limit=limit,
        )

    def find_latest_message_block_by_snapshot_id(
        self,
        *,
        conversation_id: str,
        snapshot_id: str,
    ) -> tuple[str | None, str | None]:
        return self._base_repository.find_latest_message_block_by_snapshot_id(
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
        )

    def update_conversation_summary(
        self,
        *,
        conversation_id: str,
        user_goal: str | None,
        agent_type: str,
        status: str,
        current_summary: dict[str, Any],
    ) -> dict[str, Any] | None:
        previous_document = self.get_conversation(conversation_id)
        document = self._base_repository.update_conversation_summary(
            conversation_id=conversation_id,
            user_goal=user_goal,
            agent_type=agent_type,
            status=status,
            current_summary=current_summary,
        )
        self._invalidate_current_conversation_cache(previous_document)
        if document is not None:
            self._cache_conversation(document)
        return document

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
        cached_document = self._cache.get_json(planner_current_conversation(user_id, user_goal))
        if isinstance(cached_document, dict):
            return cached_document

        document = self._base_repository.get_current_conversation(
            user_id=user_id,
            user_goal=user_goal,
        )
        if document is not None:
            self._cache_conversation(document)
        return document

    def find_reusable_conversation(
        self,
        *,
        user_id: str,
        user_goal: str,
    ) -> dict[str, Any] | None:
        cache_key = planner_current_conversation(user_id, user_goal)
        cached_document = self._cache.get_json(cache_key)
        if isinstance(cached_document, dict):
            return cached_document

        document = self._base_repository.find_reusable_conversation(
            user_id=user_id,
            user_goal=user_goal,
        )
        if document is not None:
            self._cache_conversation(document)
        return document

    def list_recent_conversations(self, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._base_repository.list_recent_conversations(user_id=user_id, limit=limit)

    def list_conversations_with_latest_blocks_before(
        self,
        *,
        before: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._base_repository.list_conversations_with_latest_blocks_before(
            before=before,
            limit=limit,
        )

    def _cache_conversation(self, document: dict[str, Any]) -> None:
        self._cache.set_json(
            planner_conversation(str(document["_id"])),
            document,
            ttl_seconds=self._conversation_ttl_seconds,
        )

        current_keys = self._current_conversation_keys(document)
        if not current_keys:
            return
        for key in current_keys:
            self._cache.set_json(key, document, ttl_seconds=self._conversation_ttl_seconds)

    def _append_recent_message(self, document: dict[str, Any]) -> None:
        cache_key = planner_recent_messages(str(document["conversation_id"]))
        cached_messages = self._cache.get_json(cache_key)
        if not isinstance(cached_messages, list):
            return

        next_messages = [*cached_messages, document][-self._recent_messages_limit :]
        self._cache_recent_messages(str(document["conversation_id"]), next_messages)

    def _cache_recent_messages(self, conversation_id: str, messages: list[dict[str, Any]]) -> None:
        self._cache.set_json(
            planner_recent_messages(conversation_id),
            messages[-self._recent_messages_limit :],
            ttl_seconds=self._recent_messages_ttl_seconds,
        )

    def _invalidate_current_conversation_cache(self, document: dict[str, Any] | None) -> None:
        keys = self._current_conversation_keys(document)
        if keys:
            self._cache.delete_many(*keys)

    @staticmethod
    def _current_conversation_keys(document: dict[str, Any] | None) -> list[str]:
        if document is None:
            return []
        if str(document.get("status")) != "active":
            return []

        user_id = str(document.get("user_id") or "")
        if not user_id:
            return []

        summary = document.get("current_summary") or {}
        user_goal = str(document.get("user_goal") or summary.get("user_goal") or "").strip() or None
        keys = [planner_current_conversation(user_id)]
        if user_goal:
            keys.append(planner_current_conversation(user_id, user_goal))
        return keys
