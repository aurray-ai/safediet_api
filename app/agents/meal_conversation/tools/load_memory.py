from __future__ import annotations

from typing import Any

from app.repositories.meal_conversation_repository import MealConversationRepository


class LoadMemoryTool:
    name = "load_conversation_memory"
    description = (
        "Load recent conversation memory. "
        "Use this only when you need to avoid repeating rejected meals or to honor recent planner context."
    )

    def __init__(self, meal_conversation_repository: MealConversationRepository) -> None:
        self._meal_conversation_repository = meal_conversation_repository

    def execute(self, *, conversation_id: str, limit: int = 8) -> dict[str, Any]:
        sliced = self._meal_conversation_repository.list_recent_messages(
            conversation_id,
            limit=max(limit, 1),
        )
        return {
            "messages": [
                {
                    "role": message.get("role"),
                    "text": message.get("text", ""),
                    "metadata": message.get("metadata", {}),
                }
                for message in sliced
            ]
        }
