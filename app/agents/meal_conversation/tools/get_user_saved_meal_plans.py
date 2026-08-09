from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository


class GetUserSavedMealPlansTool:
    name = "get_user_saved_meal_plans"
    description = (
        "Load the current user's saved meal plans for context. "
        "Use this when the user asks about a meal they already saved, wants to review a prior plan, "
        "or wants to adjust something based on an existing saved plan."
    )

    def __init__(
        self,
        saved_meal_plan_repository: SavedMealPlanRepository,
        current_user_id_provider: Callable[[], str | None],
    ) -> None:
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._current_user_id_provider = current_user_id_provider

    def execute(
        self,
        *,
        limit: int = 5,
        view_mode: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        user_id = str(self._current_user_id_provider() or "").strip()
        if not user_id:
            return {"error": "No active user context is available for saved meal lookup."}

        capped_limit = max(1, min(limit, 20))
        items, total = self._saved_meal_plan_repository.list_saved_plans(
            user_id=user_id,
            view_mode=view_mode,
            effective_date=None,
            limit=max(capped_limit * 3, capped_limit),
        )
        normalized_query = str(query or "").strip().lower()
        if normalized_query:
            items = [item for item in items if self._matches_query(item=item, normalized_query=normalized_query)]

        sliced = items[:capped_limit]
        return {
            "total": total if not normalized_query else len(items),
            "items": [self._serialize_saved_plan(item) for item in sliced],
        }

    @staticmethod
    def _matches_query(*, item, normalized_query: str) -> bool:
        haystacks = [
            item.title,
            item.user_goal or "",
            item.requested_culture or "",
            " ".join(str(entry.get("meal_name") or "") for entry in item.planned_meals),
        ]
        return any(normalized_query in haystack.lower() for haystack in haystacks if haystack)

    @staticmethod
    def _serialize_saved_plan(item) -> dict[str, Any]:
        planned_meals = [
            {
                "slot": entry.get("slot"),
                "meal_id": entry.get("meal_id"),
                "meal_name": entry.get("meal_name"),
                "meal_source": entry.get("meal_source"),
            }
            for entry in list(item.planned_meals or [])
        ]
        payload = dict(item.plan_payload or {})
        return {
            "saved_plan_id": item.id,
            "title": item.title,
            "status": item.status,
            "view_mode": item.view_mode,
            "plan_scope": item.plan_scope,
            "effective_date": item.effective_date.isoformat() if item.effective_date else None,
            "week_start": item.week_start.isoformat() if item.week_start else None,
            "week_end": item.week_end.isoformat() if item.week_end else None,
            "meal_type": item.meal_type.value if item.meal_type else None,
            "requested_culture": item.requested_culture,
            "user_goal": item.user_goal,
            "source_snapshot_id": item.source_snapshot_id,
            "source_conversation_id": item.source_conversation_id,
            "updated_at": item.updated_at.isoformat(),
            "planned_meals": planned_meals,
            "slots": [entry.get("slot") for entry in planned_meals if entry.get("slot")],
            "meal_names": [entry.get("meal_name") for entry in planned_meals if entry.get("meal_name")],
            "totals": dict(payload.get("totals") or {}),
            "tracked_text": payload.get("tracked_text"),
            "sections": list(payload.get("sections") or []),
        }
