from __future__ import annotations

from typing import Any


class MealPlanCartService:
    def build_bundle_summary(
        self,
        *,
        planned_meals: list[dict[str, Any]],
        household_size: int,
        weekly_budget: int | None,
        shared_product_count: int,
        cart_summary: dict[str, Any],
        meal_count: int | None = None,
        period_days: int = 1,
    ) -> dict[str, Any]:
        estimated_total_cost = float(cart_summary.get("estimated_total_cost") or 0)
        budget_status = "unknown"
        if weekly_budget is not None and weekly_budget > 0:
            budget_window = weekly_budget * (max(period_days, 1) / 7.0)
            if estimated_total_cost <= budget_window:
                budget_status = "within_budget"
            elif estimated_total_cost <= budget_window * 1.2:
                budget_status = "near_budget"
            else:
                budget_status = "over_budget"
        return {
            "household_size": household_size,
            "meal_count": meal_count if meal_count is not None else len(planned_meals),
            "shared_product_count": shared_product_count,
            "estimated_total_cost": estimated_total_cost,
            "formatted_estimated_total_cost": cart_summary.get("formatted_estimated_total_cost"),
            "currency_code": cart_summary.get("currency_code"),
            "budget_status": budget_status,
        }
