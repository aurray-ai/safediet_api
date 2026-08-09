from __future__ import annotations

import logging
import math
from itertools import product
from typing import Any

from app.services.meal_inventory_reconciliation_service import MealInventoryReconciliationService
from app.services.meal_plan_cart_service import MealPlanCartService
from app.services.meal_plan_costing_service import MealPlanCostingService

logger = logging.getLogger(__name__)


class MealPlanOptimizationService:
    def __init__(
        self,
        *,
        costing_service: MealPlanCostingService,
        inventory_service: MealInventoryReconciliationService,
        cart_service: MealPlanCartService,
    ) -> None:
        self._costing_service = costing_service
        self._inventory_service = inventory_service
        self._cart_service = cart_service

    def rank_bundles(
        self,
        *,
        slot_candidates: dict[str, list[dict[str, Any]]],
        user_context: dict[str, Any],
        pantry_items: list[Any],
        country_code: str | None,
        requested_culture: str | None,
        max_bundles: int = 3,
    ) -> list[dict[str, Any]]:
        slots = [slot for slot, candidates in slot_candidates.items() if candidates]
        if not slots:
            return []

        candidate_cap = self._candidate_cap_for_slots(slot_count=len(slots))
        bundle_candidates = [list(slot_candidates[slot])[:candidate_cap] for slot in slots]
        ranked: list[dict[str, Any]] = []
        household_size = max(int(user_context.get("household_size") or 1), 1)
        weekly_budget = self._normalized_int(user_context.get("weekly_budget"))
        daily_budget_window = (weekly_budget / 7.0) if weekly_budget is not None and weekly_budget > 0 else None
        explored_combinations = math.prod(len(candidates) for candidates in bundle_candidates)
        logger.info(
            "meal_plan_optimization.rank_bundles.start slots=%s slot_count=%s candidate_cap=%s explored_combinations=%s max_bundles=%s",
            ",".join(slots) or "-",
            len(slots),
            candidate_cap,
            explored_combinations,
            max_bundles,
        )

        for index, bundle in enumerate(product(*bundle_candidates), start=1):
            meals_by_slot = {
                slot: dict(meal)
                for slot, meal in zip(slots, bundle, strict=False)
            }
            demand_summary = self._costing_service.build_product_demands(
                meals_by_slot=meals_by_slot,
                household_size=household_size,
            )
            inventory_summary = self._inventory_service.reconcile(
                product_demands=list(demand_summary.get("product_demands") or []),
                pantry_items=pantry_items,
            )
            cart_summary = self._costing_service.summarize_cart(
                shortages=list(inventory_summary.get("shortages") or []),
                products_by_id=dict(demand_summary.get("products_by_id") or {}),
                country_code=country_code,
                target_budget=daily_budget_window,
            )
            planned_meals = [
                {
                    "slot": slot,
                    "meal_id": meal.get("id"),
                    "meal_name": meal.get("name"),
                    "meal_source": "catalog",
                    "created_meal_draft": None,
                }
                for slot, meal in meals_by_slot.items()
            ]
            totals = self._compute_totals(meals_by_slot)
            bundle_summary = self._cart_service.build_bundle_summary(
                planned_meals=planned_meals,
                household_size=household_size,
                weekly_budget=weekly_budget,
                shared_product_count=int(demand_summary.get("shared_product_count") or 0),
                cart_summary=cart_summary,
            )
            score, score_breakdown = self._score_bundle(
                meals_by_slot=meals_by_slot,
                totals=totals,
                bundle_summary=bundle_summary,
                inventory_summary=inventory_summary,
                user_context=user_context,
                requested_culture=requested_culture,
            )
            ranked.append(
                {
                    "bundle_id": f"bundle-{index}",
                    "score": score,
                    "score_breakdown": score_breakdown,
                    "planned_meals": planned_meals,
                    "meals_by_slot": meals_by_slot,
                    "totals": totals,
                    "bundle_summary": bundle_summary,
                    "inventory_summary": inventory_summary,
                    "cart_summary": cart_summary,
                }
            )

        ranked.sort(
            key=lambda item: (
                float(item.get("score") or 0),
                -float((item.get("cart_summary") or {}).get("estimated_total_cost") or 0),
            ),
            reverse=True,
        )
        logger.info(
            "meal_plan_optimization.rank_bundles.completed slots=%s explored_combinations=%s returned=%s",
            ",".join(slots) or "-",
            explored_combinations,
            min(len(ranked), max_bundles),
        )
        return ranked[:max_bundles]

    @staticmethod
    def _candidate_cap_for_slots(*, slot_count: int) -> int:
        if slot_count >= 4:
            return 2
        if slot_count >= 3:
            return 3
        return 5

    def _score_bundle(
        self,
        *,
        meals_by_slot: dict[str, dict[str, Any]],
        totals: dict[str, Any],
        bundle_summary: dict[str, Any],
        inventory_summary: dict[str, Any],
        user_context: dict[str, Any],
        requested_culture: str | None,
    ) -> tuple[float, dict[str, Any]]:
        score = 0.0
        breakdown: dict[str, Any] = {}

        weekly_budget = self._normalized_int(user_context.get("weekly_budget"))
        estimated_total_cost = float(bundle_summary.get("estimated_total_cost") or 0)
        if weekly_budget is not None and weekly_budget > 0:
            daily_budget = weekly_budget / 7.0
            budget_delta = daily_budget - estimated_total_cost
            budget_score = 16.0 if budget_delta >= 0 else max(-8.0, budget_delta)
            score += budget_score
            breakdown["budget_score"] = round(budget_score, 2)

        if bundle_summary.get("budget_status") in {"within_budget", "near_budget"}:
            budget_fit_bonus = 4.0 if bundle_summary.get("budget_status") == "within_budget" else 2.0
            score += budget_fit_bonus
            breakdown["budget_fit_bonus"] = budget_fit_bonus

        if bool((bundle_summary.get("estimated_total_cost") or 0) > 0) and bool(
            (inventory_summary.get("used_items_count") or 0) > 0
        ):
            pantry_efficiency_bonus = 2.0
            score += pantry_efficiency_bonus
            breakdown["pantry_efficiency_bonus"] = pantry_efficiency_bonus

        pantry_score = min(int(inventory_summary.get("used_items_count") or 0) * 4.0, 20.0)
        score += pantry_score
        breakdown["pantry_score"] = pantry_score

        shared_product_score = min(int(bundle_summary.get("shared_product_count") or 0) * 6.0, 18.0)
        score += shared_product_score
        breakdown["shared_product_score"] = shared_product_score

        household_size = max(int(user_context.get("household_size") or 1), 1)
        household_fit = 0.0
        for meal in meals_by_slot.values():
            servings = self._normalized_float(meal.get("servings")) or 1.0
            household_fit += max(0.0, 6.0 - abs(servings - household_size) * 2.0)
        score += household_fit
        breakdown["household_fit_score"] = round(household_fit, 2)

        goal_score = self._goal_fit_score(goal=str(user_context.get("goal") or ""), totals=totals)
        score += goal_score
        breakdown["goal_score"] = round(goal_score, 2)

        culture_score = 0.0
        target_cultures = [requested_culture] if requested_culture else list(user_context.get("culture_preferences") or [])
        normalized_targets = {
            str(item).strip().lower()
            for item in target_cultures
            if str(item).strip()
        }
        if normalized_targets:
            for meal in meals_by_slot.values():
                meal_cultures = {
                    str(item).strip().lower()
                    for item in list(meal.get("culture_tags") or [])
                    if str(item).strip()
                }
                if meal_cultures & normalized_targets:
                    culture_score += 3.0
        score += culture_score
        breakdown["culture_score"] = round(culture_score, 2)
        breakdown["total_score"] = round(score, 2)
        return round(score, 2), breakdown

    @staticmethod
    def _compute_totals(meals_by_slot: dict[str, dict[str, Any]]) -> dict[str, Any]:
        calories = 0
        protein_g = 0.0
        carbs_g = 0.0
        fat_g = 0.0
        for meal in meals_by_slot.values():
            summary = dict(meal.get("nutrition_summary") or {})
            calories += int(summary.get("calories") or 0)
            protein_g += float(summary.get("protein_g") or 0)
            carbs_g += float(summary.get("carbs_g") or 0)
            fat_g += float(summary.get("fat_g") or 0)
        return {
            "calories": calories,
            "protein_g": round(protein_g, 1),
            "carbs_g": round(carbs_g, 1),
            "fat_g": round(fat_g, 1),
        }

    @staticmethod
    def _goal_fit_score(*, goal: str, totals: dict[str, Any]) -> float:
        normalized_goal = str(goal or "").strip().lower()
        calories = int(totals.get("calories") or 0)
        protein_g = float(totals.get("protein_g") or 0)
        if normalized_goal in {"weight_gain", "build_muscle", "muscle_building"}:
            return min(max((protein_g - 40) * 0.25, 0.0), 16.0) + min(max((calories - 1200) / 120.0, 0.0), 10.0)
        if normalized_goal in {"lose_weight", "weight_loss"}:
            calorie_component = 10.0 if calories <= 1800 else max(0.0, 10.0 - ((calories - 1800) / 150.0))
            protein_component = min(max((protein_g - 35) * 0.2, 0.0), 8.0)
            return calorie_component + protein_component
        if normalized_goal == "maintain":
            calorie_gap = abs(calories - 1800)
            return max(0.0, 12.0 - (calorie_gap / 120.0))
        return 0.0

    @staticmethod
    def _normalized_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
