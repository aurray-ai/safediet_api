from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.models.meal import Meal
from app.models.user import User
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_repository import MealRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.user_pantry_repository import UserPantryRepository
from app.schemas.meal_conversation import ConversationUIBlockResponse
from app.schemas.saved_meal_plan import (
    HomeMealPlanResponse,
    SavedMealPlanListResponse,
    SavedMealPlanResponse,
    SavedMealPlanSlotMutationRequest,
)
from app.services.meal_inventory_reconciliation_service import MealInventoryReconciliationService
from app.services.meal_plan_cart_service import MealPlanCartService
from app.services.meal_plan_costing_service import MealPlanCostingService
from app.services.meal_scaling_service import MealScalingService
from app.services.kitchen_service import KitchenService
from app.services.user_meal_usage_service import UserMealUsageService


class SavedMealPlanNotFoundError(Exception):
    pass


class SavedMealPlanMutationError(Exception):
    pass


class SavedMealPlanService:
    _HOME_VISIBLE_STATUSES = ("saved", "missing_groceries")

    def __init__(
        self,
        *,
        saved_meal_plan_repository: SavedMealPlanRepository,
        meal_repository: MealRepository,
        grocery_repository: GroceryRepository,
        user_pantry_repository: UserPantryRepository,
        kitchen_service: KitchenService,
        user_meal_usage_service: UserMealUsageService,
        meal_scaling_service: MealScalingService | None = None,
    ) -> None:
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._meal_repository = meal_repository
        self._grocery_repository = grocery_repository
        self._user_pantry_repository = user_pantry_repository
        self._kitchen_service = kitchen_service
        self._user_meal_usage_service = user_meal_usage_service
        self._meal_scaling_service = meal_scaling_service or MealScalingService()

    def list_saved_plans(
        self,
        *,
        current_user: User,
        view_mode: str | None,
        effective_date: date | None,
        limit: int,
    ) -> SavedMealPlanListResponse:
        items, total = self._saved_meal_plan_repository.list_saved_plans(
            user_id=current_user.id,
            view_mode=view_mode,
            effective_date=effective_date,
            limit=limit,
        )
        return SavedMealPlanListResponse(
            items=[
                SavedMealPlanResponse(
                    id=item.id,
                    title=item.title,
                    status=item.status,
                    view_mode=item.view_mode,
                    plan_scope=item.plan_scope,
                    effective_date=item.effective_date,
                    week_start=item.week_start,
                    week_end=item.week_end,
                    day_index=item.day_index,
                    parent_saved_plan_id=item.parent_saved_plan_id,
                    source_saved_plan_id=item.source_saved_plan_id,
                    linked_day_plan_ids=item.linked_day_plan_ids,
                    meal_type=item.meal_type,
                    country_code=item.country_code,
                    planned_meals=item.planned_meals,
                    plan_payload=self._response_payload(item),
                    requested_culture=item.requested_culture,
                    user_goal=item.user_goal,
                    source_snapshot_id=item.source_snapshot_id,
                    source_conversation_id=item.source_conversation_id,
                    agent_type=item.agent_type,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in items
            ],
            total=total,
        )

    def resolve_home_plan(
        self,
        *,
        current_user: User,
        selected_date: date,
        view_mode: str,
        include_drafts: bool = False,
    ) -> HomeMealPlanResponse:
        if include_drafts:
            return self.resolve_planner_plan(
                user_id=current_user.id,
                selected_date=selected_date,
                view_mode=view_mode,
                weekly_budget=self._current_user_weekly_budget(current_user),
                household_size=self._current_user_household_size(current_user),
            )

        normalized_view_mode = "week" if str(view_mode).lower() == "week" else "day"
        week_start, week_end = self._week_bounds(selected_date)
        weekly_plan = self._resolve_saved_weekly_plan(
            user_id=current_user.id,
            selected_date=selected_date,
        )
        if normalized_view_mode == "day":
            if weekly_plan is not None:
                day_slice = self._day_slice_from_weekly_plan(
                    weekly_plan=weekly_plan,
                    selected_date=selected_date,
                    user_id=current_user.id,
                    weekly_budget=self._current_user_weekly_budget(current_user),
                    household_size=self._current_user_household_size(current_user),
                )
                if day_slice is not None:
                    return HomeMealPlanResponse(
                        selected_date=selected_date,
                        view_mode="day",
                        resolution_mode="saved_weekly_plan_day_slice",
                        ui_block=day_slice,
                    )

            saved_plan = self._saved_meal_plan_repository.get_saved_day_plan_for_date(
                user_id=current_user.id,
                effective_date=selected_date,
                allowed_statuses=list(self._HOME_VISIBLE_STATUSES),
            )
            if not self._saved_plan_has_allocated_slots(saved_plan):
                saved_plan = None
            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="day",
                resolution_mode="saved_day_plan" if saved_plan is not None else "empty_day",
                ui_block=(
                    self._saved_plan_ui_block(
                        saved_plan,
                        user_id=current_user.id,
                        weekly_budget=self._current_user_weekly_budget(current_user),
                        household_size=self._current_user_household_size(current_user),
                    )
                    if saved_plan is not None
                    else None
                ),
            )

        if weekly_plan is not None:
            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="week",
                resolution_mode="saved_weekly_plan",
                ui_block=self._saved_plan_ui_block(
                    weekly_plan,
                    user_id=current_user.id,
                    weekly_budget=self._current_user_weekly_budget(current_user),
                    household_size=self._current_user_household_size(current_user),
                ),
            )

        day_plans = self._saved_meal_plan_repository.list_saved_day_plans_in_range(
            user_id=current_user.id,
            start_date=week_start,
            end_date=week_end,
            allowed_statuses=list(self._HOME_VISIBLE_STATUSES),
        )
        day_plans = [plan for plan in day_plans if self._saved_plan_has_allocated_slots(plan)]
        if day_plans:
            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="week",
                resolution_mode="composed_from_day_plans",
                ui_block=self._compose_weekly_ui_block(
                    selected_date=selected_date,
                    week_start=week_start,
                    week_end=week_end,
                    saved_day_plans=day_plans,
                    user_id=current_user.id,
                    weekly_budget=self._current_user_weekly_budget(current_user),
                    household_size=self._current_user_household_size(current_user),
                ),
            )

        return HomeMealPlanResponse(
            selected_date=selected_date,
            view_mode="week",
            resolution_mode="empty_week",
            ui_block=None,
        )

    def resolve_planner_plan(
        self,
        *,
        user_id: str,
        selected_date: date,
        view_mode: str,
        weekly_budget: int | None = None,
        household_size: int | None = None,
    ) -> HomeMealPlanResponse:
        normalized_view_mode = "week" if str(view_mode).lower() == "week" else "day"
        planner_statuses = ["draft", "saved", "missing_groceries"]
        weekly_plan = self._resolve_planner_weekly_plan(
            user_id=user_id,
            selected_date=selected_date,
        )

        if normalized_view_mode == "day":
            if weekly_plan is not None:
                day_slice = self._day_slice_from_weekly_plan(
                    weekly_plan=weekly_plan,
                    selected_date=selected_date,
                    user_id=user_id,
                    weekly_budget=weekly_budget,
                    household_size=household_size,
                )
                if day_slice is not None:
                    resolution_mode = (
                        "draft_weekly_plan_day_slice"
                        if str(weekly_plan.status or "").lower() == "draft"
                        else "saved_weekly_plan_day_slice"
                    )
                    return HomeMealPlanResponse(
                        selected_date=selected_date,
                        view_mode="day",
                        resolution_mode=resolution_mode,
                        ui_block=day_slice,
                    )

            day_plan = self._saved_meal_plan_repository.get_saved_day_plan_for_date(
                user_id=user_id,
                effective_date=selected_date,
                allowed_statuses=planner_statuses,
            )
            if not self._saved_plan_has_allocated_slots(day_plan):
                day_plan = None
            if day_plan is not None:
                normalized_status = str(day_plan.status or "").lower()
                return HomeMealPlanResponse(
                    selected_date=selected_date,
                    view_mode="day",
                    resolution_mode="draft_day_plan" if normalized_status == "draft" else "saved_day_plan",
                    ui_block=self._saved_plan_ui_block(
                        day_plan,
                        user_id=user_id,
                        weekly_budget=weekly_budget,
                        household_size=household_size,
                    ),
                )

            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="day",
                resolution_mode="empty_day",
                ui_block=None,
            )

        if weekly_plan is not None:
            normalized_status = str(weekly_plan.status or "").lower()
            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="week",
                resolution_mode="draft_weekly_plan" if normalized_status == "draft" else "saved_weekly_plan",
                ui_block=self._saved_plan_ui_block(
                    weekly_plan,
                    user_id=user_id,
                    weekly_budget=weekly_budget,
                    household_size=household_size,
                ),
            )

        week_start, week_end = self._week_bounds(selected_date)
        day_plans = self._preferred_planner_day_plans_in_range(
            user_id=user_id,
            start_date=week_start,
            end_date=week_end,
        )
        if day_plans:
            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="week",
                resolution_mode="draft_composed_from_day_plans",
                ui_block=self._compose_weekly_ui_block(
                    selected_date=selected_date,
                    week_start=week_start,
                    week_end=week_end,
                    saved_day_plans=day_plans,
                    user_id=user_id,
                    weekly_budget=weekly_budget,
                    household_size=household_size,
                ),
            )

        return HomeMealPlanResponse(
            selected_date=selected_date,
            view_mode="week",
            resolution_mode="empty_week",
            ui_block=None,
        )

    def publish_saved_plan(
        self,
        *,
        user_id: str,
        saved_plan_id: str,
    ):
        saved_plan = self._saved_meal_plan_repository.get_saved_plan(
            user_id=user_id,
            saved_plan_id=saved_plan_id,
        )
        if saved_plan is None:
            raise SavedMealPlanNotFoundError
        if str(saved_plan.status or "").lower() != "draft":
            return saved_plan

        include_saved_plan_id = saved_plan.source_saved_plan_id or saved_plan.id
        refreshed_payload = self._refresh_plan_supporting_summaries(
            user_id=saved_plan.user_id,
            payload_data=dict(saved_plan.plan_payload or {}),
            country_code=(
                saved_plan.country_code.value
                if saved_plan.country_code is not None
                else None
            ),
            household_size=self._normalized_positive_int(
                dict((saved_plan.plan_payload or {}).get("bundle_summary") or {}).get("household_size")
            ),
            include_saved_plan_id=include_saved_plan_id,
        )
        has_shortages = bool(list(dict(refreshed_payload.get("inventory_summary") or {}).get("shortages") or []))
        refreshed_payload["state"] = "missing_groceries" if has_shortages else "saved"
        refreshed_payload["primary_action"] = None
        published_plan = self._upsert_saved_plan(
            existing_plan=saved_plan,
            payload_data=refreshed_payload,
        )
        if published_plan.view_mode == "week":
            published_plan = self._sync_or_create_weekly_child_plans(parent_saved_plan=published_plan)
        else:
            self._user_meal_usage_service.sync_saved_day_plan(saved_plan=published_plan)
        self._sync_kitchen_allocations_for_saved_plan(saved_plan=published_plan)
        return published_plan

    def mutate_slot(
        self,
        *,
        current_user: User,
        payload: SavedMealPlanSlotMutationRequest,
    ) -> HomeMealPlanResponse:
        selected_date = payload.effective_date
        target_plan = None

        if payload.saved_plan_id:
            target_plan = self._saved_meal_plan_repository.get_saved_plan(
                user_id=current_user.id,
                saved_plan_id=payload.saved_plan_id,
            )
            if target_plan is None:
                raise SavedMealPlanNotFoundError

        if selected_date is None and target_plan is not None:
            selected_date = target_plan.effective_date or target_plan.week_start

        if selected_date is None:
            raise SavedMealPlanMutationError("effective_date is required for slot updates.")

        if target_plan is None:
            target_plan = self._resolve_saved_weekly_plan(
                user_id=current_user.id,
                selected_date=selected_date,
            )
            if target_plan is None:
                target_plan = self._saved_meal_plan_repository.get_saved_day_plan_for_date(
                    user_id=current_user.id,
                    effective_date=selected_date,
                )

        if target_plan is not None:
            updated_plan = self._mutate_existing_saved_plan(
                current_user=current_user,
                saved_plan=target_plan,
                selected_date=selected_date,
                payload=payload,
            )
        else:
            updated_plan = self._create_and_mutate_saved_day_plan(
                current_user=current_user,
                selected_date=selected_date,
                payload=payload,
            )

        if updated_plan.status != "draft" and updated_plan.view_mode == "week":
            self._sync_weekly_child_plan_for_date(
                parent_saved_plan=updated_plan,
                selected_date=selected_date,
            )
        elif updated_plan.status != "draft" and updated_plan.view_mode == "day":
            self._user_meal_usage_service.sync_saved_day_plan(saved_plan=updated_plan)
        if updated_plan.status != "draft":
            self._sync_kitchen_allocations_for_saved_plan(saved_plan=updated_plan)

        if updated_plan.status == "draft":
            return self._draft_mutation_response(
                current_user=current_user,
                selected_date=selected_date,
                requested_view_mode=payload.view,
                saved_plan=updated_plan,
            )

        return self.resolve_home_plan(current_user=current_user, selected_date=selected_date, view_mode=payload.view)

    def list_saved_plan_kitchen(
        self,
        *,
        current_user: User,
        saved_plan_id: str,
    ):
        saved_plan = self._saved_meal_plan_repository.get_saved_plan(
            user_id=current_user.id,
            saved_plan_id=saved_plan_id,
        )
        if saved_plan is None:
            raise SavedMealPlanNotFoundError
        return self._kitchen_service.list_saved_plan_allocations(
            current_user=current_user,
            saved_plan_id=saved_plan_id,
        )

    def consume_saved_plan_kitchen_slot(
        self,
        *,
        current_user: User,
        saved_plan_id: str,
        payload,
    ):
        saved_plan = self._saved_meal_plan_repository.get_saved_plan(
            user_id=current_user.id,
            saved_plan_id=saved_plan_id,
        )
        if saved_plan is None:
            raise SavedMealPlanNotFoundError
        return self._kitchen_service.consume_saved_plan_slot(
            current_user=current_user,
            saved_plan_id=saved_plan_id,
            payload=payload,
        )

    def _resolve_saved_weekly_plan(
        self,
        *,
        user_id: str,
        selected_date: date,
    ):
        week_start, week_end = self._week_bounds(selected_date)
        weekly_plan = self._saved_meal_plan_repository.get_saved_weekly_plan_for_week(
            user_id=user_id,
            week_start=week_start,
            week_end=week_end,
            allowed_statuses=list(self._HOME_VISIBLE_STATUSES),
        )
        if weekly_plan is not None:
            return weekly_plan
        return self._saved_meal_plan_repository.get_saved_weekly_plan_covering_date(
            user_id=user_id,
            target_date=selected_date,
            allowed_statuses=list(self._HOME_VISIBLE_STATUSES),
        )

    def _resolve_planner_weekly_plan(
        self,
        *,
        user_id: str,
        selected_date: date,
    ):
        week_start, week_end = self._week_bounds(selected_date)
        for statuses in (["draft"], list(self._HOME_VISIBLE_STATUSES)):
            weekly_plan = self._saved_meal_plan_repository.get_saved_weekly_plan_for_week(
                user_id=user_id,
                week_start=week_start,
                week_end=week_end,
                allowed_statuses=statuses,
            )
            if self._saved_plan_has_allocated_slots(weekly_plan):
                return weekly_plan
            weekly_plan = self._saved_meal_plan_repository.get_saved_weekly_plan_covering_date(
                user_id=user_id,
                target_date=selected_date,
                allowed_statuses=statuses,
            )
            if self._saved_plan_has_allocated_slots(weekly_plan):
                return weekly_plan
            weekly_plan = self._resolve_recent_planner_weekly_plan_from_payload(
                user_id=user_id,
                selected_date=selected_date,
                allowed_statuses=statuses,
            )
            if self._saved_plan_has_allocated_slots(weekly_plan):
                return weekly_plan
        return None

    def _preferred_planner_day_plans_in_range(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> list[Any]:
        plans = self._saved_meal_plan_repository.list_saved_day_plans_in_range(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            allowed_statuses=["draft", *self._HOME_VISIBLE_STATUSES],
        )
        fallback_plans = self._resolve_recent_planner_day_plans_from_payload(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            allowed_statuses=["draft", *self._HOME_VISIBLE_STATUSES],
        )
        existing_ids = {plan.id for plan in plans}
        for fallback_plan in fallback_plans:
            if fallback_plan.id not in existing_ids:
                plans.append(fallback_plan)
        plans = [plan for plan in plans if self._saved_plan_has_allocated_slots(plan)]
        if not plans:
            return []

        def plan_priority(plan: Any) -> tuple[int, float]:
            normalized_status = str(plan.status or "").lower()
            status_priority = 0 if normalized_status == "draft" else 1
            return (status_priority, -plan.updated_at.timestamp())

        preferred_by_date: dict[date, Any] = {}
        for plan in sorted(plans, key=plan_priority):
            effective_date = self._saved_plan_effective_date(plan)
            if effective_date is None or effective_date in preferred_by_date:
                continue
            preferred_by_date[effective_date] = plan
        return [
            preferred_by_date[current_date]
            for current_date in sorted(preferred_by_date.keys())
        ]

    def _resolve_recent_planner_weekly_plan_from_payload(
        self,
        *,
        user_id: str,
        selected_date: date,
        allowed_statuses: list[str],
    ):
        recent_plans, _ = self._saved_meal_plan_repository.list_saved_plans(
            user_id=user_id,
            view_mode="week",
            limit=100,
        )
        allowed_status_set = {str(status).lower() for status in allowed_statuses}
        for plan in recent_plans:
            if str(plan.status or "").lower() not in allowed_status_set:
                continue
            week_start, week_end = self._saved_plan_week_bounds(plan)
            if week_start is None or week_end is None:
                continue
            if week_start <= selected_date <= week_end:
                return plan
        return None

    def _resolve_recent_planner_day_plans_from_payload(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
        allowed_statuses: list[str],
    ) -> list[Any]:
        recent_plans, _ = self._saved_meal_plan_repository.list_saved_plans(
            user_id=user_id,
            view_mode="day",
            limit=200,
        )
        allowed_status_set = {str(status).lower() for status in allowed_statuses}
        fallback_plans: list[Any] = []
        for plan in recent_plans:
            if str(plan.status or "").lower() not in allowed_status_set:
                continue
            effective_date = self._saved_plan_effective_date(plan)
            if effective_date is None or effective_date < start_date or effective_date > end_date:
                continue
            fallback_plans.append(plan)
        return fallback_plans

    def _mutate_existing_saved_plan(
        self,
        *,
        current_user: User,
        saved_plan,
        selected_date: date,
        payload: SavedMealPlanSlotMutationRequest,
    ):
        mutable_plan = self._ensure_mutable_saved_plan(saved_plan=saved_plan)
        if mutable_plan.view_mode == "week":
            mutated_payload = self._mutate_weekly_payload(
                payload_data=dict(mutable_plan.plan_payload or {}),
                selected_date=selected_date,
                payload=payload,
                target_state="draft",
            )
        else:
            mutated_payload = self._mutate_day_payload(
                payload_data=dict(mutable_plan.plan_payload or {}),
                payload=payload,
                target_state="draft",
            )
        mutated_payload = self._refresh_plan_supporting_summaries(
            user_id=current_user.id,
            payload_data=mutated_payload,
            country_code=(
                mutable_plan.country_code.value
                if mutable_plan.country_code is not None
                else None
            ),
            weekly_budget=self._current_user_weekly_budget(current_user),
            household_size=self._current_user_household_size(current_user),
            include_saved_plan_id=mutable_plan.source_saved_plan_id or mutable_plan.id,
        )

        return self._upsert_saved_plan(
            existing_plan=mutable_plan,
            payload_data=mutated_payload,
        )

    def _ensure_mutable_saved_plan(self, *, saved_plan):
        if str(saved_plan.status or "").lower() == "draft":
            return saved_plan

        existing_draft = self._saved_meal_plan_repository.get_latest_draft_derived_from_saved_plan(
            user_id=saved_plan.user_id,
            source_saved_plan_id=saved_plan.id,
            view_mode=saved_plan.view_mode,
            effective_date=saved_plan.effective_date,
            week_start=saved_plan.week_start,
            week_end=saved_plan.week_end,
        )
        if existing_draft is not None:
            return existing_draft

        draft_payload = dict(saved_plan.plan_payload or {})
        draft_snapshot_id = f"{saved_plan.source_snapshot_id}:draft:{uuid4().hex[:8]}"
        draft_payload["snapshot_id"] = draft_snapshot_id
        draft_payload["saved_plan_id"] = None
        draft_payload["state"] = "draft"
        draft_payload["saved_at"] = None
        draft_payload["primary_action"] = self._draft_primary_action(
            view_mode=str(draft_payload.get("view_mode") or saved_plan.view_mode or "day"),
            snapshot_id=draft_snapshot_id,
        )
        return self._saved_meal_plan_repository.upsert_saved_plan(
            user_id=saved_plan.user_id,
            title=str(draft_payload.get("title") or saved_plan.title or "Meal Plan"),
            status="draft",
            view_mode=str(draft_payload.get("view_mode") or saved_plan.view_mode or "day"),
            effective_date=saved_plan.effective_date,
            meal_type=saved_plan.meal_type.value if saved_plan.meal_type is not None else None,
            country_code=saved_plan.country_code.value if saved_plan.country_code is not None else None,
            planned_meals=self._planned_meals_from_payload(draft_payload),
            plan_payload=draft_payload,
            requested_culture=saved_plan.requested_culture,
            user_goal=saved_plan.user_goal,
            source_snapshot_id=draft_snapshot_id,
            source_conversation_id=saved_plan.source_conversation_id,
            agent_type=saved_plan.agent_type,
            plan_scope=saved_plan.plan_scope,
            week_start=saved_plan.week_start,
            week_end=saved_plan.week_end,
            day_index=saved_plan.day_index,
            parent_saved_plan_id=saved_plan.parent_saved_plan_id,
            source_saved_plan_id=saved_plan.id,
            linked_day_plan_ids=saved_plan.linked_day_plan_ids,
        )

    def _create_and_mutate_saved_day_plan(
        self,
        *,
        current_user: User,
        selected_date: date,
        payload: SavedMealPlanSlotMutationRequest,
    ):
        base_payload = self._empty_day_payload(selected_date)
        mutated_payload = self._mutate_day_payload(
            payload_data=base_payload,
            payload=payload,
            target_state="draft",
        )
        mutated_payload = self._refresh_plan_supporting_summaries(
            user_id=current_user.id,
            payload_data=mutated_payload,
            country_code=None,
            weekly_budget=self._current_user_weekly_budget(current_user),
            household_size=self._current_user_household_size(current_user),
        )
        return self._saved_meal_plan_repository.upsert_saved_plan(
            user_id=current_user.id,
            title=str(mutated_payload.get("title") or "Meal Plan"),
            view_mode="day",
            effective_date=selected_date,
            meal_type=None,
            country_code=None,
            planned_meals=self._planned_meals_from_payload(mutated_payload),
            plan_payload=mutated_payload,
            requested_culture=None,
            user_goal=str((current_user.user_configuration or {}).get("goal") or "").strip() or None,
            source_snapshot_id=str(mutated_payload.get("snapshot_id") or f"home-day-{selected_date.isoformat()}"),
            source_conversation_id="manual",
            agent_type="slot_mutation",
            plan_scope="standalone_day",
            status="draft",
        )

    def _mutate_day_payload(
        self,
        *,
        payload_data: dict[str, Any],
        payload: SavedMealPlanSlotMutationRequest,
        target_state: str,
    ) -> dict[str, Any]:
        sections = list(payload_data.get("sections") or [])
        updated_sections = self._mutate_sections(
            sections=sections,
            payload=payload,
        )
        summary = self._summarize_sections(updated_sections)

        updated_payload = dict(payload_data)
        updated_payload["view_mode"] = "day"
        updated_payload["state"] = target_state
        updated_payload["sections"] = updated_sections
        updated_payload["totals"] = self._totals_payload(summary)
        updated_payload["tracked_text"] = self._tracked_text(summary["meal_count"], scope="day")
        updated_payload["planned_meals"] = self._build_planned_meals_from_sections(updated_sections)
        if target_state == "draft":
            updated_payload["primary_action"] = self._draft_primary_action(
                view_mode="day",
                snapshot_id=str(updated_payload.get("snapshot_id") or payload_data.get("snapshot_id") or ""),
            )
        else:
            updated_payload["primary_action"] = None
        bundle_summary = dict(updated_payload.get("bundle_summary") or {})
        bundle_summary["meal_count"] = summary["meal_count"]
        updated_payload["bundle_summary"] = bundle_summary
        return updated_payload

    def _mutate_weekly_payload(
        self,
        *,
        payload_data: dict[str, Any],
        selected_date: date,
        payload: SavedMealPlanSlotMutationRequest,
        target_state: str,
    ) -> dict[str, Any]:
        selected_date_iso = selected_date.isoformat()
        day_objects = [dict(item) for item in list(payload_data.get("days") or []) if isinstance(item, dict)]
        snapshot_objects = [dict(item) for item in list(payload_data.get("daily_snapshots") or []) if isinstance(item, dict)]
        if not day_objects:
            raise SavedMealPlanMutationError("Weekly plan is missing day data.")

        target_day = next((item for item in day_objects if str(item.get("date") or "") == selected_date_iso), None)
        if target_day is None:
            raise SavedMealPlanMutationError("The selected day could not be found in this weekly plan.")

        resolved_sections = self._resolved_weekly_sections(
            day_objects=day_objects,
            snapshot_objects=snapshot_objects,
            selected_date_iso=selected_date_iso,
        )
        updated_sections = self._mutate_sections(
            sections=resolved_sections,
            payload=payload,
        )
        updated_day_summary = self._summarize_sections(updated_sections)
        should_keep_target_day = self._summary_has_allocated_slots(updated_day_summary)

        updated_day_objects: list[dict[str, Any]] = []
        for day_object in day_objects:
            if str(day_object.get("date") or "") == selected_date_iso:
                if should_keep_target_day:
                    updated_day_objects.append(
                        self._updated_week_day_object(
                            day_object=day_object,
                            sections=updated_sections,
                            summary=updated_day_summary,
                        )
                    )
            else:
                updated_day_objects.append(day_object)

        updated_snapshot_objects: list[dict[str, Any]] = []
        for snapshot_object in snapshot_objects:
            if str(snapshot_object.get("effective_date") or "") == selected_date_iso:
                if should_keep_target_day:
                    updated_snapshot_objects.append(
                        self._updated_week_snapshot_object(
                            snapshot_object=snapshot_object,
                            sections=updated_sections,
                            summary=updated_day_summary,
                        )
                    )
            else:
                updated_snapshot_objects.append(snapshot_object)

        week_summary = self._summarize_week(
            day_objects=updated_day_objects,
            snapshot_objects=updated_snapshot_objects,
        )

        updated_payload = dict(payload_data)
        updated_payload["state"] = target_state
        updated_payload["days"] = updated_day_objects
        updated_payload["daily_snapshots"] = updated_snapshot_objects
        updated_payload["totals"] = self._totals_payload(week_summary)
        updated_payload["tracked_text"] = self._tracked_text(week_summary["meal_count"], scope="week")
        updated_payload["day_briefs"] = self._day_briefs(
            day_objects=updated_day_objects,
            snapshot_objects=updated_snapshot_objects,
        )
        if target_state == "draft":
            updated_payload["primary_action"] = self._draft_primary_action(
                view_mode="week",
                snapshot_id=str(updated_payload.get("snapshot_id") or payload_data.get("snapshot_id") or ""),
            )
        else:
            updated_payload["primary_action"] = None
        bundle_summary = dict(updated_payload.get("bundle_summary") or {})
        bundle_summary["meal_count"] = week_summary["meal_count"]
        updated_payload["bundle_summary"] = bundle_summary
        week_summary_payload = dict(updated_payload.get("week_summary") or {})
        if week_summary_payload:
            week_summary_payload["meal_count"] = week_summary["meal_count"]
            week_summary_payload["day_count"] = len(updated_day_objects)
            updated_payload["week_summary"] = week_summary_payload
        return updated_payload

    def _mutate_sections(
        self,
        *,
        sections: list[dict[str, Any]],
        payload: SavedMealPlanSlotMutationRequest,
    ) -> list[dict[str, Any]]:
        updated_sections = [dict(section) for section in sections]

        if payload.operation in {"add", "swap"}:
            meal = self._meal_repository.get_meal(str(payload.meal_id or ""))
            if meal is None:
                raise SavedMealPlanMutationError("The selected meal could not be found.")
            normalized_slot = payload.slot.value.lower()
            updated_sections = self._remove_meal_from_sections(
                sections=updated_sections,
                meal_id=meal.id,
            )
            existing_index = next(
                (
                    index
                    for index, section in enumerate(updated_sections)
                    if str(section.get("slot") or "").strip().lower() == normalized_slot
                ),
                None,
            )
            item_object = self._planner_item_object(meal=meal)
            if existing_index is not None:
                section = dict(updated_sections[existing_index])
                items = [dict(item) for item in list(section.get("items") or []) if isinstance(item, dict)]
                replacement_index = self._index_of_item(
                    items=items,
                    meal_id=payload.replacing_meal_id,
                )
                if replacement_index is not None and replacement_index < len(items):
                    items[replacement_index] = item_object
                else:
                    items = [item_object]
                section["items"] = items
                section["calories"] = self._summarize_items(items)["calories"]
                updated_sections[existing_index] = section
            else:
                updated_sections.append(
                    {
                        "slot": normalized_slot,
                        "title": payload.slot.value.capitalize(),
                        "calories": meal.nutrition_summary.calories,
                        "items": [item_object],
                    }
                )
        elif payload.operation == "update_servings":
            normalized_slot = payload.slot.value.lower()
            existing_index = next(
                (
                    index
                    for index, section in enumerate(updated_sections)
                    if str(section.get("slot") or "").strip().lower() == normalized_slot
                ),
                None,
            )
            if existing_index is None:
                raise SavedMealPlanMutationError("The selected meal could not be found in this plan.")

            section = dict(updated_sections[existing_index])
            items = [dict(item) for item in list(section.get("items") or []) if isinstance(item, dict)]
            target_index = self._index_of_item(
                items=items,
                meal_id=payload.meal_id,
            )
            if target_index is None or target_index >= len(items):
                raise SavedMealPlanMutationError("The selected meal could not be found in this slot.")

            items[target_index] = self._updated_item_for_servings(
                item=items[target_index],
                target_servings=float(payload.planned_servings or 1),
            )
            section["items"] = items
            section["calories"] = self._summarize_items(items)["calories"]
            updated_sections[existing_index] = section
        else:
            normalized_slot = payload.slot.value.lower()
            existing_index = next(
                (
                    index
                    for index, section in enumerate(updated_sections)
                    if str(section.get("slot") or "").strip().lower() == normalized_slot
                ),
                None,
            )
            if existing_index is None:
                return self._sort_sections(updated_sections)
            section = dict(updated_sections[existing_index])
            items = [dict(item) for item in list(section.get("items") or []) if isinstance(item, dict)]
            removal_index = self._index_of_item(
                items=items,
                meal_id=payload.replacing_meal_id,
            )
            if removal_index is not None and removal_index < len(items):
                items.pop(removal_index)
            elif items:
                items.pop(0)

            if not items:
                updated_sections.pop(existing_index)
            else:
                section["items"] = items
                section["calories"] = self._summarize_items(items)["calories"]
                updated_sections[existing_index] = section

        return self._sort_sections(updated_sections)

    def _remove_meal_from_sections(
        self,
        *,
        sections: list[dict[str, Any]],
        meal_id: str,
    ) -> list[dict[str, Any]]:
        updated_sections: list[dict[str, Any]] = []
        for section in sections:
            section_object = dict(section)
            items = [dict(item) for item in list(section.get("items") or []) if isinstance(item, dict)]
            filtered_items = [
                item
                for item in items
                if str(item.get("meal_id") or "").strip() != meal_id
            ]
            if not filtered_items:
                continue
            section_object["items"] = filtered_items
            section_object["calories"] = self._summarize_items(filtered_items)["calories"]
            updated_sections.append(section_object)
        return updated_sections

    def _updated_item_for_servings(
        self,
        *,
        item: dict[str, Any],
        target_servings: float,
    ) -> dict[str, Any]:
        resolved_servings = max(float(target_servings), 1.0)
        updated_item = dict(item)
        meal_detail = dict(updated_item.get("meal_detail") or {})

        updated_item["servings"] = resolved_servings
        updated_item["planned_servings"] = resolved_servings
        updated_item["yield_servings"] = resolved_servings
        updated_item["serving_text"] = self._serving_text(resolved_servings)

        if meal_detail:
            meal_detail["servings"] = resolved_servings
            meal_detail["planned_servings"] = resolved_servings
            meal_detail["yield_servings"] = resolved_servings
            meal_detail["ingredients_scaled_for_servings"] = resolved_servings
            updated_item["meal_detail"] = meal_detail
        return self._refresh_item_scaled_ingredients(updated_item)

    def _upsert_saved_plan(
        self,
        *,
        existing_plan,
        payload_data: dict[str, Any],
    ):
        planned_meals = self._planned_meals_from_payload(payload_data)
        updated_plan = self._saved_meal_plan_repository.upsert_saved_plan(
            user_id=existing_plan.user_id,
            title=str(payload_data.get("title") or existing_plan.title),
            status=str(payload_data.get("state") or existing_plan.status or "saved"),
            view_mode=str(payload_data.get("view_mode") or existing_plan.view_mode or "day"),
            effective_date=existing_plan.effective_date,
            meal_type=existing_plan.meal_type.value if existing_plan.meal_type is not None else None,
            country_code=existing_plan.country_code.value if existing_plan.country_code is not None else None,
            planned_meals=planned_meals,
            plan_payload=payload_data,
            requested_culture=existing_plan.requested_culture,
            user_goal=existing_plan.user_goal,
            source_snapshot_id=existing_plan.source_snapshot_id,
            source_conversation_id=existing_plan.source_conversation_id,
            agent_type=existing_plan.agent_type,
            plan_scope=existing_plan.plan_scope,
            week_start=existing_plan.week_start,
            week_end=existing_plan.week_end,
            day_index=existing_plan.day_index,
            parent_saved_plan_id=existing_plan.parent_saved_plan_id,
            source_saved_plan_id=existing_plan.source_saved_plan_id,
            linked_day_plan_ids=existing_plan.linked_day_plan_ids,
        )
        return updated_plan

    def _draft_mutation_response(
        self,
        *,
        current_user: User,
        selected_date: date,
        requested_view_mode: str,
        saved_plan,
    ) -> HomeMealPlanResponse:
        requested_view = "week" if str(requested_view_mode).lower() == "week" else "day"
        if saved_plan.view_mode == "week" and requested_view == "day":
            day_slice = self._day_slice_from_weekly_plan(
                weekly_plan=saved_plan,
                selected_date=selected_date,
                user_id=current_user.id,
                weekly_budget=self._current_user_weekly_budget(current_user),
                household_size=self._current_user_household_size(current_user),
            )
            return HomeMealPlanResponse(
                selected_date=selected_date,
                view_mode="day",
                resolution_mode="draft_weekly_plan_day_slice",
                ui_block=day_slice,
            )

        response_view_mode = saved_plan.view_mode
        return HomeMealPlanResponse(
            selected_date=selected_date,
            view_mode=response_view_mode,
            resolution_mode="draft_weekly_plan" if response_view_mode == "week" else "draft_day_plan",
            ui_block=self._saved_plan_ui_block(
                saved_plan,
                user_id=current_user.id,
                weekly_budget=self._current_user_weekly_budget(current_user),
                household_size=self._current_user_household_size(current_user),
            ),
        )

    def _sync_or_create_weekly_child_plans(self, *, parent_saved_plan):
        payload = dict(parent_saved_plan.plan_payload or {})
        weekly_snapshots = [
            dict(item)
            for item in list(payload.get("daily_snapshots") or [])
            if isinstance(item, dict)
            and self._snapshot_has_allocated_slots(dict(item))
        ]
        if not weekly_snapshots:
            if not parent_saved_plan.linked_day_plan_ids:
                return parent_saved_plan
            parent_payload = dict(payload)
            parent_payload["linked_day_plan_ids"] = []
            return self._saved_meal_plan_repository.upsert_saved_plan(
                user_id=parent_saved_plan.user_id,
                title=parent_saved_plan.title,
                status=parent_saved_plan.status,
                view_mode=parent_saved_plan.view_mode,
                effective_date=parent_saved_plan.effective_date,
                meal_type=(
                    parent_saved_plan.meal_type.value
                    if parent_saved_plan.meal_type is not None
                    else None
                ),
                country_code=(
                    parent_saved_plan.country_code.value
                    if parent_saved_plan.country_code is not None
                    else None
                ),
                planned_meals=parent_saved_plan.planned_meals,
                plan_payload=parent_payload,
                requested_culture=parent_saved_plan.requested_culture,
                user_goal=parent_saved_plan.user_goal,
                source_snapshot_id=parent_saved_plan.source_snapshot_id,
                source_conversation_id=parent_saved_plan.source_conversation_id,
                agent_type=parent_saved_plan.agent_type,
                plan_scope=parent_saved_plan.plan_scope,
                week_start=parent_saved_plan.week_start,
                week_end=parent_saved_plan.week_end,
                day_index=parent_saved_plan.day_index,
                parent_saved_plan_id=parent_saved_plan.parent_saved_plan_id,
                source_saved_plan_id=parent_saved_plan.source_saved_plan_id,
                linked_day_plan_ids=[],
            )

        existing_children_by_date: dict[date, Any] = {}
        for child_id in list(parent_saved_plan.linked_day_plan_ids or []):
            child_plan = self._saved_meal_plan_repository.get_saved_plan(
                user_id=parent_saved_plan.user_id,
                saved_plan_id=child_id,
            )
            if child_plan is not None and child_plan.effective_date is not None:
                existing_children_by_date[child_plan.effective_date] = child_plan

        linked_day_plan_ids: list[str] = []
        for index, snapshot in enumerate(weekly_snapshots):
            effective_date = self._parse_date_value(
                snapshot.get("effective_date") or snapshot.get("date")
            )
            if effective_date is None:
                continue
            child_plan = existing_children_by_date.get(effective_date)
            if child_plan is None:
                child_snapshot_id = f"{parent_saved_plan.source_snapshot_id}:day:{index}:{effective_date.isoformat()}"
                child_plan = self._saved_meal_plan_repository.upsert_saved_plan(
                    user_id=parent_saved_plan.user_id,
                    title=str(snapshot.get("title") or parent_saved_plan.title or "Meal Plan"),
                    status=str(parent_saved_plan.status or "saved"),
                    view_mode="day",
                    effective_date=effective_date,
                    meal_type=(
                        parent_saved_plan.meal_type.value
                        if parent_saved_plan.meal_type is not None
                        else None
                    ),
                    country_code=(
                        parent_saved_plan.country_code.value
                        if parent_saved_plan.country_code is not None
                        else None
                    ),
                    planned_meals=self._build_planned_meals_from_sections(list(snapshot.get("sections") or [])),
                    plan_payload={},
                    requested_culture=parent_saved_plan.requested_culture,
                    user_goal=parent_saved_plan.user_goal,
                    source_snapshot_id=child_snapshot_id,
                    source_conversation_id=parent_saved_plan.source_conversation_id,
                    agent_type=parent_saved_plan.agent_type,
                    plan_scope="weekly_child",
                    week_start=parent_saved_plan.week_start,
                    week_end=parent_saved_plan.week_end,
                    day_index=index,
                    parent_saved_plan_id=parent_saved_plan.id,
                )

            child_payload = self._child_day_payload_from_weekly_snapshot(
                parent_saved_plan=parent_saved_plan,
                parent_payload=payload,
                day_snapshot=snapshot,
                child_plan=child_plan,
            )
            child_payload["state"] = str(parent_saved_plan.status or "saved")
            child_payload["primary_action"] = None
            child_payload = self._refresh_plan_supporting_summaries(
                user_id=parent_saved_plan.user_id,
                payload_data=child_payload,
                country_code=(
                    parent_saved_plan.country_code.value
                    if parent_saved_plan.country_code is not None
                    else None
                ),
                include_saved_plan_id=child_plan.source_saved_plan_id or child_plan.id,
            )
            updated_child = self._upsert_saved_plan(
                existing_plan=child_plan,
                payload_data=child_payload,
            )
            linked_day_plan_ids.append(updated_child.id)
            self._user_meal_usage_service.sync_saved_day_plan(saved_plan=updated_child)

        if linked_day_plan_ids == list(parent_saved_plan.linked_day_plan_ids or []):
            return parent_saved_plan

        parent_payload = dict(payload)
        parent_payload["linked_day_plan_ids"] = linked_day_plan_ids
        return self._saved_meal_plan_repository.upsert_saved_plan(
            user_id=parent_saved_plan.user_id,
            title=parent_saved_plan.title,
            status=parent_saved_plan.status,
            view_mode=parent_saved_plan.view_mode,
            effective_date=parent_saved_plan.effective_date,
            meal_type=(
                parent_saved_plan.meal_type.value
                if parent_saved_plan.meal_type is not None
                else None
            ),
            country_code=(
                parent_saved_plan.country_code.value
                if parent_saved_plan.country_code is not None
                else None
            ),
            planned_meals=parent_saved_plan.planned_meals,
            plan_payload=parent_payload,
            requested_culture=parent_saved_plan.requested_culture,
            user_goal=parent_saved_plan.user_goal,
            source_snapshot_id=parent_saved_plan.source_snapshot_id,
            source_conversation_id=parent_saved_plan.source_conversation_id,
            agent_type=parent_saved_plan.agent_type,
            plan_scope=parent_saved_plan.plan_scope,
            week_start=parent_saved_plan.week_start,
            week_end=parent_saved_plan.week_end,
            day_index=parent_saved_plan.day_index,
            parent_saved_plan_id=parent_saved_plan.parent_saved_plan_id,
            source_saved_plan_id=parent_saved_plan.source_saved_plan_id,
            linked_day_plan_ids=linked_day_plan_ids,
        )

    def _sync_weekly_child_plan_for_date(
        self,
        *,
        parent_saved_plan,
        selected_date: date,
    ) -> None:
        payload = dict(parent_saved_plan.plan_payload or {})
        selected_snapshot = self._selected_week_day_snapshot(payload, selected_date, self._selected_week_day_payload(payload, selected_date) or {})
        if selected_snapshot is None:
            return

        child_plan = None
        for child_id in list(parent_saved_plan.linked_day_plan_ids or []):
            candidate = self._saved_meal_plan_repository.get_saved_plan(
                user_id=parent_saved_plan.user_id,
                saved_plan_id=child_id,
            )
            if candidate is not None and candidate.effective_date == selected_date:
                child_plan = candidate
                break

        if child_plan is None:
            return

        child_payload = self._child_day_payload_from_weekly_snapshot(
            parent_saved_plan=parent_saved_plan,
            parent_payload=payload,
            day_snapshot=selected_snapshot,
            child_plan=child_plan,
        )
        child_payload = self._refresh_plan_supporting_summaries(
            user_id=parent_saved_plan.user_id,
            payload_data=child_payload,
            country_code=(
                parent_saved_plan.country_code.value
                if parent_saved_plan.country_code is not None
                else None
            ),
            include_saved_plan_id=child_plan.id,
        )
        updated_child = self._upsert_saved_plan(
            existing_plan=child_plan,
            payload_data=child_payload,
        )
        self._user_meal_usage_service.sync_saved_day_plan(saved_plan=updated_child)

    def _child_day_payload_from_weekly_snapshot(
        self,
        *,
        parent_saved_plan,
        parent_payload: dict[str, Any],
        day_snapshot: dict[str, Any],
        child_plan,
    ) -> dict[str, Any]:
        sections = list(day_snapshot.get("sections") or [])
        return {
            "snapshot_id": child_plan.source_snapshot_id,
            "title": str(day_snapshot.get("title") or child_plan.title or "Meal Plan"),
            "view_mode": "day",
            "state": "saved",
            "effective_date": day_snapshot.get("effective_date") or child_plan.effective_date.isoformat(),
            "tracked_text": str(day_snapshot.get("tracked_text") or self._tracked_text(self._count_section_items(sections), scope="day")),
            "totals": dict(day_snapshot.get("totals") or self._totals_payload(self._summarize_sections(sections))),
            "sections": sections,
            "days": [],
            "primary_action": None,
            "overflow_actions": [],
            "planned_meals": self._build_planned_meals_from_sections(sections),
            "parent_weekly_plan_id": parent_saved_plan.id,
            "parent_weekly_snapshot_id": parent_saved_plan.source_snapshot_id,
            "week_start": parent_payload.get("week_start"),
            "week_end": parent_payload.get("week_end"),
            "day_index": child_plan.day_index,
            "source": "weekly_plan_child",
        }

    def _planner_item_object(self, *, meal: Meal) -> dict[str, Any]:
        servings = max(int(meal.servings or 1), 1)
        linked_products = self._grocery_repository.list_products_by_ids(list(meal.linked_product_ids))
        linked_products_by_id = {product.id: product for product in linked_products}
        ingredients = self._scaled_ingredient_payloads(
            meal=meal,
            target_servings=float(servings),
        )
        total_time_minutes = int(meal.prep_time_minutes or 0) + int(meal.cook_time_minutes or 0)
        estimated_cost = self._planner_estimated_cost(meal)
        return {
            "meal_id": meal.id,
            "name": meal.name,
            "servings": servings,
            "serving_text": f"{servings} serving" + ("" if servings == 1 else "s"),
            "calories": meal.nutrition_summary.calories,
            "description": meal.description,
            "meal_source": "Safediet catalog",
            "source_type": "fresh",
            "hero_image_url": meal.hero_image_url,
            "yield_servings": servings,
            "local_nutrition": {
                "calories": meal.nutrition_summary.calories,
                "protein_g": meal.nutrition_summary.protein_g,
                "carbs_g": meal.nutrition_summary.carbs_g,
                "fat_g": meal.nutrition_summary.fat_g,
            },
            "meal_detail": {
                "meal_id": meal.id,
                "name": meal.name,
                "meal_type": meal.meal_type.value,
                "hero_image_url": meal.hero_image_url,
                "description": meal.description,
                "servings": float(servings),
                "planned_servings": float(servings),
                "yield_servings": float(servings),
                "ingredients_scaled_for_servings": float(servings),
                "prep_time_minutes": int(meal.prep_time_minutes or 0),
                "cook_time_minutes": int(meal.cook_time_minutes or 0),
                "total_time_minutes": total_time_minutes,
                "difficulty": meal.difficulty.value,
                "culture_tags": list(meal.culture_tags),
                "diet_rules_supported": list(meal.diet_rules_supported),
                "allergy_exclusions": list(meal.allergy_exclusions),
                "estimated_nutrition_per_serving": {
                    "calories": meal.nutrition_summary.calories,
                    "protein_g": meal.nutrition_summary.protein_g,
                    "carbs_g": meal.nutrition_summary.carbs_g,
                    "fat_g": meal.nutrition_summary.fat_g,
                },
                "ingredients": ingredients,
                "linked_products": [
                    {
                        "product_id": product.id,
                        "name": product.product,
                        "image_url": product.img_url,
                    }
                    for product in linked_products
                ],
                "step_by_step": self._planner_step_by_step(meal),
                "quick_tips": self._planner_quick_tips(
                    servings=float(servings),
                    total_time_minutes=total_time_minutes,
                    estimated_cost=estimated_cost,
                    culture_tags=list(meal.culture_tags),
                ),
                "shopping_list_grouped": self._shopping_list_grouped(
                    ingredients=ingredients,
                    linked_products_by_id=linked_products_by_id,
                ),
                "estimated_cost": estimated_cost,
                "estimated_cost_gbp": self._planner_estimated_cost_amount(
                    meal=meal,
                    preferred_country_code="GB",
                ),
            },
        }

    def _empty_day_payload(self, selected_date: date) -> dict[str, Any]:
        return {
            "snapshot_id": f"home-day-{selected_date.isoformat()}",
            "title": self._home_day_title(selected_date),
            "view_mode": "day",
            "state": "saved",
            "effective_date": selected_date.isoformat(),
            "tracked_text": self._tracked_text(0, scope="day"),
            "totals": self._totals_payload(self._empty_summary()),
            "sections": [],
            "days": [],
            "daily_snapshots": [],
            "batch_groups": [],
            "leftover_links": [],
            "grocery_rollup": [],
            "bundle_summary": {"meal_count": 0},
            "inventory_summary": None,
            "cart_summary": None,
            "primary_action": None,
            "overflow_actions": [],
            "period_label": self._home_day_title(selected_date),
            "planned_meals": [],
        }

    @staticmethod
    def _home_day_title(selected_date: date) -> str:
        return selected_date.strftime("%A, %B %d")

    def _updated_week_day_object(
        self,
        *,
        day_object: dict[str, Any],
        sections: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        updated_day = dict(day_object)
        updated_day["sections"] = sections
        updated_day["calories"] = summary["calories"]
        updated_day["tracked_text"] = self._tracked_text(summary["meal_count"], scope="day")
        updated_day["totals"] = self._totals_payload(summary)
        return updated_day

    def _updated_week_snapshot_object(
        self,
        *,
        snapshot_object: dict[str, Any],
        sections: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        updated_snapshot = dict(snapshot_object)
        updated_snapshot["sections"] = sections
        updated_snapshot["tracked_text"] = self._tracked_text(summary["meal_count"], scope="day")
        updated_snapshot["totals"] = self._totals_payload(summary)
        return updated_snapshot

    def _day_briefs(
        self,
        *,
        day_objects: list[dict[str, Any]],
        snapshot_objects: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        briefs: list[dict[str, Any]] = []
        for day_object in day_objects:
            day_id = str(day_object.get("id") or "")
            effective_date = str(day_object.get("date") or "")
            sections = self._resolved_sections_for_summary(
                day_object=day_object,
                snapshot_objects=snapshot_objects,
            )
            summary = self._summarize_sections(sections)
            items = [dict(item) for section in sections for item in list(section.get("items") or []) if isinstance(item, dict)]
            snapshot_id = next(
                (
                    str(snapshot.get("snapshot_id") or "")
                    for snapshot in snapshot_objects
                    if str(snapshot.get("parent_day_id") or "") == day_id
                    or str(snapshot.get("effective_date") or "") == effective_date
                ),
                "",
            )
            briefs.append(
                {
                    "id": day_id or f"day-{effective_date}",
                    "date": effective_date or None,
                    "accent_label": day_object.get("accent_label") or "Day",
                    "full_label": day_object.get("full_label") or "Meal plan",
                    "calories": summary["calories"],
                    "tracked_text": self._tracked_text(summary["meal_count"], scope="day"),
                    "item_count": summary["meal_count"],
                    "meal_names": [str(item.get("name") or "") for item in items[:3] if str(item.get("name") or "").strip()],
                    "source_types": [str(item.get("source_type") or "") for item in items[:3] if str(item.get("source_type") or "").strip()],
                    "has_details": bool(sections),
                    "snapshot_id": snapshot_id or None,
                }
            )
        return briefs

    def _resolved_weekly_sections(
        self,
        *,
        day_objects: list[dict[str, Any]],
        snapshot_objects: list[dict[str, Any]],
        selected_date_iso: str,
    ) -> list[dict[str, Any]]:
        target_day = next((item for item in day_objects if str(item.get("date") or "") == selected_date_iso), None)
        if target_day is None:
            return []
        return self._resolved_sections_for_summary(
            day_object=target_day,
            snapshot_objects=snapshot_objects,
        )

    @staticmethod
    def _resolved_sections_for_summary(
        *,
        day_object: dict[str, Any],
        snapshot_objects: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        day_sections = [dict(item) for item in list(day_object.get("sections") or []) if isinstance(item, dict)]
        if day_sections:
            return day_sections
        day_id = str(day_object.get("id") or "")
        effective_date = str(day_object.get("date") or "")
        for snapshot in snapshot_objects:
            if (
                str(snapshot.get("parent_day_id") or "") == day_id
                or str(snapshot.get("effective_date") or "") == effective_date
            ):
                return [dict(item) for item in list(snapshot.get("sections") or []) if isinstance(item, dict)]
        return []

    def _summarize_week(
        self,
        *,
        day_objects: list[dict[str, Any]],
        snapshot_objects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        summary = self._empty_summary()
        for day_object in day_objects:
            partial = self._summarize_sections(
                self._resolved_sections_for_summary(
                    day_object=day_object,
                    snapshot_objects=snapshot_objects,
                )
            )
            summary = self._merge_summary(summary, partial)
        return summary

    def _summarize_sections(self, sections: list[dict[str, Any]]) -> dict[str, Any]:
        summary = self._empty_summary()
        for section in sections:
            partial = self._summarize_items(
                [dict(item) for item in list(section.get("items") or []) if isinstance(item, dict)]
            )
            summary = self._merge_summary(summary, partial)
        return summary

    @staticmethod
    def _summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
        summary = SavedMealPlanService._empty_summary()
        for item in items:
            local_nutrition = dict(item.get("local_nutrition") or {})
            detail_nutrition = dict(dict(item.get("meal_detail") or {}).get("estimated_nutrition_per_serving") or {})
            summary["calories"] += int(round(
                float(local_nutrition.get("calories") or detail_nutrition.get("calories") or item.get("calories") or 0)
            ))
            summary["protein_g"] += float(local_nutrition.get("protein_g") or detail_nutrition.get("protein_g") or 0.0)
            summary["carbs_g"] += float(local_nutrition.get("carbs_g") or detail_nutrition.get("carbs_g") or 0.0)
            summary["fat_g"] += float(local_nutrition.get("fat_g") or detail_nutrition.get("fat_g") or 0.0)
            summary["meal_count"] += 1
        return summary

    @staticmethod
    def _merge_summary(lhs: dict[str, Any], rhs: dict[str, Any]) -> dict[str, Any]:
        return {
            "calories": int(lhs["calories"] + rhs["calories"]),
            "protein_g": float(lhs["protein_g"] + rhs["protein_g"]),
            "carbs_g": float(lhs["carbs_g"] + rhs["carbs_g"]),
            "fat_g": float(lhs["fat_g"] + rhs["fat_g"]),
            "meal_count": int(lhs["meal_count"] + rhs["meal_count"]),
        }

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "calories": 0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "meal_count": 0,
        }

    @staticmethod
    def _totals_payload(summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "calories": int(summary["calories"]),
            "protein_g": float(summary["protein_g"]),
            "carbs_g": float(summary["carbs_g"]),
            "fat_g": float(summary["fat_g"]),
        }

    @staticmethod
    def _tracked_text(meal_count: int, *, scope: str) -> str:
        suffix = "meal" if meal_count == 1 else "meals"
        if scope == "week":
            return f"{meal_count} {suffix} planned this week"
        return f"{meal_count} {suffix} planned"

    @staticmethod
    def _sort_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        order = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}
        return sorted(
            sections,
            key=lambda section: (
                order.get(str(section.get("slot") or "").strip().lower(), 999),
                str(section.get("title") or ""),
            ),
        )

    @staticmethod
    def _index_of_item(*, items: list[dict[str, Any]], meal_id: str | None) -> int | None:
        normalized = str(meal_id or "").strip()
        if not normalized:
            return None
        for index, item in enumerate(items):
            if str(item.get("meal_id") or "").strip() == normalized:
                return index
        return None

    @staticmethod
    def _build_planned_meals_from_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        planned_meals: list[dict[str, Any]] = []
        for section in sections:
            slot = str(section.get("slot") or "").strip().lower()
            for item in list(section.get("items") or []):
                if not isinstance(item, dict):
                    continue
                meal_name = str(item.get("name") or "").strip()
                if not meal_name:
                    continue
                planned_meals.append(
                    {
                        "slot": slot,
                        "meal_id": item.get("meal_id"),
                        "meal_name": meal_name,
                        "meal_source": item.get("meal_source"),
                        "created_meal_draft": (
                            dict(item.get("meal_detail") or {})
                            if str(item.get("meal_source") or "") == "created"
                            else None
                        ),
                        "source_type": item.get("source_type"),
                        "batch_id": item.get("batch_id"),
                        "origin_batch_id": item.get("origin_batch_id"),
                    }
                )
        return planned_meals

    def _presentation_meals_by_key_from_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        normalized_view_mode = str(payload.get("view_mode") or "day").strip().lower()
        meals_by_key: dict[str, dict[str, Any]] = {}

        if normalized_view_mode == "week":
            for day_index, day in enumerate(list(payload.get("days") or []), start=1):
                if not isinstance(day, dict):
                    continue
                date_key = str(day.get("date") or payload.get("effective_date") or f"day-{day_index}").strip()
                for section_index, section in enumerate(list(day.get("sections") or []), start=1):
                    if not isinstance(section, dict):
                        continue
                    slot = str(section.get("slot") or "").strip().lower()
                    if not slot:
                        continue
                    for item_index, item in enumerate(list(section.get("items") or []), start=1):
                        if not isinstance(item, dict):
                            continue
                        synthetic_meal = self._presentation_meal_payload_from_item(
                            slot=slot,
                            item=item,
                            key_prefix=f"{date_key}:{section_index}:{item_index}",
                        )
                        if synthetic_meal is None:
                            continue
                        meals_by_key[f"{date_key}:{slot}:{section_index}:{item_index}"] = synthetic_meal
            return meals_by_key

        for section_index, section in enumerate(list(payload.get("sections") or []), start=1):
            if not isinstance(section, dict):
                continue
            slot = str(section.get("slot") or "").strip().lower()
            if not slot:
                continue
            for item_index, item in enumerate(list(section.get("items") or []), start=1):
                if not isinstance(item, dict):
                    continue
                synthetic_meal = self._presentation_meal_payload_from_item(
                    slot=slot,
                    item=item,
                    key_prefix=f"{slot}:{section_index}:{item_index}",
                )
                if synthetic_meal is None:
                    continue
                meals_by_key[f"{slot}:{section_index}:{item_index}"] = synthetic_meal
        return meals_by_key

    def _presentation_meal_payload_from_item(
        self,
        *,
        slot: str,
        item: dict[str, Any],
        key_prefix: str,
    ) -> dict[str, Any] | None:
        meal_detail = dict(item.get("meal_detail") or {})
        raw_ingredients = list(meal_detail.get("ingredients") or [])
        ingredient_items: list[dict[str, Any]] = []
        for ingredient_index, ingredient in enumerate(raw_ingredients, start=1):
            if not isinstance(ingredient, dict):
                continue
            ingredient_items.append(
                {
                    "id": ingredient.get("id") or f"{key_prefix}:ingredient:{ingredient_index}",
                    "name": str(ingredient.get("name") or "").strip(),
                    "quantity": ingredient.get("quantity"),
                    "unit": str(ingredient.get("unit") or "").strip(),
                    "optional": bool(ingredient.get("optional", False)),
                    "linked_product_ids": list(ingredient.get("linked_product_ids") or []),
                    "measurement_type": ingredient.get("measurement_type"),
                    "unit_code": ingredient.get("unit_code"),
                    "canonical_quantity": ingredient.get("canonical_quantity"),
                    "canonical_unit": ingredient.get("canonical_unit"),
                    "conversion_profile_id": ingredient.get("conversion_profile_id"),
                    "scaling_behavior": ingredient.get("scaling_behavior"),
                    "rounding_rule": ingredient.get("rounding_rule"),
                }
            )
        if not ingredient_items:
            return None

        source_type = str(
            item.get("source_type")
            or meal_detail.get("source_type")
            or ""
        ).strip().lower()
        scaled_for_servings = self._normalized_float(
            meal_detail.get("ingredients_scaled_for_servings")
        )
        planned_servings = self._normalized_float(
            item.get("yield_servings")
            or meal_detail.get("yield_servings")
            or item.get("planned_servings")
            or meal_detail.get("planned_servings")
        )
        servings = (
            scaled_for_servings
            or self._normalized_float(meal_detail.get("servings") or item.get("servings"))
            or 1.0
        )
        return {
            "id": item.get("meal_id") or f"{key_prefix}:{slot}",
            "name": str(item.get("name") or meal_detail.get("name") or "Planned meal").strip(),
            "servings": servings,
            "planned_servings": 0.0 if source_type == "leftover" else (planned_servings or servings),
            "ingredient_items": ingredient_items,
        }

    def _saved_plan_ui_block(
        self,
        saved_plan,
        *,
        user_id: str | None = None,
        weekly_budget: int | None = None,
        household_size: int | None = None,
    ) -> ConversationUIBlockResponse:
        payload = self._response_payload(saved_plan)
        if user_id is not None:
            payload = self._refresh_plan_supporting_summaries(
                user_id=user_id,
                payload_data=payload,
                country_code=(
                    saved_plan.country_code.value
                    if saved_plan.country_code is not None
                    else None
                ),
                weekly_budget=weekly_budget,
                household_size=household_size,
            )
        return ConversationUIBlockResponse(
            id=saved_plan.id,
            block_type="meal_plan_week" if saved_plan.view_mode == "week" else "meal_plan_draft",
            title=saved_plan.title,
            payload=payload,
        )

    def _day_slice_from_weekly_plan(
        self,
        *,
        weekly_plan,
        selected_date: date,
        user_id: str,
        weekly_budget: int | None,
        household_size: int | None,
    ) -> ConversationUIBlockResponse | None:
        payload = self._refresh_payload_meal_media(dict(weekly_plan.plan_payload or {}))
        selected_day = self._selected_week_day_payload(payload, selected_date)
        if selected_day is None:
            return None

        sections = list(selected_day.get("sections") or [])
        day_totals = self._coerce_totals(selected_day.get("totals"))
        day_bundle_summary = self._day_bundle_summary(
            weekly_bundle_summary=dict(payload.get("bundle_summary") or {}),
            sections=sections,
        )
        selected_snapshot = self._selected_week_day_snapshot(payload, selected_date, selected_day)

        sliced_payload: dict[str, Any] = dict(payload)
        sliced_payload["saved_plan_id"] = weekly_plan.id
        sliced_payload["snapshot_id"] = f"{weekly_plan.source_snapshot_id}:{selected_date.isoformat()}"
        sliced_payload["title"] = str(selected_day.get("full_label") or weekly_plan.title or "Meal Plan")
        sliced_payload["view_mode"] = "day"
        sliced_payload["state"] = str(payload.get("state") or weekly_plan.status or "saved")
        sliced_payload["effective_date"] = selected_date.isoformat()
        sliced_payload["tracked_text"] = str(
            selected_day.get("tracked_text")
            or f"Tracked 0/{len(sections)} meals"
        )
        sliced_payload["totals"] = day_totals
        sliced_payload["sections"] = sections
        sliced_payload["days"] = []
        sliced_payload["daily_snapshots"] = [selected_snapshot] if selected_snapshot is not None else []
        sliced_payload["bundle_summary"] = day_bundle_summary
        sliced_payload["day_briefs"] = []
        sliced_payload["period_label"] = selected_day.get("full_label") or payload.get("period_label")
        sliced_payload["linked_day_plan_ids"] = list(weekly_plan.linked_day_plan_ids or [])
        sliced_payload["primary_action"] = (
            self._draft_primary_action(
                view_mode="day",
                snapshot_id=str(sliced_payload["snapshot_id"]),
            )
            if str(weekly_plan.status or "saved").lower() == "draft"
            else None
        )
        sliced_payload = self._refresh_plan_supporting_summaries(
            user_id=user_id,
            payload_data=sliced_payload,
            country_code=(
                weekly_plan.country_code.value
                if weekly_plan.country_code is not None
                else None
            ),
            weekly_budget=weekly_budget,
            household_size=household_size,
        )

        return ConversationUIBlockResponse(
            id=f"{weekly_plan.id}:{selected_date.isoformat()}",
            block_type="meal_plan_draft",
            title=str(sliced_payload["title"]),
            payload=sliced_payload,
        )

    @staticmethod
    def _selected_week_day_payload(
        payload: dict[str, Any],
        selected_date: date,
    ) -> dict[str, Any] | None:
        selected_date_iso = selected_date.isoformat()
        for day in list(payload.get("days") or []):
            if not isinstance(day, dict):
                continue
            if str(day.get("date") or "") == selected_date_iso:
                return dict(day)
        return None

    @staticmethod
    def _selected_week_day_snapshot(
        payload: dict[str, Any],
        selected_date: date,
        selected_day: dict[str, Any],
    ) -> dict[str, Any] | None:
        selected_date_iso = selected_date.isoformat()
        day_id = str(selected_day.get("id") or "").strip()
        for snapshot in list(payload.get("daily_snapshots") or []):
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("effective_date") or "") == selected_date_iso:
                return dict(snapshot)
            if day_id and str(snapshot.get("parent_day_id") or "") == day_id:
                return dict(snapshot)
        return None

    def _day_bundle_summary(
        self,
        *,
        weekly_bundle_summary: dict[str, Any],
        sections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "household_size": weekly_bundle_summary.get("household_size"),
            "meal_count": self._count_section_items(sections),
            "shared_product_count": weekly_bundle_summary.get("shared_product_count"),
            "budget_status": weekly_bundle_summary.get("budget_status"),
        }

    def _compose_weekly_ui_block(
        self,
        *,
        selected_date: date,
        week_start: date,
        week_end: date,
        saved_day_plans: list[Any],
        user_id: str,
        weekly_budget: int | None,
        household_size: int | None,
    ) -> ConversationUIBlockResponse:
        plan_by_date: dict[date, Any] = {}
        for saved_plan in saved_day_plans:
            effective_date = self._saved_plan_effective_date(saved_plan)
            if effective_date is None or effective_date in plan_by_date:
                continue
            plan_by_date[effective_date] = saved_plan

        totals = {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        days: list[dict[str, Any]] = []
        daily_snapshots: list[dict[str, Any]] = []
        linked_day_plan_ids: list[str] = []
        meal_count = 0
        overall_state = "saved"

        current_date = week_start
        while current_date <= week_end:
            saved_plan = plan_by_date.get(current_date)
            if saved_plan is None:
                current_date += timedelta(days=1)
                continue
            plan_payload = (
                self._refresh_payload_meal_media(dict(saved_plan.plan_payload or {}))
                if saved_plan is not None
                else {}
            )
            day_totals = self._coerce_totals(plan_payload.get("totals"))
            sections = list(plan_payload.get("sections") or [])
            if not self._sections_have_allocated_slots(sections):
                current_date += timedelta(days=1)
                continue
            tracked_text = plan_payload.get("tracked_text")
            accent_label = current_date.strftime("%A")
            full_label = current_date.strftime("%A, %B %d")
            expanded = current_date == selected_date

            days.append(
                {
                    "id": f"day-{current_date.isoformat()}",
                    "date": current_date.isoformat(),
                    "accent_label": accent_label,
                    "full_label": full_label,
                    "calories": int(day_totals.get("calories") or 0),
                    "expanded": expanded,
                    "tracked_text": tracked_text,
                    "totals": day_totals,
                    "sections": sections,
                }
            )
            linked_day_plan_ids.append(saved_plan.id)
            meal_count += self._count_section_items(sections)
            normalized_day_status = str(saved_plan.status or "saved").lower()
            if normalized_day_status == "missing_groceries":
                overall_state = "missing_groceries"
            elif normalized_day_status != "saved" and overall_state != "missing_groceries":
                overall_state = "draft"
            daily_snapshots.append(
                {
                    "snapshot_id": saved_plan.source_snapshot_id,
                    "effective_date": current_date.isoformat(),
                    "title": saved_plan.title,
                    "view_mode": "day",
                    "state": saved_plan.status,
                    "tracked_text": tracked_text,
                    "totals": day_totals,
                    "sections": sections,
                    "parent_day_id": f"day-{current_date.isoformat()}",
                }
            )
            totals["calories"] += int(day_totals.get("calories") or 0)
            totals["protein_g"] += float(day_totals.get("protein_g") or 0.0)
            totals["carbs_g"] += float(day_totals.get("carbs_g") or 0.0)
            totals["fat_g"] += float(day_totals.get("fat_g") or 0.0)
            current_date += timedelta(days=1)

        payload = {
            "snapshot_id": f"home-week-{week_start.isoformat()}",
            "title": "This Week's Plan",
            "view_mode": "week",
            "state": overall_state,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "tracked_text": f"Tracked 0/{meal_count} meals" if meal_count > 0 else None,
            "totals": totals,
            "sections": [],
            "days": days,
            "daily_snapshots": daily_snapshots,
            "batch_groups": [],
            "leftover_links": [],
            "grocery_rollup": [],
            "bundle_summary": {
                "meal_count": meal_count,
                "household_size": self._household_size_from_saved_day_plans(saved_day_plans),
            },
            "inventory_summary": None,
            "cart_summary": None,
            "linked_day_plan_ids": linked_day_plan_ids,
            "primary_action": None,
            "overflow_actions": [],
            "period_label": self._week_period_label(week_start, week_end),
        }
        payload = self._refresh_plan_supporting_summaries(
            user_id=user_id,
            payload_data=payload,
            country_code=self._country_code_from_saved_day_plans(saved_day_plans),
            weekly_budget=weekly_budget,
            household_size=household_size,
        )
        return ConversationUIBlockResponse(
            id=f"home-week-{week_start.isoformat()}",
            block_type="meal_plan_week",
            title="This Week's Plan",
            payload=payload,
        )

    def _response_payload(self, saved_plan) -> dict[str, Any]:
        payload = self._refresh_payload_meal_media(dict(saved_plan.plan_payload or {}))
        payload.setdefault("saved_plan_id", saved_plan.id)
        payload.setdefault("snapshot_id", saved_plan.source_snapshot_id)
        payload.setdefault("title", saved_plan.title)
        payload.setdefault("view_mode", saved_plan.view_mode)
        payload.setdefault("state", saved_plan.status or "saved")
        if saved_plan.week_start is not None:
            payload.setdefault("week_start", saved_plan.week_start.isoformat())
        if saved_plan.week_end is not None:
            payload.setdefault("week_end", saved_plan.week_end.isoformat())
        if saved_plan.effective_date is not None:
            payload.setdefault("effective_date", saved_plan.effective_date.isoformat())
        if saved_plan.linked_day_plan_ids:
            payload.setdefault("linked_day_plan_ids", list(saved_plan.linked_day_plan_ids))

        normalized_status = str(saved_plan.status or "saved").lower()
        if normalized_status != "draft":
            payload["primary_action"] = None
        else:
            payload["primary_action"] = self._draft_primary_action(
                view_mode=str(payload.get("view_mode") or saved_plan.view_mode or "day"),
                snapshot_id=str(payload.get("snapshot_id") or saved_plan.source_snapshot_id),
            )
        return payload

    def _refresh_payload_meal_media(self, payload: dict[str, Any]) -> dict[str, Any]:
        updated_payload = dict(payload)
        get_meal = getattr(self._meal_repository, "get_meal", None)
        if not callable(get_meal):
            return updated_payload
        meal_cache: dict[str, Meal | None] = {}

        def refresh_item(item: dict[str, Any]) -> dict[str, Any]:
            updated_item = dict(item)
            meal_id = str(updated_item.get("meal_id") or "").strip()
            if not meal_id:
                return updated_item

            if meal_id not in meal_cache:
                meal_cache[meal_id] = get_meal(meal_id)
            meal = meal_cache[meal_id]
            if meal is None:
                return updated_item

            updated_item["hero_image_url"] = meal.hero_image_url
            meal_detail = dict(updated_item.get("meal_detail") or {})
            if meal_detail:
                meal_detail["hero_image_url"] = meal.hero_image_url
                updated_item["meal_detail"] = meal_detail
            return updated_item

        def refresh_sections(sections: list[Any]) -> list[dict[str, Any]]:
            refreshed_sections: list[dict[str, Any]] = []
            for section in sections:
                if not isinstance(section, dict):
                    continue
                updated_section = dict(section)
                updated_section["items"] = [
                    refresh_item(dict(item))
                    for item in list(section.get("items") or [])
                    if isinstance(item, dict)
                ]
                refreshed_sections.append(updated_section)
            return refreshed_sections

        updated_payload["sections"] = refresh_sections(list(updated_payload.get("sections") or []))

        refreshed_days: list[dict[str, Any]] = []
        for day in list(updated_payload.get("days") or []):
            if not isinstance(day, dict):
                continue
            updated_day = dict(day)
            updated_day["sections"] = refresh_sections(list(day.get("sections") or []))
            refreshed_days.append(updated_day)
        if refreshed_days:
            updated_payload["days"] = refreshed_days

        refreshed_snapshots: list[dict[str, Any]] = []
        for snapshot in list(updated_payload.get("daily_snapshots") or []):
            if not isinstance(snapshot, dict):
                continue
            updated_snapshot = dict(snapshot)
            updated_snapshot["sections"] = refresh_sections(list(snapshot.get("sections") or []))
            refreshed_snapshots.append(updated_snapshot)
        if refreshed_snapshots:
            updated_payload["daily_snapshots"] = refreshed_snapshots

        return updated_payload

    @staticmethod
    def _draft_primary_action(*, view_mode: str, snapshot_id: str) -> dict[str, Any]:
        return {
            "id": f"save-{snapshot_id}",
            "label": "Start Plan",
            "action_type": "save_meal_plan",
            "message": "Start Plan",
            "payload": {
                "snapshot_id": snapshot_id,
            },
        }

    @staticmethod
    def _count_section_items(sections: list[dict[str, Any]]) -> int:
        return sum(len(section.get("items") or []) for section in sections)

    def _summary_has_allocated_slots(self, summary: dict[str, Any]) -> bool:
        return int(summary.get("meal_count") or 0) > 0

    def _sections_have_allocated_slots(self, sections: list[dict[str, Any]]) -> bool:
        return self._count_section_items(sections) > 0

    def _snapshot_has_allocated_slots(self, snapshot: dict[str, Any]) -> bool:
        return self._sections_have_allocated_slots(
            [dict(item) for item in list(snapshot.get("sections") or []) if isinstance(item, dict)]
        )

    def _saved_plan_has_allocated_slots(self, saved_plan) -> bool:
        if saved_plan is None:
            return False
        if list(saved_plan.planned_meals or []):
            return True
        return bool(self._planned_meals_from_payload(dict(saved_plan.plan_payload or {})))

    def _saved_plan_effective_date(self, saved_plan) -> date | None:
        if saved_plan is None:
            return None
        if saved_plan.effective_date is not None:
            return saved_plan.effective_date
        return self._parse_date_value(dict(saved_plan.plan_payload or {}).get("effective_date"))

    def _saved_plan_week_bounds(self, saved_plan) -> tuple[date | None, date | None]:
        if saved_plan is None:
            return (None, None)
        payload = dict(saved_plan.plan_payload or {})
        week_start = saved_plan.week_start or self._parse_date_value(payload.get("week_start"))
        week_end = saved_plan.week_end or self._parse_date_value(payload.get("week_end"))
        return (week_start, week_end)

    @staticmethod
    def _coerce_totals(raw_totals: Any) -> dict[str, Any]:
        totals = dict(raw_totals or {})
        return {
            "calories": int(totals.get("calories") or 0),
            "protein_g": float(totals.get("protein_g") or 0.0),
            "carbs_g": float(totals.get("carbs_g") or 0.0),
            "fat_g": float(totals.get("fat_g") or 0.0),
        }

    @staticmethod
    def _week_bounds(selected_date: date) -> tuple[date, date]:
        week_start = selected_date - timedelta(days=selected_date.weekday())
        return week_start, week_start + timedelta(days=6)

    @staticmethod
    def _parse_date_value(raw_value: Any) -> date | None:
        if raw_value in (None, ""):
            return None
        raw_text = str(raw_value).strip()
        try:
            return date.fromisoformat(raw_text)
        except ValueError:
            try:
                return datetime.fromisoformat(raw_text.replace("Z", "+00:00")).date()
            except ValueError:
                return None

    @staticmethod
    def _week_period_label(week_start: date, week_end: date) -> str:
        if week_start.month == week_end.month:
            return f"{week_start.strftime('%b %d')} - {week_end.strftime('%d')}"
        return f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}"

    def _refresh_plan_supporting_summaries(
        self,
        *,
        user_id: str,
        payload_data: dict[str, Any],
        country_code: str | None,
        weekly_budget: int | None = None,
        household_size: int | None = None,
        include_saved_plan_id: str | None = None,
    ) -> dict[str, Any]:
        updated_payload = self._refresh_payload_scaled_ingredients(dict(payload_data))
        normalized_view_mode = str(updated_payload.get("view_mode") or "day").strip().lower()
        bundle_summary = dict(updated_payload.get("bundle_summary") or {})
        resolved_household_size = (
            household_size
            or self._normalized_positive_int(bundle_summary.get("household_size"))
            or 1
        )
        planned_meals = self._planned_meals_from_payload(updated_payload)
        meal_count = len(planned_meals)
        meals_by_key = self._presentation_meals_by_key_from_payload(updated_payload)
        period_days = 7 if normalized_view_mode == "week" else 1
        period_budget = (
            weekly_budget * (period_days / 7.0)
            if weekly_budget is not None and weekly_budget > 0
            else None
        )

        inventory_summary = self._empty_inventory_summary()
        cart_summary = self._empty_cart_summary()
        shared_product_count = 0
        if meals_by_key:
            costing_service = MealPlanCostingService(self._grocery_repository)
            inventory_service = MealInventoryReconciliationService()
            demand_summary = costing_service.build_product_demands(
                meals_by_slot=meals_by_key,
                household_size=resolved_household_size,
            )
            pantry_items = self._kitchen_service.list_planning_items(
                user_id=user_id,
                include_saved_plan_id=include_saved_plan_id,
            )
            inventory_summary = inventory_service.reconcile(
                product_demands=list(demand_summary.get("product_demands") or []),
                pantry_items=pantry_items,
            )
            cart_summary = costing_service.summarize_cart(
                shortages=list(inventory_summary.get("shortages") or []),
                products_by_id=dict(demand_summary.get("products_by_id") or {}),
                country_code=country_code,
                target_budget=period_budget,
            )
            shared_product_count = int(demand_summary.get("shared_product_count") or 0)

        cart_service = MealPlanCartService()
        refreshed_bundle_summary = dict(bundle_summary)
        refreshed_bundle_summary.update(
            cart_service.build_bundle_summary(
                planned_meals=planned_meals,
                household_size=resolved_household_size,
                weekly_budget=weekly_budget,
                shared_product_count=shared_product_count,
                cart_summary=cart_summary,
                meal_count=meal_count,
                period_days=period_days,
            )
        )

        updated_payload["planned_meals"] = planned_meals
        updated_payload["bundle_summary"] = refreshed_bundle_summary
        updated_payload["inventory_summary"] = inventory_summary
        updated_payload["cart_summary"] = cart_summary
        updated_payload["grocery_rollup"] = self._grocery_rollup_from_payload(updated_payload)

        if normalized_view_mode == "week":
            day_objects = [dict(item) for item in list(updated_payload.get("days") or []) if isinstance(item, dict)]
            snapshot_objects = [
                dict(item)
                for item in list(updated_payload.get("daily_snapshots") or [])
                if isinstance(item, dict)
            ]
            updated_payload["day_briefs"] = self._day_briefs(
                day_objects=day_objects,
                snapshot_objects=snapshot_objects,
            )
            updated_payload["week_summary"] = self._week_summary_payload(
                payload=updated_payload,
                bundle_summary=refreshed_bundle_summary,
                inventory_summary=inventory_summary,
                cart_summary=cart_summary,
            )
        else:
            updated_payload["day_briefs"] = []
            updated_payload["week_summary"] = None

        return updated_payload

    def _sync_kitchen_allocations_for_saved_plan(self, *, saved_plan) -> None:
        if str(saved_plan.plan_scope or "") not in {"standalone_day", "weekly_parent"}:
            return
        if str(saved_plan.status or "").lower() != "saved":
            self._kitchen_service.release_saved_plan_allocations(
                user_id=saved_plan.user_id,
                saved_plan_id=saved_plan.id,
            )
            return
        payload_data = dict(saved_plan.plan_payload or {})
        demands = self._product_demands_for_payload(payload_data=payload_data)
        self._kitchen_service.sync_saved_plan_allocations(
            user_id=saved_plan.user_id,
            saved_plan_id=saved_plan.id,
            product_demands=demands,
            effective_date=saved_plan.effective_date if saved_plan.view_mode == "day" else None,
            replace_existing=True,
        )

    def _product_demands_for_payload(
        self,
        *,
        payload_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        meals_by_key = self._presentation_meals_by_key_from_payload(payload_data)
        if not meals_by_key:
            return []
        resolved_household_size = (
            self._normalized_positive_int((payload_data.get("bundle_summary") or {}).get("household_size"))
            or 1
        )
        demand_summary = MealPlanCostingService(self._grocery_repository).build_product_demands(
            meals_by_slot=meals_by_key,
            household_size=resolved_household_size,
        )
        return list(demand_summary.get("product_demands") or [])

    def _planned_meals_from_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if str(payload.get("view_mode") or "day").strip().lower() == "week":
            planned_meals: list[dict[str, Any]] = []
            for day in list(payload.get("days") or []):
                if not isinstance(day, dict):
                    continue
                planned_meals.extend(self._build_planned_meals_from_sections(list(day.get("sections") or [])))
            return planned_meals
        return self._build_planned_meals_from_sections(list(payload.get("sections") or []))

    @staticmethod
    def _grocery_rollup_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        days = list(payload.get("days") or [])
        if not days:
            days = [{"sections": list(payload.get("sections") or [])}]

        seen: set[tuple[str, str]] = set()
        items: list[dict[str, Any]] = []
        for day in days:
            if not isinstance(day, dict):
                continue
            for section in list(day.get("sections") or []):
                if not isinstance(section, dict):
                    continue
                for item in list(section.get("items") or []):
                    if not isinstance(item, dict):
                        continue
                    meal_detail = dict(item.get("meal_detail") or {})
                    for group in list(meal_detail.get("shopping_list_grouped") or []):
                        if not isinstance(group, dict):
                            continue
                        group_title = str(group.get("title") or "Items")
                        for group_item in list(group.get("items") or []):
                            if not isinstance(group_item, dict):
                                continue
                            key = (group_title, str(group_item.get("name") or ""))
                            if not key[1] or key in seen:
                                continue
                            seen.add(key)
                            items.append(
                                {
                                    "group": group_title,
                                    "name": group_item.get("name"),
                                    "subtitle": group_item.get("subtitle"),
                                    "optional": bool(group_item.get("optional", False)),
                                    "image_url": group_item.get("image_url"),
                                }
                            )
        return items

    def _week_summary_payload(
        self,
        *,
        payload: dict[str, Any],
        bundle_summary: dict[str, Any],
        inventory_summary: dict[str, Any],
        cart_summary: dict[str, Any],
    ) -> dict[str, Any]:
        days = list(payload.get("days") or [])
        daily_snapshots = list(payload.get("daily_snapshots") or [])
        meal_count = 0
        for day in days:
            if not isinstance(day, dict):
                continue
            meal_count += self._count_section_items(
                self._resolved_sections_for_summary(
                    day_object=day,
                    snapshot_objects=[dict(item) for item in daily_snapshots if isinstance(item, dict)],
                )
            )

        day_count = len(days) or len(daily_snapshots)
        used_items_count = int(inventory_summary.get("used_items_count") or 0)
        shared_product_count = int(bundle_summary.get("shared_product_count") or 0)
        items_to_buy_count = int(cart_summary.get("items_to_buy_count") or 0)
        reuse_score = min(shared_product_count * 20 + used_items_count * 8, 100)
        waste_label = (
            "Leftovers are planned into the week"
            if any(
                str(item.get("source_type") or "").lower() == "leftover"
                for day in days
                if isinstance(day, dict)
                for section in list(day.get("sections") or [])
                if isinstance(section, dict)
                for item in list(section.get("items") or [])
                if isinstance(item, dict)
            )
            else "Fresh meals only"
        )

        return {
            "day_count": day_count,
            "meal_count": meal_count,
            "budget_status": str(bundle_summary.get("budget_status") or "unknown"),
            "estimated_total_cost": cart_summary.get("estimated_total_cost"),
            "formatted_estimated_total_cost": (
                cart_summary.get("formatted_estimated_total_cost")
                or bundle_summary.get("formatted_estimated_total_cost")
            ),
            "items_to_buy_count": items_to_buy_count,
            "shared_product_count": shared_product_count,
            "used_items_count": used_items_count,
            "depleted_items_count": int(inventory_summary.get("depleted_items_count") or 0),
            "reuse_score": reuse_score,
            "pantry_coverage_label": (
                f"{used_items_count} pantry match{'es' if used_items_count != 1 else ''}"
                if used_items_count > 0
                else "No pantry matches yet"
            ),
            "waste_label": waste_label,
        }

    @staticmethod
    def _shopping_list_grouped(
        *,
        ingredients: list[dict[str, Any]],
        linked_products_by_id: dict[str, Any],
    ) -> list[dict[str, Any]]:
        group_items: list[dict[str, Any]] = []
        for ingredient in ingredients:
            linked_product_ids = [
                str(item)
                for item in list(ingredient.get("linked_product_ids") or [])
                if str(item).strip()
            ]
            product = linked_products_by_id.get(linked_product_ids[0]) if linked_product_ids else None
            quantity = SavedMealPlanService._normalized_float(ingredient.get("quantity"))
            unit = str(ingredient.get("unit") or "").strip()
            subtitle = str(ingredient.get("quantity_label") or "").strip() or (
                f"{SavedMealPlanService._format_quantity(quantity)} {unit}".strip()
                if quantity is not None or unit
                else None
            )
            image_url = getattr(product, "img_url", None)
            if image_url is None and isinstance(product, dict):
                image_url = product.get("image_url") or product.get("img_url")
            group_items.append(
                {
                    "name": ingredient.get("name"),
                    "subtitle": subtitle,
                    "optional": bool(ingredient.get("optional", False)),
                    "image_url": image_url,
                }
            )
        return [{"title": "Items", "items": group_items}] if group_items else []

    def _refresh_payload_scaled_ingredients(self, payload: dict[str, Any]) -> dict[str, Any]:
        updated_payload = dict(payload)
        updated_payload["sections"] = self._refresh_sections_scaled_ingredients(
            list(updated_payload.get("sections") or [])
        )
        updated_payload["days"] = [
            {
                **dict(day),
                "sections": self._refresh_sections_scaled_ingredients(
                    list(dict(day).get("sections") or [])
                ),
            }
            for day in list(updated_payload.get("days") or [])
            if isinstance(day, dict)
        ]
        updated_payload["daily_snapshots"] = [
            {
                **dict(snapshot),
                "sections": self._refresh_sections_scaled_ingredients(
                    list(dict(snapshot).get("sections") or [])
                ),
            }
            for snapshot in list(updated_payload.get("daily_snapshots") or [])
            if isinstance(snapshot, dict)
        ]
        return updated_payload

    def _refresh_sections_scaled_ingredients(
        self,
        sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refreshed_sections: list[dict[str, Any]] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            refreshed_sections.append(
                {
                    **dict(section),
                    "items": [
                        self._refresh_item_scaled_ingredients(dict(item))
                        for item in list(section.get("items") or [])
                        if isinstance(item, dict)
                    ],
                }
            )
        return refreshed_sections

    def _refresh_item_scaled_ingredients(
        self,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        updated_item = dict(item)
        meal_detail = dict(updated_item.get("meal_detail") or {})
        if not meal_detail:
            return updated_item

        meal_id = str(updated_item.get("meal_id") or meal_detail.get("meal_id") or "").strip()
        target_servings = self._normalized_float(
            updated_item.get("yield_servings")
            or meal_detail.get("yield_servings")
            or updated_item.get("planned_servings")
            or meal_detail.get("planned_servings")
            or meal_detail.get("servings")
            or updated_item.get("servings")
        )
        current_scaled_servings = self._normalized_float(
            meal_detail.get("ingredients_scaled_for_servings")
            or meal_detail.get("yield_servings")
            or updated_item.get("yield_servings")
            or meal_detail.get("planned_servings")
            or updated_item.get("planned_servings")
            or meal_detail.get("servings")
            or updated_item.get("servings")
        ) or 1.0
        linked_products_by_id = self._linked_products_by_id_from_payload(
            list(meal_detail.get("linked_products") or [])
        )
        get_meal = getattr(self._meal_repository, "get_meal", None)
        meal = get_meal(meal_id) if callable(get_meal) and meal_id else None

        if meal is not None:
            resolved_target_servings = target_servings or max(float(meal.servings or 1), 1.0)
            scale_factor = resolved_target_servings / max(float(meal.servings or 1), 1.0)
            ingredients = self._scaled_ingredient_payloads(
                meal=meal,
                target_servings=resolved_target_servings,
            )
            linked_products = self._grocery_repository.list_products_by_ids(list(meal.linked_product_ids))
            linked_products_by_id = {product.id: product for product in linked_products}
            if not meal_detail.get("linked_products"):
                meal_detail["linked_products"] = [
                    {
                        "product_id": product.id,
                        "name": product.product,
                        "image_url": product.img_url,
                    }
                    for product in linked_products
                ]
            meal_detail["ingredients"] = ingredients
            meal_detail["ingredients_scaled_for_servings"] = resolved_target_servings
            meal_detail["servings"] = resolved_target_servings
            local_nutrition = self._scaled_meal_nutrition_payload(
                meal=meal,
                scale_factor=scale_factor,
            )
            estimated_cost = self._scaled_meal_estimated_cost_payload(
                meal=meal,
                scale_factor=scale_factor,
            )
            meal_detail["estimated_nutrition_per_serving"] = dict(local_nutrition)
            meal_detail["estimated_cost"] = estimated_cost
            meal_detail["step_by_step"] = self._planner_step_by_step(meal)
            meal_detail["quick_tips"] = self._planner_quick_tips(
                servings=resolved_target_servings,
                total_time_minutes=int(meal.prep_time_minutes or 0) + int(meal.cook_time_minutes or 0),
                estimated_cost=estimated_cost,
                culture_tags=list(meal.culture_tags),
            )
            meal_detail["estimated_cost_gbp"] = self._scaled_meal_estimated_cost_amount(
                meal=meal,
                scale_factor=scale_factor,
                preferred_country_code="GB",
            )
        else:
            ingredients = self._normalized_payload_ingredients(list(meal_detail.get("ingredients") or []))
            resolved_target_servings = target_servings or current_scaled_servings
            if not ingredients:
                updated_item["servings"] = resolved_target_servings
                updated_item["planned_servings"] = resolved_target_servings
                updated_item["yield_servings"] = resolved_target_servings
                updated_item["serving_text"] = self._serving_text(resolved_target_servings)
                meal_detail["servings"] = resolved_target_servings
                meal_detail["planned_servings"] = resolved_target_servings
                meal_detail["yield_servings"] = resolved_target_servings
                meal_detail["ingredients_scaled_for_servings"] = resolved_target_servings
                updated_item["meal_detail"] = meal_detail
                return updated_item
            scale_factor = resolved_target_servings / max(current_scaled_servings, 1.0)
            meal_detail["ingredients"] = [
                self._scaled_payload_ingredient(
                    ingredient=ingredient,
                    scale_factor=scale_factor,
                )
                for ingredient in ingredients
            ]
            meal_detail["ingredients_scaled_for_servings"] = resolved_target_servings
            local_nutrition = self._scaled_payload_nutrition(
                payload=dict(
                    updated_item.get("local_nutrition")
                    or meal_detail.get("estimated_nutrition_per_serving")
                    or {}
                ),
                scale_factor=scale_factor,
            )
            meal_detail["estimated_nutrition_per_serving"] = dict(local_nutrition)
            meal_detail["estimated_cost"] = self._scaled_payload_estimated_cost(
                payload=dict(meal_detail.get("estimated_cost") or {}),
                scale_factor=scale_factor,
            )
            estimated_cost_gbp = self._normalized_float(meal_detail.get("estimated_cost_gbp"))
            if estimated_cost_gbp is not None:
                meal_detail["estimated_cost_gbp"] = round(estimated_cost_gbp * scale_factor, 2)
            meal_detail.setdefault("step_by_step", [])
            meal_detail.setdefault("quick_tips", [])

        resolved_servings = (
            self._normalized_float(meal_detail.get("ingredients_scaled_for_servings"))
            or target_servings
            or current_scaled_servings
        )
        updated_item["servings"] = resolved_servings
        updated_item["planned_servings"] = resolved_servings
        updated_item["yield_servings"] = resolved_servings
        updated_item["serving_text"] = self._serving_text(resolved_servings)
        updated_item["local_nutrition"] = dict(local_nutrition)
        updated_item["calories"] = int(round(float(local_nutrition.get("calories") or 0)))
        meal_detail["servings"] = resolved_servings
        meal_detail["planned_servings"] = resolved_servings
        meal_detail["yield_servings"] = resolved_servings
        meal_detail["shopping_list_grouped"] = self._shopping_list_grouped(
            ingredients=list(meal_detail.get("ingredients") or []),
            linked_products_by_id=linked_products_by_id,
        )
        updated_item["meal_detail"] = meal_detail
        return updated_item

    @staticmethod
    def _planner_step_by_step(meal: Meal) -> list[dict[str, Any]]:
        if meal.recipe_step_items:
            return [
                {
                    "step_number": index,
                    "instruction": step.instruction,
                    "ingredient_ids": list(step.ingredient_ids),
                }
                for index, step in enumerate(meal.recipe_step_items, start=1)
                if str(step.instruction).strip()
            ]

        return [
            {
                "step_number": index,
                "instruction": instruction,
                "ingredient_ids": [],
            }
            for index, instruction in enumerate(meal.recipe_steps, start=1)
            if str(instruction).strip()
        ]

    def _planner_quick_tips(
        self,
        *,
        servings: float | None,
        total_time_minutes: int,
        estimated_cost: dict[str, Any] | None,
        culture_tags: list[str],
    ) -> list[str]:
        tips: list[str] = []
        if total_time_minutes > 0:
            tips.append(f"Set aside about {total_time_minutes} minutes from prep to finish.")
        if servings not in (None, 0):
            serving_text = self._serving_text(servings)
            if serving_text:
                tips.append(f"This draft is portioned for {serving_text}.")
        if estimated_cost and estimated_cost.get("formatted_amount"):
            tips.append(f"Estimated ingredient spend is about {estimated_cost['formatted_amount']}.")
        if culture_tags:
            primary_tag = str(culture_tags[0]).replace("_", " ").strip()
            if primary_tag:
                tips.append(f"Built to reflect a {primary_tag.lower()} flavor profile.")
        return tips[:3]

    @staticmethod
    def _serving_text(servings: float | None) -> str | None:
        if servings is None:
            return None
        normalized = max(float(servings), 0.0)
        if normalized.is_integer():
            whole = int(normalized)
            return f"{whole} serving" + ("" if whole == 1 else "s")
        return f"{normalized:.1f} servings"

    @classmethod
    def _scaled_payload_ingredient(
        cls,
        *,
        ingredient: dict[str, Any],
        scale_factor: float,
    ) -> dict[str, Any]:
        updated_ingredient = dict(ingredient)
        quantity = cls._normalized_float(updated_ingredient.get("quantity"))
        unit = str(updated_ingredient.get("unit") or "").strip()
        canonical_quantity = cls._normalized_float(updated_ingredient.get("canonical_quantity"))
        base_scale_factor = cls._normalized_float(updated_ingredient.get("scale_factor")) or 1.0
        if quantity is not None:
            quantity = round(quantity * scale_factor, 2)
            updated_ingredient["quantity"] = quantity
        if canonical_quantity is not None:
            updated_ingredient["canonical_quantity"] = round(canonical_quantity * scale_factor, 2)
        updated_ingredient["quantity_label"] = (
            f"{cls._format_quantity(quantity)} {unit}".strip()
            if quantity is not None or unit
            else None
        )
        updated_ingredient["scale_factor"] = round(base_scale_factor * scale_factor, 4)
        return updated_ingredient

    @classmethod
    def _scaled_payload_nutrition(
        cls,
        *,
        payload: dict[str, Any],
        scale_factor: float,
    ) -> dict[str, Any]:
        return {
            "calories": int(round(float(payload.get("calories") or 0) * scale_factor)),
            "protein_g": round(float(payload.get("protein_g") or 0.0) * scale_factor, 2),
            "carbs_g": round(float(payload.get("carbs_g") or 0.0) * scale_factor, 2),
            "fat_g": round(float(payload.get("fat_g") or 0.0) * scale_factor, 2),
        }

    @classmethod
    def _scaled_meal_nutrition_payload(
        cls,
        *,
        meal: Meal,
        scale_factor: float,
    ) -> dict[str, Any]:
        return cls._scaled_payload_nutrition(
            payload={
                "calories": meal.nutrition_summary.calories,
                "protein_g": meal.nutrition_summary.protein_g,
                "carbs_g": meal.nutrition_summary.carbs_g,
                "fat_g": meal.nutrition_summary.fat_g,
            },
            scale_factor=scale_factor,
        )

    @classmethod
    def _scaled_payload_estimated_cost(
        cls,
        *,
        payload: dict[str, Any],
        scale_factor: float,
    ) -> dict[str, Any] | None:
        if not payload:
            return None
        updated_cost = dict(payload)
        amount = cls._normalized_float(updated_cost.get("amount"))
        if amount is None:
            return updated_cost
        updated_cost["amount"] = round(amount * scale_factor, 2)
        return updated_cost

    @classmethod
    def _scaled_meal_estimated_cost_payload(
        cls,
        *,
        meal: Meal,
        scale_factor: float,
    ) -> dict[str, Any] | None:
        base_cost = cls._planner_estimated_cost(meal)
        if base_cost is None:
            return None
        return cls._scaled_payload_estimated_cost(
            payload=base_cost,
            scale_factor=scale_factor,
        )

    @classmethod
    def _scaled_meal_estimated_cost_amount(
        cls,
        *,
        meal: Meal,
        scale_factor: float,
        preferred_country_code: str,
    ) -> float | None:
        amount = cls._planner_estimated_cost_amount(
            meal=meal,
            preferred_country_code=preferred_country_code,
        )
        if amount is None:
            return None
        return round(amount * scale_factor, 2)

    def _scaled_ingredient_payloads(
        self,
        *,
        meal: Meal,
        target_servings: float,
    ) -> list[dict[str, Any]]:
        scale_factor = max(float(target_servings), 0.0) / max(float(meal.servings or 1), 1.0)
        scaled_ingredients = self._meal_scaling_service.scale_ingredients(
            meal=meal,
            target_servings=target_servings,
        )
        payloads: list[dict[str, Any]] = []
        for ingredient, scaled in zip(meal.ingredient_items, scaled_ingredients, strict=False):
            quantity = scaled.scaled_quantity
            unit = ingredient.unit
            payloads.append(
                {
                    "id": ingredient.id,
                    "name": ingredient.name,
                    "quantity": quantity,
                    "unit": unit,
                    "quantity_label": f"{self._format_quantity(quantity)} {unit}".strip()
                    if quantity is not None or unit
                    else None,
                    "base_quantity": ingredient.quantity,
                    "optional": ingredient.optional,
                    "linked_product_ids": list(ingredient.linked_product_ids),
                    "measurement_type": (
                        ingredient.measurement_type.value
                        if ingredient.measurement_type is not None
                        else None
                    ),
                    "unit_code": ingredient.unit_code,
                    "canonical_quantity": scaled.canonical_quantity,
                    "canonical_unit": scaled.canonical_unit,
                    "conversion_profile_id": ingredient.conversion_profile_id,
                    "scaling_behavior": ingredient.scaling_behavior.value,
                    "rounding_rule": (
                        ingredient.rounding_rule.value
                        if ingredient.rounding_rule is not None
                        else None
                    ),
                    "scale_factor": round(scale_factor, 4),
                }
            )
        return payloads

    @classmethod
    def _normalized_payload_ingredients(
        cls,
        raw_ingredients: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ingredients: list[dict[str, Any]] = []
        for index, ingredient in enumerate(raw_ingredients, start=1):
            if not isinstance(ingredient, dict):
                continue
            quantity = cls._normalized_float(ingredient.get("quantity"))
            unit = str(ingredient.get("unit") or "").strip()
            ingredients.append(
                {
                    "id": ingredient.get("id") or f"ingredient-{index}",
                    "name": str(ingredient.get("name") or "").strip(),
                    "quantity": quantity,
                    "unit": unit,
                    "quantity_label": str(ingredient.get("quantity_label") or "").strip() or (
                        f"{cls._format_quantity(quantity)} {unit}".strip()
                        if quantity is not None or unit
                        else None
                    ),
                    "base_quantity": cls._normalized_float(ingredient.get("base_quantity")) or quantity,
                    "optional": bool(ingredient.get("optional", False)),
                    "linked_product_ids": list(ingredient.get("linked_product_ids") or []),
                    "measurement_type": ingredient.get("measurement_type"),
                    "unit_code": ingredient.get("unit_code"),
                    "canonical_quantity": cls._normalized_float(ingredient.get("canonical_quantity")),
                    "canonical_unit": ingredient.get("canonical_unit"),
                    "conversion_profile_id": ingredient.get("conversion_profile_id"),
                    "scaling_behavior": ingredient.get("scaling_behavior"),
                    "rounding_rule": ingredient.get("rounding_rule"),
                    "scale_factor": cls._normalized_float(ingredient.get("scale_factor")),
                }
            )
        return [ingredient for ingredient in ingredients if ingredient.get("name")]

    @staticmethod
    def _linked_products_by_id_from_payload(
        linked_products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        products_by_id: dict[str, Any] = {}
        for product in linked_products:
            if not isinstance(product, dict):
                continue
            product_id = str(product.get("product_id") or product.get("id") or "").strip()
            if product_id:
                products_by_id[product_id] = product
        return products_by_id

    @staticmethod
    def _planner_estimated_cost(meal: Meal) -> dict[str, Any] | None:
        preferred = SavedMealPlanService._preferred_estimated_cost(meal=meal, preferred_country_code="GB")
        if preferred is None:
            return None
        return {
            "country_code": preferred.country_code.value,
            "currency_code": preferred.currency_code.value,
            "amount": preferred.amount,
        }

    @staticmethod
    def _planner_estimated_cost_amount(
        *,
        meal: Meal,
        preferred_country_code: str,
    ) -> float | None:
        preferred = SavedMealPlanService._preferred_estimated_cost(
            meal=meal,
            preferred_country_code=preferred_country_code,
        )
        return float(preferred.amount) if preferred is not None else None

    @staticmethod
    def _preferred_estimated_cost(
        *,
        meal: Meal,
        preferred_country_code: str,
    ):
        for cost in meal.estimated_costs:
            if str(cost.country_code.value).upper() == preferred_country_code.upper():
                return cost
        return meal.estimated_costs[0] if meal.estimated_costs else None

    @staticmethod
    def _empty_inventory_summary() -> dict[str, Any]:
        return {
            "used_items_count": 0,
            "depleted_items_count": 0,
            "used_items": [],
            "remaining_items": [],
            "shortages": [],
        }

    @staticmethod
    def _empty_cart_summary() -> dict[str, Any]:
        return {
            "items_to_buy_count": 0,
            "buy_items": [],
            "shared_items": [],
            "estimated_total_cost": 0.0,
            "currency_code": None,
            "formatted_estimated_total_cost": None,
            "budget_adjusted": False,
            "budget_adjustment_factor": 1.0,
            "target_budget": None,
            "original_estimated_total_cost": None,
            "formatted_original_estimated_total_cost": None,
        }

    @staticmethod
    def _current_user_weekly_budget(current_user: User) -> int | None:
        return SavedMealPlanService._normalized_positive_int(
            dict(current_user.user_configuration or {}).get("weekly_budget")
        )

    @staticmethod
    def _current_user_household_size(current_user: User) -> int | None:
        return SavedMealPlanService._normalized_positive_int(
            dict(current_user.user_configuration or {}).get("household_size")
        )

    @staticmethod
    def _country_code_from_saved_day_plans(saved_day_plans: list[Any]) -> str | None:
        for saved_plan in saved_day_plans:
            if saved_plan.country_code is not None:
                return saved_plan.country_code.value
        return None

    @staticmethod
    def _normalized_positive_int(value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_quantity(value: float | None) -> str:
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _household_size_from_saved_day_plans(saved_day_plans: list[Any]) -> int | None:
        for saved_plan in saved_day_plans:
            bundle_summary = dict((saved_plan.plan_payload or {}).get("bundle_summary") or {})
            household_size = bundle_summary.get("household_size")
            if isinstance(household_size, int) and household_size > 0:
                return household_size
        return None
