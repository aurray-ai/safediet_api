from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from types import SimpleNamespace

from app.models.meal import Meal, MealDifficulty, MealEstimatedCost, MealIngredient, MealNutritionSummary, MealType
from app.models.grocery import CountryCode, CurrencyCode
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.schemas.saved_meal_plan import SavedMealPlanSlotMutationRequest
from app.services.saved_meal_plan_service import (
    SavedMealPlanMutationError,
    SavedMealPlanNotFoundError,
    SavedMealPlanService,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user() -> User:
    return User(
        id="user-1",
        name="Test User",
        email="test@example.com",
        password_hash="x",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_saved_plan(
    *,
    plan_id: str,
    view_mode: str,
    effective_date: date | None,
    title: str = "Meal Plan",
    week_start: date | None = None,
    week_end: date | None = None,
    source_snapshot_id: str | None = None,
    plan_payload: dict | None = None,
    linked_day_plan_ids: list[str] | None = None,
    updated_at: datetime | None = None,
    status: str = "saved",
) -> SavedMealPlan:
    resolved_updated_at = updated_at or utc_now()
    return SavedMealPlan(
        id=plan_id,
        user_id="user-1",
        title=title,
        status=status,
        view_mode=view_mode,
        plan_scope="weekly_parent" if view_mode == "week" else "standalone_day",
        effective_date=effective_date,
        week_start=week_start,
        week_end=week_end,
        day_index=None,
        parent_saved_plan_id=None,
        source_saved_plan_id=None,
        linked_day_plan_ids=list(linked_day_plan_ids or []),
        meal_type=None,
        country_code=None,
        planned_meals=[],
        plan_payload=dict(plan_payload or {}),
        requested_culture=None,
        user_goal=None,
        source_snapshot_id=source_snapshot_id or f"snapshot-{plan_id}",
        source_conversation_id="conversation-1",
        agent_type="meal_planner_agent",
        created_at=resolved_updated_at,
        updated_at=resolved_updated_at,
    )


class StubSavedMealPlanRepository:
    def __init__(
        self,
        *,
        day_plan: SavedMealPlan | None = None,
        weekly_plan: SavedMealPlan | None = None,
        range_plans: list[SavedMealPlan] | None = None,
        saved_plans: list[SavedMealPlan] | None = None,
    ) -> None:
        self.day_plan = day_plan
        self.weekly_plan = weekly_plan
        self.range_plans = list(range_plans or [])
        self.saved_plans = list(saved_plans or [])
        self.upsert_calls: list[dict] = []
        self._plans_by_snapshot: dict[str, SavedMealPlan] = {}
        self._plans_by_id: dict[str, SavedMealPlan] = {}
        self._drafts_by_source: dict[str, SavedMealPlan] = {}
        if day_plan is not None:
            self._plans_by_id[day_plan.id] = day_plan
            self._plans_by_snapshot[day_plan.source_snapshot_id] = day_plan
        if weekly_plan is not None:
            self._plans_by_id[weekly_plan.id] = weekly_plan
            self._plans_by_snapshot[weekly_plan.source_snapshot_id] = weekly_plan

    def get_saved_plan(self, *, user_id: str, saved_plan_id: str) -> SavedMealPlan | None:
        return self._plans_by_id.get(saved_plan_id)

    def get_latest_draft_derived_from_saved_plan(self, **kwargs) -> SavedMealPlan | None:
        source_saved_plan_id = kwargs.get("source_saved_plan_id")
        return self._drafts_by_source.get(str(source_saved_plan_id)) if source_saved_plan_id else None

    def upsert_saved_plan(self, **kwargs) -> SavedMealPlan:
        self.upsert_calls.append(dict(kwargs))
        source_snapshot_id = str(kwargs.get("source_snapshot_id") or "")
        existing = self._plans_by_snapshot.get(source_snapshot_id)
        plan_id = existing.id if existing is not None else f"plan-{len(self.upsert_calls)}"
        plan = make_saved_plan(
            plan_id=plan_id,
            view_mode=str(kwargs.get("view_mode") or "day"),
            effective_date=kwargs.get("effective_date"),
            title=str(kwargs.get("title") or "Meal Plan"),
            week_start=kwargs.get("week_start"),
            week_end=kwargs.get("week_end"),
            source_snapshot_id=source_snapshot_id or None,
            plan_payload=kwargs.get("plan_payload"),
            linked_day_plan_ids=kwargs.get("linked_day_plan_ids"),
            status=str(kwargs.get("status") or "saved"),
        )
        self._plans_by_snapshot[plan.source_snapshot_id] = plan
        self._plans_by_id[plan.id] = plan
        if plan.status == "draft" and kwargs.get("source_saved_plan_id"):
            self._drafts_by_source[str(kwargs["source_saved_plan_id"])] = plan
        if plan.view_mode == "day" and plan.effective_date is not None:
            self.day_plan = plan
        if plan.view_mode == "week" and plan.week_start is not None and plan.week_end is not None:
            self.weekly_plan = plan
        return plan

    def list_saved_plans(self, **kwargs):
        user_id = kwargs.get("user_id")
        view_mode = kwargs.get("view_mode")
        limit = kwargs.get("limit", 20)
        items = [
            plan
            for plan in self.saved_plans
            if (user_id is None or plan.user_id == user_id)
            and (view_mode is None or plan.view_mode == view_mode)
        ]
        return items[:limit], len(items)

    def get_saved_day_plan_for_date(
        self,
        *,
        user_id: str,
        effective_date: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        if self.day_plan is not None and self.day_plan.effective_date == effective_date:
            if allowed_statuses and self.day_plan.status not in allowed_statuses:
                return None
            return self.day_plan
        return None

    def get_saved_weekly_plan_for_week(
        self,
        *,
        user_id: str,
        week_start: date,
        week_end: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        if self.weekly_plan is None:
            return None
        if self.weekly_plan.week_start == week_start and self.weekly_plan.week_end == week_end:
            if allowed_statuses and self.weekly_plan.status not in allowed_statuses:
                return None
            return self.weekly_plan
        return None

    def get_saved_weekly_plan_covering_date(
        self,
        *,
        user_id: str,
        target_date: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        if self.weekly_plan is None:
            return None
        if (
            self.weekly_plan.week_start is not None
            and self.weekly_plan.week_end is not None
            and self.weekly_plan.week_start <= target_date <= self.weekly_plan.week_end
        ):
            if allowed_statuses and self.weekly_plan.status not in allowed_statuses:
                return None
            return self.weekly_plan
        return None

    def list_saved_day_plans_in_range(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
        limit: int = 500,
        allowed_statuses: list[str] | None = None,
    ) -> list[SavedMealPlan]:
        return [
            plan
            for plan in self.range_plans
            if (
                plan.effective_date is not None
                and start_date <= plan.effective_date <= end_date
                and (not allowed_statuses or plan.status in allowed_statuses)
            )
        ][:limit]


class StubMealRepository:
    def __init__(self, meals: dict[str, Meal] | None = None) -> None:
        self.meals = dict(meals or {})

    def get_meal(self, meal_id: str) -> Meal | None:
        return self.meals.get(meal_id)


class StubGroceryRepository:
    def list_products_by_ids(self, product_ids: list[str]):
        return []


class StubUserPantryRepository:
    def list_items(self, user_id: str):
        return []


def make_meal(*, meal_id: str, hero_image_url: str) -> Meal:
    return Meal(
        id=meal_id,
        name="Test Meal",
        hero_image_url=hero_image_url,
        image_urls=[hero_image_url],
        description="",
        meal_type=MealType.BREAKFAST,
        meal_types=[MealType.BREAKFAST],
        category_ids=[],
        culture_tags=[],
        diet_rules_supported=[],
        allergy_exclusions=[],
        prep_time_minutes=0,
        cook_time_minutes=0,
        difficulty=MealDifficulty.EASY,
        servings=1,
        nutritional_specs=[],
        nutrition_summary=MealNutritionSummary(calories=100, protein_g=10, carbs_g=10, fat_g=5),
        estimated_costs=[],
        recipe_steps=[],
        ingredient_items=[],
        recipe_step_items=[],
        linked_product_ids=[],
        chef_available=False,
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def build_service(
    repository: StubSavedMealPlanRepository,
    *,
    meal_repository: object | None = None,
) -> SavedMealPlanService:
    return SavedMealPlanService(
        saved_meal_plan_repository=repository,
        meal_repository=meal_repository or object(),
        grocery_repository=StubGroceryRepository(),
        user_pantry_repository=StubUserPantryRepository(),
        kitchen_service=SimpleNamespace(
            list_planning_items=lambda user_id, include_saved_plan_id=None: [],
            release_saved_plan_allocations=lambda **kwargs: None,
            sync_saved_plan_allocations=lambda **kwargs: None,
            list_saved_plan_allocations=lambda **kwargs: [],
            consume_saved_plan_slot=lambda **kwargs: [],
        ),
        user_meal_usage_service=object(),
    )


class SavedMealPlanServiceTests(unittest.TestCase):
    def test_mutate_sections_updates_servings_and_scaled_nutrition(self) -> None:
        now = utc_now()
        meal = Meal(
            id="meal-scale-update-1",
            name="Rice Bowl",
            hero_image_url="hero.png",
            image_urls=["hero.png"],
            description="",
            meal_type=MealType.LUNCH,
            meal_types=[MealType.LUNCH],
            category_ids=[],
            culture_tags=[],
            diet_rules_supported=[],
            allergy_exclusions=[],
            prep_time_minutes=0,
            cook_time_minutes=0,
            difficulty=MealDifficulty.EASY,
            servings=2,
            nutritional_specs=[],
            nutrition_summary=MealNutritionSummary(calories=300, protein_g=10, carbs_g=40, fat_g=5),
            estimated_costs=[
                MealEstimatedCost(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=4.5,
                )
            ],
            recipe_steps=[],
            recipe_step_items=[],
            ingredient_items=[
                MealIngredient(
                    id="ingredient-rice",
                    name="Rice",
                    quantity=100,
                    unit="g",
                    optional=False,
                    linked_product_ids=["prod_rice"],
                    canonical_quantity=100,
                    canonical_unit="g",
                )
            ],
            linked_product_ids=["prod_rice"],
            chef_available=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({"meal-scale-update-1": meal}),
        )

        updated_sections = service._mutate_sections(
            sections=[
                {
                    "slot": "lunch",
                    "title": "Lunch",
                    "items": [
                        {
                            "meal_id": "meal-scale-update-1",
                            "name": "Rice Bowl",
                            "yield_servings": 2.0,
                            "planned_servings": 2.0,
                            "servings": 2.0,
                            "meal_detail": {
                                "meal_id": "meal-scale-update-1",
                                "name": "Rice Bowl",
                                "servings": 2.0,
                                "yield_servings": 2.0,
                                "planned_servings": 2.0,
                                "ingredients_scaled_for_servings": 2.0,
                                "ingredients": [
                                    {
                                        "id": "ingredient-rice",
                                        "name": "Rice",
                                        "quantity": 100,
                                        "unit": "g",
                                        "linked_product_ids": ["prod_rice"],
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            payload=SavedMealPlanSlotMutationRequest(
                operation="update_servings",
                slot=MealType.LUNCH,
                meal_id="meal-scale-update-1",
                planned_servings=4,
            ),
        )

        updated_item = updated_sections[0]["items"][0]
        updated_ingredient = updated_item["meal_detail"]["ingredients"][0]

        self.assertEqual(4.0, updated_item["yield_servings"])
        self.assertEqual("4 servings", updated_item["serving_text"])
        self.assertEqual(600, updated_item["calories"])
        self.assertEqual(200.0, updated_ingredient["quantity"])
        self.assertEqual("200 g", updated_ingredient["quantity_label"])
        self.assertEqual(4.0, updated_item["meal_detail"]["ingredients_scaled_for_servings"])
        self.assertEqual(600, updated_item["meal_detail"]["estimated_nutrition_per_serving"]["calories"])
        self.assertEqual(9.0, updated_item["meal_detail"]["estimated_cost"]["amount"])
        self.assertEqual(9.0, updated_item["meal_detail"]["estimated_cost_gbp"])

    def test_mutate_sections_add_creates_new_section(self) -> None:
        meal = make_meal(meal_id="meal-a", hero_image_url="hero-a.png")
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({"meal-a": meal}),
        )

        updated_sections = service._mutate_sections(
            sections=[],
            payload=SavedMealPlanSlotMutationRequest(
                operation="add",
                slot=MealType.LUNCH,
                meal_id="meal-a",
            ),
        )

        self.assertEqual(1, len(updated_sections))
        self.assertEqual("lunch", updated_sections[0]["slot"])
        self.assertEqual(1, len(updated_sections[0]["items"]))
        self.assertEqual("meal-a", updated_sections[0]["items"][0]["meal_id"])

    def test_mutate_sections_add_replaces_existing_slot_items_when_no_target_specified(self) -> None:
        meal = make_meal(meal_id="meal-a", hero_image_url="hero-a.png")
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({"meal-a": meal}),
        )

        updated_sections = service._mutate_sections(
            sections=[
                {
                    "slot": "lunch",
                    "title": "Lunch",
                    "items": [{"meal_id": "meal-old", "name": "Old Meal"}],
                }
            ],
            payload=SavedMealPlanSlotMutationRequest(
                operation="add",
                slot=MealType.LUNCH,
                meal_id="meal-a",
            ),
        )

        self.assertEqual(1, len(updated_sections))
        self.assertEqual(1, len(updated_sections[0]["items"]))
        self.assertEqual("meal-a", updated_sections[0]["items"][0]["meal_id"])

    def test_mutate_sections_add_raises_when_meal_not_found(self) -> None:
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({}),
        )

        with self.assertRaises(SavedMealPlanMutationError):
            service._mutate_sections(
                sections=[],
                payload=SavedMealPlanSlotMutationRequest(
                    operation="add",
                    slot=MealType.LUNCH,
                    meal_id="missing-meal",
                ),
            )

    def test_mutate_sections_swap_replaces_item_at_target_index(self) -> None:
        meal = make_meal(meal_id="meal-a", hero_image_url="hero-a.png")
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({"meal-a": meal}),
        )

        updated_sections = service._mutate_sections(
            sections=[
                {
                    "slot": "dinner",
                    "title": "Dinner",
                    "items": [
                        {"meal_id": "meal-old", "name": "Old Meal"},
                        {"meal_id": "meal-other", "name": "Other Meal"},
                    ],
                }
            ],
            payload=SavedMealPlanSlotMutationRequest(
                operation="swap",
                slot=MealType.DINNER,
                meal_id="meal-a",
                replacing_meal_id="meal-old",
            ),
        )

        items = updated_sections[0]["items"]
        self.assertEqual(2, len(items))
        self.assertEqual("meal-a", items[0]["meal_id"])
        self.assertEqual("meal-other", items[1]["meal_id"])

    def test_mutate_sections_swap_raises_when_meal_not_found(self) -> None:
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({}),
        )

        with self.assertRaises(SavedMealPlanMutationError):
            service._mutate_sections(
                sections=[
                    {
                        "slot": "dinner",
                        "title": "Dinner",
                        "items": [{"meal_id": "meal-old", "name": "Old Meal"}],
                    }
                ],
                payload=SavedMealPlanSlotMutationRequest(
                    operation="swap",
                    slot=MealType.DINNER,
                    meal_id="missing-meal",
                    replacing_meal_id="meal-old",
                ),
            )

    def test_mutate_sections_remove_item_by_replacing_meal_id(self) -> None:
        service = build_service(StubSavedMealPlanRepository())

        updated_sections = service._mutate_sections(
            sections=[
                {
                    "slot": "breakfast",
                    "title": "Breakfast",
                    "items": [
                        {"meal_id": "meal-x", "name": "Meal X"},
                        {"meal_id": "meal-y", "name": "Meal Y"},
                    ],
                }
            ],
            payload=SavedMealPlanSlotMutationRequest(
                operation="remove",
                slot=MealType.BREAKFAST,
                meal_id="meal-x",
            ),
        )

        self.assertEqual(1, len(updated_sections))
        items = updated_sections[0]["items"]
        self.assertEqual(1, len(items))
        self.assertEqual("meal-y", items[0]["meal_id"])

    def test_mutate_sections_remove_drops_empty_section(self) -> None:
        service = build_service(StubSavedMealPlanRepository())

        updated_sections = service._mutate_sections(
            sections=[
                {
                    "slot": "snack",
                    "title": "Snack",
                    "items": [{"meal_id": "meal-z", "name": "Meal Z"}],
                }
            ],
            payload=SavedMealPlanSlotMutationRequest(
                operation="remove",
                slot=MealType.SNACK,
                meal_id="meal-z",
            ),
        )

        self.assertEqual([], updated_sections)

    def test_mutate_sections_remove_pops_first_item_when_no_match(self) -> None:
        service = build_service(StubSavedMealPlanRepository())

        updated_sections = service._mutate_sections(
            sections=[
                {
                    "slot": "lunch",
                    "title": "Lunch",
                    "items": [
                        {"meal_id": "meal-a", "name": "Meal A"},
                        {"meal_id": "meal-b", "name": "Meal B"},
                    ],
                }
            ],
            payload=SavedMealPlanSlotMutationRequest(
                operation="remove",
                slot=MealType.LUNCH,
                replacing_meal_id="does-not-exist",
            ),
        )

        items = updated_sections[0]["items"]
        self.assertEqual(1, len(items))
        self.assertEqual("meal-b", items[0]["meal_id"])

    def test_mutate_slot_add_creates_plan_on_demand(self) -> None:
        meal = make_meal(meal_id="meal-a", hero_image_url="hero-a.png")
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({"meal-a": meal}),
        )

        response = service.mutate_slot(
            current_user=build_user(),
            payload=SavedMealPlanSlotMutationRequest(
                operation="add",
                slot=MealType.LUNCH,
                meal_id="meal-a",
                effective_date=date(2026, 6, 24),
            ),
        )

        self.assertEqual("draft_day_plan", response.resolution_mode)
        self.assertIsNotNone(response.ui_block)
        self.assertEqual(1, len(response.ui_block.payload["sections"]))
        self.assertEqual("meal-a", response.ui_block.payload["sections"][0]["items"][0]["meal_id"])

    def test_mutate_slot_add_against_existing_draft_day_plan(self) -> None:
        meal = make_meal(meal_id="meal-a", hero_image_url="hero-a.png")
        day_plan = make_saved_plan(
            plan_id="draft-day-1",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            status="draft",
            source_snapshot_id="snapshot-draft-day-1",
            plan_payload={
                "snapshot_id": "snapshot-draft-day-1",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "draft",
                "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
                "sections": [],
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(day_plan=day_plan),
            meal_repository=StubMealRepository({"meal-a": meal}),
        )

        response = service.mutate_slot(
            current_user=build_user(),
            payload=SavedMealPlanSlotMutationRequest(
                operation="add",
                slot=MealType.LUNCH,
                meal_id="meal-a",
                effective_date=date(2026, 6, 24),
            ),
        )

        self.assertEqual("draft_day_plan", response.resolution_mode)
        self.assertEqual(1, len(response.ui_block.payload["sections"]))
        self.assertEqual("meal-a", response.ui_block.payload["sections"][0]["items"][0]["meal_id"])

    def test_mutate_slot_swap_against_existing_draft_day_plan(self) -> None:
        meal_old = make_meal(meal_id="meal-old", hero_image_url="hero-old.png")
        meal_new = make_meal(meal_id="meal-new", hero_image_url="hero-new.png")
        day_plan = make_saved_plan(
            plan_id="draft-day-2",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            status="draft",
            source_snapshot_id="snapshot-draft-day-2",
            plan_payload={
                "snapshot_id": "snapshot-draft-day-2",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "draft",
                "totals": {"calories": 100, "protein_g": 10, "carbs_g": 10, "fat_g": 5},
                "sections": [
                    {
                        "slot": "dinner",
                        "title": "Dinner",
                        "items": [{"meal_id": "meal-old", "name": "Old Meal"}],
                    }
                ],
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(day_plan=day_plan),
            meal_repository=StubMealRepository({"meal-old": meal_old, "meal-new": meal_new}),
        )

        response = service.mutate_slot(
            current_user=build_user(),
            payload=SavedMealPlanSlotMutationRequest(
                operation="swap",
                slot=MealType.DINNER,
                meal_id="meal-new",
                replacing_meal_id="meal-old",
                effective_date=date(2026, 6, 24),
            ),
        )

        items = response.ui_block.payload["sections"][0]["items"]
        self.assertEqual(1, len(items))
        self.assertEqual("meal-new", items[0]["meal_id"])

    def test_mutate_slot_remove_against_existing_draft_day_plan(self) -> None:
        day_plan = make_saved_plan(
            plan_id="draft-day-3",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            status="draft",
            source_snapshot_id="snapshot-draft-day-3",
            plan_payload={
                "snapshot_id": "snapshot-draft-day-3",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "draft",
                "totals": {"calories": 100, "protein_g": 10, "carbs_g": 10, "fat_g": 5},
                "sections": [
                    {
                        "slot": "dinner",
                        "title": "Dinner",
                        "items": [{"meal_id": "meal-old", "name": "Old Meal"}],
                    }
                ],
            },
        )
        service = build_service(StubSavedMealPlanRepository(day_plan=day_plan))

        response = service.mutate_slot(
            current_user=build_user(),
            payload=SavedMealPlanSlotMutationRequest(
                operation="remove",
                slot=MealType.DINNER,
                meal_id="meal-old",
                effective_date=date(2026, 6, 24),
            ),
        )

        self.assertEqual(0, len(response.ui_block.payload["sections"]))

    def test_mutate_slot_raises_not_found_for_unknown_saved_plan_id(self) -> None:
        service = build_service(StubSavedMealPlanRepository())

        with self.assertRaises(SavedMealPlanNotFoundError):
            service.mutate_slot(
                current_user=build_user(),
                payload=SavedMealPlanSlotMutationRequest(
                    operation="add",
                    slot=MealType.LUNCH,
                    meal_id="meal-a",
                    saved_plan_id="does-not-exist",
                    effective_date=date(2026, 6, 24),
                ),
            )

    def test_refresh_plan_supporting_summaries_scales_ingredients_from_yield_servings(self) -> None:
        now = utc_now()
        meal = Meal(
            id="meal-scale-1",
            name="Rice Bowl",
            hero_image_url="hero.png",
            image_urls=["hero.png"],
            description="",
            meal_type=MealType.LUNCH,
            meal_types=[MealType.LUNCH],
            category_ids=[],
            culture_tags=[],
            diet_rules_supported=[],
            allergy_exclusions=[],
            prep_time_minutes=0,
            cook_time_minutes=0,
            difficulty=MealDifficulty.EASY,
            servings=2,
            nutritional_specs=[],
            nutrition_summary=MealNutritionSummary(calories=300, protein_g=10, carbs_g=40, fat_g=5),
            estimated_costs=[
                MealEstimatedCost(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=4.5,
                )
            ],
            recipe_steps=[],
            recipe_step_items=[],
            ingredient_items=[
                MealIngredient(
                    id="ingredient-rice",
                    name="Rice",
                    quantity=100,
                    unit="g",
                    optional=False,
                    linked_product_ids=["prod_rice"],
                    canonical_quantity=100,
                    canonical_unit="g",
                )
            ],
            linked_product_ids=["prod_rice"],
            chef_available=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        service = build_service(
            StubSavedMealPlanRepository(),
            meal_repository=StubMealRepository({"meal-scale-1": meal}),
        )

        refreshed = service._refresh_plan_supporting_summaries(
            user_id="user-1",
            payload_data={
                "view_mode": "day",
                "sections": [
                    {
                        "slot": "lunch",
                        "items": [
                            {
                                "meal_id": "meal-scale-1",
                                "name": "Rice Bowl",
                                "yield_servings": 4.0,
                                "meal_detail": {
                                    "meal_id": "meal-scale-1",
                                    "name": "Rice Bowl",
                                    "servings": 2.0,
                                    "yield_servings": 4.0,
                                    "ingredients": [
                                        {
                                            "id": "ingredient-rice",
                                            "name": "Rice",
                                            "quantity": 100,
                                            "unit": "g",
                                            "linked_product_ids": ["prod_rice"],
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
            },
            country_code="GB",
            household_size=2,
        )

        ingredient = refreshed["sections"][0]["items"][0]["meal_detail"]["ingredients"][0]
        synthetic_meal = service._presentation_meal_payload_from_item(
            slot="lunch",
            item=refreshed["sections"][0]["items"][0],
            key_prefix="test",
        )

        self.assertEqual(200.0, ingredient["quantity"])
        self.assertEqual("200 g", ingredient["quantity_label"])
        self.assertEqual(4.0, refreshed["sections"][0]["items"][0]["meal_detail"]["ingredients_scaled_for_servings"])
        self.assertIsNotNone(synthetic_meal)
        self.assertEqual(4.0, synthetic_meal["servings"])
        self.assertEqual(4.0, synthetic_meal["planned_servings"])

    def test_response_payload_includes_saved_plan_id(self) -> None:
        saved_plan = make_saved_plan(
            plan_id="saved-day-42",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            plan_payload={
                "snapshot_id": "snapshot-day-42",
                "title": "Day plan",
                "view_mode": "day",
                "state": "saved",
                "sections": [],
                "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
            },
        )
        service = build_service(StubSavedMealPlanRepository())

        payload = service._response_payload(saved_plan)

        self.assertEqual("saved-day-42", payload["saved_plan_id"])

    def test_presentation_meal_payload_zeroes_leftover_demand(self) -> None:
        service = build_service(StubSavedMealPlanRepository())

        synthetic_meal = service._presentation_meal_payload_from_item(
            slot="dinner",
            item={
                "meal_id": "meal-leftover-1",
                "name": "Stew",
                "source_type": "leftover",
                "yield_servings": 2.0,
                "meal_detail": {
                    "meal_id": "meal-leftover-1",
                    "name": "Stew",
                    "servings": 2.0,
                    "ingredients_scaled_for_servings": 2.0,
                    "ingredients": [
                        {
                            "id": "ingredient-1",
                            "name": "Yam",
                            "quantity": 300,
                            "unit": "g",
                            "linked_product_ids": ["prod_yam"],
                        }
                    ],
                },
            },
            key_prefix="leftover",
        )

        self.assertIsNotNone(synthetic_meal)
        self.assertEqual(2.0, synthetic_meal["servings"])
        self.assertEqual(0.0, synthetic_meal["planned_servings"])

    def test_resolve_home_day_prefers_weekly_plan_slice(self) -> None:
        weekly_plan = make_saved_plan(
            plan_id="saved-week-1",
            view_mode="week",
            effective_date=date(2026, 6, 22),
            title="This Week's Plan",
            week_start=date(2026, 6, 22),
            week_end=date(2026, 6, 28),
            linked_day_plan_ids=["saved-day-1"],
            plan_payload={
                "snapshot_id": "snapshot-week-1",
                "title": "This Week's Plan",
                "view_mode": "week",
                "state": "saved",
                "week_start": "2026-06-22",
                "week_end": "2026-06-28",
                "period_label": "This Week, Jun 22 - 28",
                "totals": {"calories": 2800, "protein_g": 170, "carbs_g": 290, "fat_g": 92},
                "bundle_summary": {
                    "meal_count": 7,
                    "household_size": 2,
                    "shared_product_count": 4,
                    "budget_status": "within_budget",
                },
                "inventory_summary": {
                    "used_items_count": 6,
                    "depleted_items_count": 1,
                },
                "cart_summary": {
                    "items_to_buy_count": 5,
                    "formatted_estimated_total_cost": "£26.00",
                },
                "days": [
                    {
                        "id": "day-2",
                        "date": "2026-06-24",
                        "accent_label": "Wednesday",
                        "full_label": "Wednesday, June 24",
                        "calories": 540,
                        "tracked_text": "Tracked 0/1 meals",
                        "totals": {"calories": 540, "protein_g": 29, "carbs_g": 48, "fat_g": 20},
                        "sections": [
                            {
                                "id": "lunch",
                                "slot": "lunch",
                                "title": "Lunch",
                                "items": [{"id": "meal-3", "name": "Chicken Wrap"}],
                            }
                        ],
                    }
                ],
                "daily_snapshots": [
                    {
                        "snapshot_id": "snapshot-day-wed",
                        "effective_date": "2026-06-24",
                        "title": "Wednesday Plan",
                        "view_mode": "day",
                        "state": "saved",
                        "tracked_text": "Tracked 0/1 meals",
                        "totals": {"calories": 540, "protein_g": 29, "carbs_g": 48, "fat_g": 20},
                        "sections": [
                            {
                                "id": "lunch",
                                "slot": "lunch",
                                "title": "Lunch",
                                "items": [{"id": "meal-3", "name": "Chicken Wrap"}],
                            }
                        ],
                        "parent_day_id": "day-2",
                    }
                ],
            },
        )
        day_plan = make_saved_plan(
            plan_id="saved-day-1",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            title="Standalone Day Plan",
            plan_payload={
                "snapshot_id": "snapshot-day-1",
                "title": "Standalone Day Plan",
                "view_mode": "day",
                "state": "saved",
                "totals": {"calories": 620, "protein_g": 32, "carbs_g": 56, "fat_g": 18},
                "sections": [],
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(day_plan=day_plan, weekly_plan=weekly_plan)
        )

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="day",
        )

        self.assertEqual("saved_weekly_plan_day_slice", result.resolution_mode)
        self.assertIsNotNone(result.ui_block)
        self.assertEqual("meal_plan_draft", result.ui_block.block_type)
        self.assertEqual("2026-06-24", result.ui_block.payload["effective_date"])
        self.assertEqual("day", result.ui_block.payload["view_mode"])
        self.assertEqual(540, result.ui_block.payload["totals"]["calories"])
        self.assertEqual(1, len(result.ui_block.payload["sections"]))
        self.assertEqual("Wednesday, June 24", result.ui_block.title)

    def test_resolve_home_day_slice_from_missing_groceries_week_preserves_blocked_state(self) -> None:
        weekly_plan = make_saved_plan(
            plan_id="saved-week-missing-1",
            view_mode="week",
            effective_date=date(2026, 6, 22),
            title="This Week's Plan",
            week_start=date(2026, 6, 22),
            week_end=date(2026, 6, 28),
            linked_day_plan_ids=["saved-day-1"],
            status="missing_groceries",
            plan_payload={
                "snapshot_id": "snapshot-week-missing-1",
                "title": "This Week's Plan",
                "view_mode": "week",
                "state": "missing_groceries",
                "week_start": "2026-06-22",
                "week_end": "2026-06-28",
                "totals": {"calories": 2800, "protein_g": 170, "carbs_g": 290, "fat_g": 92},
                "bundle_summary": {
                    "meal_count": 1,
                    "household_size": 2,
                    "shared_product_count": 0,
                    "budget_status": "within_budget",
                },
                "inventory_summary": {
                    "shortages": [
                        {
                            "product_id": "prod-1",
                            "product_name": "Chicken Breast",
                            "remaining_shortage": 2,
                            "unit": "pcs",
                        }
                    ],
                    "used_items_count": 0,
                    "depleted_items_count": 0,
                },
                "cart_summary": {
                    "items_to_buy_count": 1,
                    "buy_items": [
                        {
                            "product_id": "prod-1",
                            "product_name": "Chicken Breast",
                            "required_quantity": 2,
                            "unit": "pcs",
                            "slots": ["lunch"],
                            "meal_ids": ["meal-3"],
                            "is_shared": False,
                        }
                    ],
                },
                "days": [
                    {
                        "id": "day-2",
                        "date": "2026-06-24",
                        "accent_label": "Wednesday",
                        "full_label": "Wednesday, June 24",
                        "calories": 540,
                        "tracked_text": "Tracked 0/1 meals",
                        "totals": {"calories": 540, "protein_g": 29, "carbs_g": 48, "fat_g": 20},
                        "sections": [
                            {
                                "id": "lunch",
                                "slot": "lunch",
                                "title": "Lunch",
                                "items": [{"id": "meal-3", "name": "Chicken Wrap"}],
                            }
                        ],
                    }
                ],
                "daily_snapshots": [
                    {
                        "snapshot_id": "snapshot-day-wed",
                        "effective_date": "2026-06-24",
                        "title": "Wednesday Plan",
                        "view_mode": "day",
                        "state": "saved",
                        "tracked_text": "Tracked 0/1 meals",
                        "totals": {"calories": 540, "protein_g": 29, "carbs_g": 48, "fat_g": 20},
                        "sections": [
                            {
                                "id": "lunch",
                                "slot": "lunch",
                                "title": "Lunch",
                                "items": [{"id": "meal-3", "name": "Chicken Wrap"}],
                            }
                        ],
                        "parent_day_id": "day-2",
                    }
                ],
            },
        )
        service = build_service(StubSavedMealPlanRepository(weekly_plan=weekly_plan))

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="day",
        )

        self.assertEqual("missing_groceries", result.ui_block.payload["state"])
        self.assertIsNone(result.ui_block.payload["primary_action"])

    def test_resolve_home_day_returns_saved_day_block(self) -> None:
        day_plan = make_saved_plan(
            plan_id="saved-day-1",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            plan_payload={
                "snapshot_id": "snapshot-day-1",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "saved",
                "totals": {"calories": 540, "protein_g": 32, "carbs_g": 56, "fat_g": 18},
                "sections": [
                    {
                        "id": "breakfast",
                        "slot": "breakfast",
                        "title": "Breakfast",
                        "items": [{"id": "meal-1", "name": "Greek Yogurt Bowl"}],
                    }
                ],
            },
        )
        service = build_service(StubSavedMealPlanRepository(day_plan=day_plan))

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="day",
        )

        self.assertEqual("saved_day_plan", result.resolution_mode)
        self.assertIsNotNone(result.ui_block)
        self.assertEqual("meal_plan_draft", result.ui_block.block_type)
        self.assertEqual("saved-day-1", result.ui_block.id)

    def test_resolve_home_day_refreshes_saved_meal_hero_images_from_catalog(self) -> None:
        day_plan = make_saved_plan(
            plan_id="saved-day-hero-1",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            plan_payload={
                "snapshot_id": "snapshot-day-hero-1",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "saved",
                "totals": {"calories": 540, "protein_g": 32, "carbs_g": 56, "fat_g": 18},
                "sections": [
                    {
                        "id": "breakfast",
                        "slot": "breakfast",
                        "title": "Breakfast",
                        "items": [
                            {
                                "meal_id": "meal-hero-1",
                                "name": "Berry Oats",
                                "hero_image_url": "https://old.example.com/berry-oats.jpg",
                                "meal_detail": {
                                    "meal_id": "meal-hero-1",
                                    "name": "Berry Oats",
                                    "hero_image_url": "https://old.example.com/berry-oats.jpg",
                                },
                            }
                        ],
                    }
                ],
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(day_plan=day_plan),
            meal_repository=StubMealRepository(
                {"meal-hero-1": make_meal(meal_id="meal-hero-1", hero_image_url="https://cdn.example.com/berry-oats-new.jpg")}
            ),
        )

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="day",
        )

        item = result.ui_block.payload["sections"][0]["items"][0]
        self.assertEqual("https://cdn.example.com/berry-oats-new.jpg", item["hero_image_url"])
        self.assertEqual("https://cdn.example.com/berry-oats-new.jpg", item["meal_detail"]["hero_image_url"])

    def test_resolve_home_day_hides_draft_day_plan(self) -> None:
        day_plan = make_saved_plan(
            plan_id="draft-day-1",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            status="draft",
            source_snapshot_id="snapshot-draft-day-1",
            plan_payload={
                "snapshot_id": "snapshot-draft-day-1",
                "title": "Meal Plan",
                "view_mode": "day",
                "state": "draft",
                "totals": {"calories": 540, "protein_g": 32, "carbs_g": 56, "fat_g": 18},
                "sections": [],
                "primary_action": None,
            },
        )
        service = build_service(StubSavedMealPlanRepository(day_plan=day_plan))

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="day",
        )

        self.assertEqual("empty_day", result.resolution_mode)
        self.assertIsNone(result.ui_block)

    def test_resolve_home_week_returns_saved_weekly_plan(self) -> None:
        weekly_plan = make_saved_plan(
            plan_id="saved-week-1",
            view_mode="week",
            effective_date=date(2026, 6, 22),
            week_start=date(2026, 6, 22),
            week_end=date(2026, 6, 28),
            linked_day_plan_ids=["day-1", "day-2"],
            plan_payload={
                "snapshot_id": "snapshot-week-1",
                "title": "This Week's Plan",
                "view_mode": "week",
                "state": "saved",
                "week_start": "2026-06-22",
                "week_end": "2026-06-28",
                "totals": {"calories": 2800, "protein_g": 170, "carbs_g": 290, "fat_g": 92},
                "sections": [],
                "days": [],
                "daily_snapshots": [],
            },
        )
        service = build_service(StubSavedMealPlanRepository(weekly_plan=weekly_plan))

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
        )

        self.assertEqual("saved_weekly_plan", result.resolution_mode)
        self.assertIsNotNone(result.ui_block)
        self.assertEqual("meal_plan_week", result.ui_block.block_type)
        self.assertEqual("saved-week-1", result.ui_block.id)

    def test_resolve_home_week_hides_draft_weekly_plan(self) -> None:
        weekly_plan = make_saved_plan(
            plan_id="draft-week-1",
            view_mode="week",
            effective_date=date(2026, 6, 22),
            week_start=date(2026, 6, 22),
            week_end=date(2026, 6, 28),
            status="draft",
            source_snapshot_id="snapshot-draft-week-1",
            plan_payload={
                "snapshot_id": "snapshot-draft-week-1",
                "title": "This Week's Plan",
                "view_mode": "week",
                "state": "draft",
                "week_start": "2026-06-22",
                "week_end": "2026-06-28",
                "totals": {"calories": 2800, "protein_g": 170, "carbs_g": 290, "fat_g": 92},
                "sections": [],
                "days": [],
                "daily_snapshots": [],
                "primary_action": None,
            },
        )
        service = build_service(StubSavedMealPlanRepository(weekly_plan=weekly_plan))

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
        )

        self.assertEqual("empty_week", result.resolution_mode)
        self.assertIsNone(result.ui_block)

    def test_resolve_home_week_composes_missing_groceries_state_from_saved_day_plans(self) -> None:
        monday_plan = make_saved_plan(
            plan_id="saved-day-mon",
            view_mode="day",
            effective_date=date(2026, 6, 22),
            source_snapshot_id="snapshot-day-mon",
            status="missing_groceries",
            plan_payload={
                "title": "Monday Plan",
                "view_mode": "day",
                "state": "missing_groceries",
                "tracked_text": "Tracked 0/1 meals",
                "totals": {"calories": 620, "protein_g": 31, "carbs_g": 71, "fat_g": 16},
                "sections": [
                    {
                        "id": "breakfast",
                        "slot": "breakfast",
                        "title": "Breakfast",
                        "items": [{"id": "meal-1", "name": "Oats"}],
                    }
                ],
            },
        )
        service = build_service(StubSavedMealPlanRepository(range_plans=[monday_plan]))

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
        )

        self.assertEqual("missing_groceries", result.ui_block.payload["state"])
        self.assertIsNone(result.ui_block.payload["primary_action"])

    def test_resolve_home_week_composes_from_saved_day_plans(self) -> None:
        monday_plan = make_saved_plan(
            plan_id="saved-day-mon",
            view_mode="day",
            effective_date=date(2026, 6, 22),
            source_snapshot_id="snapshot-day-mon",
            plan_payload={
                "title": "Monday Plan",
                "view_mode": "day",
                "state": "saved",
                "tracked_text": "Tracked 0/2 meals",
                "totals": {"calories": 620, "protein_g": 31, "carbs_g": 71, "fat_g": 16},
                "sections": [
                    {
                        "id": "breakfast",
                        "slot": "breakfast",
                        "title": "Breakfast",
                        "items": [{"id": "meal-1", "name": "Oats"}],
                    },
                    {
                        "id": "dinner",
                        "slot": "dinner",
                        "title": "Dinner",
                        "items": [{"id": "meal-2", "name": "Rice Bowl"}],
                    },
                ],
                "bundle_summary": {"household_size": 2},
            },
        )
        wednesday_plan = make_saved_plan(
            plan_id="saved-day-wed",
            view_mode="day",
            effective_date=date(2026, 6, 24),
            source_snapshot_id="snapshot-day-wed",
            plan_payload={
                "title": "Wednesday Plan",
                "view_mode": "day",
                "state": "saved",
                "tracked_text": "Tracked 0/1 meals",
                "totals": {"calories": 540, "protein_g": 29, "carbs_g": 48, "fat_g": 20},
                "sections": [
                    {
                        "id": "lunch",
                        "slot": "lunch",
                        "title": "Lunch",
                        "items": [{"id": "meal-3", "name": "Chicken Wrap"}],
                    }
                ],
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(range_plans=[monday_plan, wednesday_plan])
        )

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
        )

        self.assertEqual("composed_from_day_plans", result.resolution_mode)
        self.assertIsNotNone(result.ui_block)
        payload = result.ui_block.payload
        self.assertEqual("week", payload["view_mode"])
        self.assertEqual(2, len(payload["days"]))
        self.assertEqual(2, len(payload["daily_snapshots"]))
        self.assertEqual("Jun 22 - 28", payload["period_label"])
        self.assertEqual(1160, payload["totals"]["calories"])
        self.assertEqual(3, payload["bundle_summary"]["meal_count"])

    def test_resolve_home_week_returns_empty_when_no_weekly_or_day_plans_exist(self) -> None:
        service = build_service(StubSavedMealPlanRepository())

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
        )

        self.assertEqual("empty_week", result.resolution_mode)
        self.assertIsNone(result.ui_block)

    def test_resolve_planner_week_uses_payload_week_bounds_when_model_dates_missing(self) -> None:
        weekly_plan = make_saved_plan(
            plan_id="draft-week-payload-1",
            view_mode="week",
            effective_date=None,
            week_start=None,
            week_end=None,
            status="draft",
            source_snapshot_id="snapshot-draft-week-payload-1",
            plan_payload={
                "snapshot_id": "snapshot-draft-week-payload-1",
                "title": "This Week's Plan",
                "view_mode": "week",
                "state": "draft",
                "week_start": "2026-06-22",
                "week_end": "2026-06-28",
                "days": [
                    {
                        "date": "2026-06-22",
                        "sections": [
                            {
                                "id": "breakfast",
                                "slot": "breakfast",
                                "title": "Breakfast",
                                "items": [{"meal_id": "meal-1", "name": "Oats"}],
                            }
                        ],
                    }
                ],
                "daily_snapshots": [],
                "sections": [],
                "primary_action": {
                    "action_type": "save_meal_plan",
                    "label": "Review plan",
                    "payload": {},
                },
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(saved_plans=[weekly_plan])
        )

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
            include_drafts=True,
        )

        self.assertEqual("draft_weekly_plan", result.resolution_mode)
        self.assertIsNotNone(result.ui_block)
        self.assertEqual("meal_plan_week", result.ui_block.block_type)
        self.assertEqual("draft-week-payload-1", result.ui_block.id)

    def test_resolve_planner_week_uses_payload_effective_dates_for_draft_day_plans(self) -> None:
        monday_plan = make_saved_plan(
            plan_id="draft-day-payload-mon",
            view_mode="day",
            effective_date=None,
            status="draft",
            source_snapshot_id="snapshot-draft-day-payload-mon",
            plan_payload={
                "snapshot_id": "snapshot-draft-day-payload-mon",
                "title": "Monday Plan",
                "view_mode": "day",
                "state": "draft",
                "effective_date": "2026-06-22",
                "tracked_text": "Tracked 0/1 meals",
                "totals": {"calories": 620, "protein_g": 31, "carbs_g": 71, "fat_g": 16},
                "sections": [
                    {
                        "id": "breakfast",
                        "slot": "breakfast",
                        "title": "Breakfast",
                        "items": [{"meal_id": "meal-1", "name": "Oats"}],
                    }
                ],
            },
        )
        wednesday_plan = make_saved_plan(
            plan_id="draft-day-payload-wed",
            view_mode="day",
            effective_date=None,
            status="draft",
            source_snapshot_id="snapshot-draft-day-payload-wed",
            plan_payload={
                "snapshot_id": "snapshot-draft-day-payload-wed",
                "title": "Wednesday Plan",
                "view_mode": "day",
                "state": "draft",
                "effective_date": "2026-06-24",
                "tracked_text": "Tracked 0/1 meals",
                "totals": {"calories": 540, "protein_g": 29, "carbs_g": 48, "fat_g": 20},
                "sections": [
                    {
                        "id": "lunch",
                        "slot": "lunch",
                        "title": "Lunch",
                        "items": [{"meal_id": "meal-3", "name": "Chicken Wrap"}],
                    }
                ],
            },
        )
        service = build_service(
            StubSavedMealPlanRepository(saved_plans=[monday_plan, wednesday_plan])
        )

        result = service.resolve_home_plan(
            current_user=build_user(),
            selected_date=date(2026, 6, 24),
            view_mode="week",
            include_drafts=True,
        )

        self.assertEqual("draft_composed_from_day_plans", result.resolution_mode)
        self.assertIsNotNone(result.ui_block)
        self.assertEqual(2, len(result.ui_block.payload["days"]))
