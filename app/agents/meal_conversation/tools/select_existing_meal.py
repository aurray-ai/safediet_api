from __future__ import annotations

from typing import Any


class SelectExistingMealTool:
    name = "select_existing_meal"
    description = (
        "Commit to one existing catalog meal from previously retrieved candidates. "
        "Use this after semantic_search_meals once you are ready to choose a single meal_id."
    )

    def execute(
        self,
        *,
        slot: str,
        selected_meal_id: str,
        candidate_meal_ids: list[str] | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        allowed_ids = set(candidate_meal_ids or [])
        if allowed_ids and selected_meal_id not in allowed_ids:
            return {
                "error": "Selected meal was not in the retrieved candidate set.",
                "selected_meal_id": selected_meal_id,
            }
        return {
            "slot": slot,
            "selected_meal_id": selected_meal_id,
            "rationale": rationale,
        }
