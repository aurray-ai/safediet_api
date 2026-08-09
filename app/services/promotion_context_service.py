from __future__ import annotations

from typing import Any

from app.models.user import User
from app.repositories.meal_conversation_repository import MealConversationRepository


class PromotionContextService:
    def __init__(self, meal_conversation_repository: MealConversationRepository) -> None:
        self._meal_conversation_repository = meal_conversation_repository

    def build_snapshot(self, *, user: User) -> dict[str, Any]:
        recent_conversations = self._meal_conversation_repository.list_recent_conversations(
            user_id=user.id,
            limit=3,
        )
        latest_conversation = recent_conversations[0] if recent_conversations else None
        latest_summary = dict((latest_conversation or {}).get("current_summary") or {})
        latest_conversation_id = str(latest_conversation["_id"]) if latest_conversation else None
        recent_messages = (
            self._meal_conversation_repository.list_recent_messages(latest_conversation_id, limit=6)
            if latest_conversation_id
            else []
        )

        profile_snapshot = {
            "name": user.name,
            "email": user.email,
            "user_types": [user_type.value for user_type in user.user_types],
        }
        preferences = dict(user.user_configuration or {})
        latest_plan_summary = self._resolve_latest_plan_summary(latest_summary)
        conversation_summary = latest_summary.get("last_assistant_preview") or latest_plan_summary

        return {
            "conversation_summary": conversation_summary,
            "recent_messages_summary": [
                {
                    "id": str(message.get("_id")),
                    "role": str(message.get("role") or ""),
                    "text": str(message.get("text") or "")[:400],
                    "created_at": message.get("created_at"),
                }
                for message in recent_messages
            ],
            "latest_plan_summary": latest_plan_summary,
            "profile_snapshot": profile_snapshot,
            "preference_snapshot": {
                "goal": preferences.get("goal"),
                "weekly_style": preferences.get("weekly_style"),
                "allergies": list(preferences.get("allergies") or []),
                "diet_rules": list(preferences.get("diet_rules") or []),
                "culture_preferences": list(preferences.get("culture_preferences") or []),
                "selected_plan_types": list(preferences.get("selected_plan_types") or []),
            },
            "eligibility_snapshot": {
                "has_recent_conversation": latest_conversation is not None,
                "recent_conversation_count": len(recent_conversations),
                "last_message_at": (latest_conversation or {}).get("last_message_at"),
            },
            "source_refs": {
                "latest_conversation_id": latest_conversation_id,
                "conversation_ids": [str(item.get("_id")) for item in recent_conversations],
            },
        }

    @staticmethod
    def _resolve_latest_plan_summary(latest_summary: dict[str, Any]) -> str | None:
        latest_ui_blocks = list(latest_summary.get("latest_ui_blocks") or [])
        for block in latest_ui_blocks:
            if str(block.get("block_type") or "") != "day_plan":
                continue
            payload = dict(block.get("payload") or {})
            tracked_text = str(payload.get("tracked_text") or "").strip()
            if tracked_text:
                return tracked_text
        return latest_summary.get("last_assistant_preview")

