from __future__ import annotations

from typing import Any


def review_guardrails(
    *,
    selected_meal_details: dict[str, dict[str, Any]] | None,
    created_meal_drafts: dict[str, dict[str, Any]] | None,
    user_context: dict[str, Any],
    final_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    issues: list[str] = []

    allergies = {str(item).strip().lower() for item in user_context.get("allergies", [])}

    for slot, selected_meal_detail in (selected_meal_details or {}).items():
        meal = selected_meal_detail.get("meal") or {}
        ingredient_names = {
            str(item.get("name", "")).strip().lower()
            for item in meal.get("ingredient_items", [])
        }
        conflicts = sorted(
            allergy for allergy in allergies if allergy and any(allergy in ingredient for ingredient in ingredient_names)
        )
        if conflicts:
            issues.append(f"{slot.capitalize()} meal conflicts with allergies: {', '.join(conflicts)}.")

    for slot, created_meal_draft in (created_meal_drafts or {}).items():
        linked_product_ids = created_meal_draft.get("linked_product_ids") or []
        if not linked_product_ids:
            issues.append(f"{slot.capitalize()} created meal draft must link to at least one real grocery product.")
        recipe_steps = created_meal_draft.get("recipe_steps") or []
        if not recipe_steps:
            issues.append(f"{slot.capitalize()} created meal draft is missing recipe steps.")
        ingredient_items = created_meal_draft.get("ingredient_items") or []
        if not ingredient_items:
            issues.append(f"{slot.capitalize()} created meal draft is missing ingredient items.")

    if final_plan is None:
        issues.append("No final plan was committed by the agent.")
    elif not final_plan.get("planned_meals"):
        issues.append("No planned meals were committed for the requested slots.")

    return {
        "passed": not issues,
        "issues": issues,
        "severity": "high" if issues else "none",
    }
