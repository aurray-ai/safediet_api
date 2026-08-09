from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException, status

from app.agents.meal_conversation.state import MealConversationTurnResult
from app.models.grocery import CountryCode, CountryPrice, CultureTag, CurrencyCode, GroceryProduct
from app.models.meal import (
    Meal,
    MealDifficulty,
    MealEstimatedCost,
    MealIngredient,
    MealNutritionSummary,
    MealRecipeStep,
    MealType,
)
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.models.user_pantry_item import UserPantryItem
from app.schemas.meal_conversation import MealPlannerRequest
from app.services.meal_conversation_service import MealConversationService
from app.services.meal_semantic_search_service import MealSemanticSearchItem


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user(*, goal: str | None, weekly_budget: int | None = 80, include_profile_defaults: bool = True) -> User:
    configuration = {}
    if goal is not None:
        configuration["goal"] = goal
    if weekly_budget is not None:
        configuration["weekly_budget"] = weekly_budget
    if include_profile_defaults:
        configuration["diet_rules"] = ["high_protein"]
        configuration["allergies"] = ["peanut"]
        configuration["culture_preferences"] = ["british"]
        configuration["household_size"] = 2
    return User(
        id="user-1",
        name="Favour",
        email="favour@example.com",
        password_hash="hashed",
        user_types=[UserType.CUSTOMER],
        user_configuration=configuration,
        created_at=utc_now(),
    )


def build_meal(*, meal_id: str, name: str, meal_type: MealType, protein: float, calories: int) -> Meal:
    return Meal(
        id=meal_id,
        name=name,
        hero_image_url="https://example.com/meal.jpg",
        image_urls=["https://example.com/meal.jpg"],
        description=f"{name} description",
        meal_type=meal_type,
        category_ids=["cat-1"],
        culture_tags=["british"],
        diet_rules_supported=["high_protein"],
        allergy_exclusions=["peanut"],
        prep_time_minutes=10,
        cook_time_minutes=20,
        difficulty=MealDifficulty.EASY,
        servings=2,
        nutritional_specs=[],
        nutrition_summary=MealNutritionSummary(
            calories=calories,
            protein_g=protein,
            carbs_g=30,
            fat_g=12,
        ),
        estimated_costs=[
            MealEstimatedCost(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=4.5,
            )
        ],
        recipe_steps=["Cook it."],
        recipe_step_items=[MealRecipeStep(instruction="Cook it.", ingredient_ids=[], image_url=None)],
        ingredient_items=[
            MealIngredient(
                id="ingredient-1",
                name="Chicken",
                quantity=200,
                unit="g",
                optional=False,
                linked_product_ids=["prod-1"],
            )
        ],
        linked_product_ids=["prod-1"],
        chef_available=False,
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
        meal_types=[meal_type],
    )


def build_grocery_product(*, product_id: str, name: str, amount: float, price_unit: str) -> GroceryProduct:
    return GroceryProduct(
        id=product_id,
        category_id="cat-1",
        img_url="https://example.com/product.jpg",
        product=name,
        product_tags=[],
        culture_tags=[CultureTag.BRITISH],
        nutritional_specs=[],
        prices=[
            CountryPrice(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=amount,
                price_unit=price_unit,
                source="test",
                updated_at=utc_now(),
                is_active=True,
            )
        ],
        description=f"{name} description",
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def build_pantry_item(*, product_id: str, product_name: str, quantity: float, unit: str) -> UserPantryItem:
    return UserPantryItem(
        id=f"pantry-{product_id}",
        user_id="user-1",
        product_id=product_id,
        product_name=product_name,
        quantity=quantity,
        unit=unit,
        country_code=CountryCode.UNITED_KINGDOM,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def make_saved_plan(
    *,
    saved_plan_id: str,
    snapshot_id: str,
    status: str = "draft",
    view_mode: str = "day",
    effective_date: date = date(2026, 6, 29),
    week_start: date | None = None,
    week_end: date | None = None,
    planned_meals: list[dict[str, object]] | None = None,
    plan_payload: dict[str, object] | None = None,
) -> SavedMealPlan:
    now = utc_now()
    resolved_payload = (
        dict(plan_payload)
        if plan_payload is not None
        else {
            "snapshot_id": snapshot_id,
            "title": "Meal Plan",
            "view_mode": view_mode,
            "state": status,
            "sections": [],
        }
    )
    return SavedMealPlan(
        id=saved_plan_id,
        user_id="user-1",
        title="Meal Plan",
        status=status,
        view_mode=view_mode,
        plan_scope="standalone_day" if view_mode == "day" else "weekly_parent",
        effective_date=effective_date,
        week_start=week_start,
        week_end=week_end,
        day_index=None,
        parent_saved_plan_id=None,
        source_saved_plan_id=None,
        linked_day_plan_ids=[],
        meal_type=MealType.DINNER,
        country_code=CountryCode.UNITED_KINGDOM,
        planned_meals=list(planned_meals or []),
        plan_payload=resolved_payload,
        requested_culture="british",
        user_goal="weight_gain",
        source_snapshot_id=snapshot_id,
        source_conversation_id="direct-planner",
        agent_type="meal_planner_agent",
        created_at=now,
        updated_at=now,
    )


class FakeSemanticSearchService:
    def __init__(self, items_by_type: dict[str, list[MealSemanticSearchItem]]) -> None:
        self.items_by_type = items_by_type
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(dict(kwargs))
        return list(self.items_by_type.get(str(kwargs["meal_type"]), []))


class FakeSavedMealPlanRepository:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        self.existing_by_snapshot: dict[str, SavedMealPlan] = {}
        self.day_plans_by_date: dict[date, SavedMealPlan] = {}
        self.weekly_plans_by_bounds: dict[tuple[date, date], SavedMealPlan] = {}

    def get_by_user_snapshot(self, *, user_id: str, source_snapshot_id: str) -> SavedMealPlan | None:
        return self.existing_by_snapshot.get(source_snapshot_id)

    def get_saved_day_plan_for_date(
        self,
        *,
        user_id: str,
        effective_date: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        return self.day_plans_by_date.get(effective_date)

    def get_saved_weekly_plan_for_week(
        self,
        *,
        user_id: str,
        week_start: date,
        week_end: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        return self.weekly_plans_by_bounds.get((week_start, week_end))

    def list_saved_day_plans_in_range(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
        limit: int = 500,
        allowed_statuses: list[str] | None = None,
    ) -> list[SavedMealPlan]:
        matches = [
            saved_plan
            for effective_date, saved_plan in self.day_plans_by_date.items()
            if start_date <= effective_date <= end_date and (not allowed_statuses or saved_plan.status in allowed_statuses)
        ]
        matches.sort(key=lambda item: item.effective_date or start_date)
        return matches[:limit]

    def upsert_saved_plan(self, **kwargs) -> SavedMealPlan:
        self.upsert_calls.append(dict(kwargs))
        status = str(kwargs.get("status") or "saved")
        saved_plan = make_saved_plan(
            saved_plan_id=f"saved-{len(self.upsert_calls)}",
            snapshot_id=str(kwargs["source_snapshot_id"]),
            status=status,
            view_mode=str(kwargs.get("view_mode") or "day"),
        )
        self.existing_by_snapshot[saved_plan.source_snapshot_id] = saved_plan
        if saved_plan.view_mode == "day" and saved_plan.effective_date is not None:
            self.day_plans_by_date[saved_plan.effective_date] = saved_plan
        if saved_plan.view_mode == "week" and saved_plan.week_start is not None and saved_plan.week_end is not None:
            self.weekly_plans_by_bounds[(saved_plan.week_start, saved_plan.week_end)] = saved_plan
        return saved_plan


class PlannerServiceUnderTest(MealConversationService):
    def __init__(
        self,
        *,
        search_service: FakeSemanticSearchService,
        grocery_products: list[GroceryProduct] | None = None,
        pantry_items: list[UserPantryItem] | None = None,
    ) -> None:
        grocery_repository = SimpleNamespace(
            list_products_by_ids=lambda product_ids: [
                product
                for product in list(grocery_products or [])
                if product.id in set(product_ids)
            ],
        )
        super().__init__(
            settings=SimpleNamespace(
                openai_api_key=None,
                openai_meal_conversation_model="",
                openai_meal_conversation_timeout_seconds=0,
                openai_meal_search_embedding_model="",
                openai_meal_search_embedding_timeout_seconds=0,
                meal_semantic_search_candidate_pool_limit=24,
                meal_semantic_search_embedding_batch_size=8,
            ),
            user_repository=SimpleNamespace(),
            meal_conversation_repository=SimpleNamespace(),
            meal_repository=SimpleNamespace(),
            grocery_repository=grocery_repository,
            saved_meal_plan_repository=FakeSavedMealPlanRepository(),
            user_pantry_repository=SimpleNamespace(list_items=lambda user_id: list(pantry_items or [])),
            kitchen_service=SimpleNamespace(
                list_planning_items=lambda user_id, include_saved_plan_id=None: [],
                release_saved_plan_allocations=lambda **kwargs: None,
                sync_saved_plan_allocations=lambda **kwargs: None,
            ),
            user_meal_usage_service=SimpleNamespace(),
        )
        self.search_service = search_service
        self.planner_call: dict[str, object] | None = None
        self.saved_repo = self._saved_meal_plan_repository

    def _meal_semantic_search_service(self) -> FakeSemanticSearchService:
        return self.search_service

    def _run_prepared_meal_planner(
        self,
        *,
        current_user: User,
        message: str,
        request_type: str,
        action_payload: dict[str, object],
        explicit_meal_type: MealType | None,
        explicit_country_code: CountryCode | None,
        conversation_id: str | None,
        trace_id: str | None,
        monitoring_recorder: object | None = None,
    ) -> MealConversationTurnResult:
        self.planner_call = {
            "current_user": current_user,
            "message": message,
            "request_type": request_type,
            "action_payload": action_payload,
            "explicit_meal_type": explicit_meal_type,
            "explicit_country_code": explicit_country_code,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
        }
        planned_meals = []
        for slot_key in ("breakfast_slots", "lunch_slots", "dinner_slots", "snack_slots"):
            slot_candidates = list(action_payload.get(slot_key, []))
            if not slot_candidates:
                continue
            slot_name = slot_key.removesuffix("_slots")
            chosen = slot_candidates[0]
            planned_meals.append(
                {
                    "slot": slot_name,
                    "meal_id": chosen["id"],
                    "meal_name": chosen["name"],
                    "meal_source": "catalog",
                    "created_meal_draft": None,
                }
            )
        snapshot_id = f"{request_type}-snapshot"
        block_type = "meal_plan_week" if request_type == "generate_week_plan" else "meal_plan_draft"
        return MealConversationTurnResult(
            assistant_text="Planner completed.",
            turn_mode="day_plan_generated",
            agent_type="meal_planner_agent",
            target_domain="meal_planning",
            meal_type=explicit_meal_type,
            country_code=explicit_country_code,
            planned_meals=planned_meals,
            requested_culture=action_payload.get("requested_culture"),
            metadata={"issue": None},
            ui_blocks=[
                {
                    "id": snapshot_id,
                    "block_type": block_type,
                    "title": "Meal Plan",
                    "payload": {
                        "snapshot_id": snapshot_id,
                        "title": "Meal Plan",
                        "view_mode": "week" if request_type == "generate_week_plan" else "day",
                        "state": "draft",
                        "effective_date": action_payload.get("effective_date"),
                        "sections": [],
                    },
                }
            ],
        )


class MealPlannerServiceTests(unittest.TestCase):
    def test_day_plan_generation_rejects_existing_meals_for_same_day(self) -> None:
        service = PlannerServiceUnderTest(search_service=FakeSemanticSearchService({}))
        effective_date = date(2026, 7, 1)
        service.saved_repo.day_plans_by_date[effective_date] = make_saved_plan(
            saved_plan_id="saved-day-1",
            snapshot_id="existing-day",
            status="saved",
            effective_date=effective_date,
            plan_payload={
                "snapshot_id": "existing-day",
                "title": "Existing Day Plan",
                "view_mode": "day",
                "state": "saved",
                "sections": [{"id": "breakfast", "items": [{"meal_id": "meal-1"}]}],
            },
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Plan my meals for today.",
                "type": "generate_day_plan",
                "slots": ["breakfast"],
                "effective_date": effective_date.isoformat(),
            }
        )

        with self.assertRaises(HTTPException) as context:
            service.plan_meals(
                current_user=build_user(goal="Weight Gain"),
                payload=payload,
            )

        self.assertEqual(status.HTTP_409_CONFLICT, context.exception.status_code)
        self.assertIn(effective_date.isoformat(), str(context.exception.detail))
        self.assertEqual([], service.search_service.calls)
        self.assertIsNone(service.planner_call)

    def test_day_plan_generation_rejects_existing_weekly_meals_for_same_day(self) -> None:
        service = PlannerServiceUnderTest(search_service=FakeSemanticSearchService({}))
        effective_date = date(2026, 7, 2)
        week_start = date(2026, 6, 29)
        week_end = date(2026, 7, 5)
        service.saved_repo.weekly_plans_by_bounds[(week_start, week_end)] = make_saved_plan(
            saved_plan_id="saved-week-1",
            snapshot_id="existing-week",
            status="saved",
            view_mode="week",
            effective_date=week_start,
            week_start=week_start,
            week_end=week_end,
            plan_payload={
                "snapshot_id": "existing-week",
                "title": "Existing Weekly Plan",
                "view_mode": "week",
                "state": "saved",
                "days": [
                    {
                        "date": effective_date.isoformat(),
                        "sections": [{"id": "dinner", "items": [{"meal_id": "meal-2"}]}],
                    }
                ],
            },
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Plan my meals for today.",
                "type": "generate_day_plan",
                "slots": ["dinner"],
                "effective_date": effective_date.isoformat(),
            }
        )

        with self.assertRaises(HTTPException) as context:
            service.plan_meals(
                current_user=build_user(goal="Weight Gain"),
                payload=payload,
            )

        self.assertEqual(status.HTTP_409_CONFLICT, context.exception.status_code)
        self.assertIn(effective_date.isoformat(), str(context.exception.detail))
        self.assertEqual([], service.search_service.calls)
        self.assertIsNone(service.planner_call)

    def test_week_plan_generation_rejects_existing_meals_after_effective_date(self) -> None:
        service = PlannerServiceUnderTest(search_service=FakeSemanticSearchService({}))
        existing_date = date(2026, 7, 3)
        service.saved_repo.day_plans_by_date[existing_date] = make_saved_plan(
            saved_plan_id="saved-day-2",
            snapshot_id="existing-week-day",
            status="saved",
            effective_date=existing_date,
            planned_meals=[{"slot": "breakfast", "meal_id": "meal-3"}],
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Build me a weekly meal plan.",
                "type": "generate_week_plan",
                "slots": ["breakfast"],
                "effective_date": "2026-07-01",
            }
        )

        with self.assertRaises(HTTPException) as context:
            service.plan_meals(
                current_user=build_user(goal="Weight Gain"),
                payload=payload,
            )

        self.assertEqual(status.HTTP_409_CONFLICT, context.exception.status_code)
        self.assertIn(existing_date.isoformat(), str(context.exception.detail))
        self.assertEqual([], service.search_service.calls)
        self.assertIsNone(service.planner_call)

    def test_week_plan_generation_allows_existing_meals_before_effective_date(self) -> None:
        breakfast_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-breakfast-1",
                name="Egg Bowl",
                meal_type=MealType.BREAKFAST,
                protein=25,
                calories=420,
            ),
            semantic_score=0.91,
            why_it_matched=["High protein"],
            estimated_cost_amount=4.5,
        )
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService({"breakfast": [breakfast_item]})
        )
        service.saved_repo.day_plans_by_date[date(2026, 6, 29)] = make_saved_plan(
            saved_plan_id="saved-day-3",
            snapshot_id="existing-monday",
            status="saved",
            effective_date=date(2026, 6, 29),
            planned_meals=[{"slot": "breakfast", "meal_id": "meal-4"}],
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Build me a weekly meal plan.",
                "type": "generate_week_plan",
                "slots": ["breakfast"],
                "effective_date": "2026-07-01",
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
        )

        self.assertEqual(1, len(service.search_service.calls))
        self.assertEqual("generate_week_plan", service.planner_call["request_type"])
        self.assertEqual("day_plan_generated", result.turn_result.turn_mode)

    def test_week_plan_generation_ignores_conflicts_on_unselected_days(self) -> None:
        breakfast_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-breakfast-1",
                name="Egg Bowl",
                meal_type=MealType.BREAKFAST,
                protein=25,
                calories=420,
            ),
            semantic_score=0.91,
            why_it_matched=["High protein"],
            estimated_cost_amount=4.5,
        )
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService({"breakfast": [breakfast_item]})
        )
        service.saved_repo.day_plans_by_date[date(2026, 7, 3)] = make_saved_plan(
            saved_plan_id="saved-day-4",
            snapshot_id="existing-friday",
            status="saved",
            effective_date=date(2026, 7, 3),
            planned_meals=[{"slot": "breakfast", "meal_id": "meal-9"}],
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Build me a weekly meal plan.",
                "type": "generate_week_plan",
                "slots": ["breakfast"],
                "effective_date": "2026-07-01",
                "selected_dates": ["2026-07-01", "2026-07-02"],
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
        )

        self.assertEqual(1, len(service.search_service.calls))
        self.assertEqual("generate_week_plan", service.planner_call["request_type"])
        self.assertEqual("day_plan_generated", result.turn_result.turn_mode)

    def test_plan_meals_requires_user_context_before_search(self) -> None:
        service = PlannerServiceUnderTest(search_service=FakeSemanticSearchService({}))
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Plan breakfast",
                "type": "generate_day_plan",
                "slot": "breakfast",
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal=None, weekly_budget=None, include_profile_defaults=False),
            payload=payload,
        )

        self.assertEqual("clarification_request", result.turn_result.turn_mode)
        self.assertEqual("missing_user_context", result.turn_result.metadata["issue"])
        self.assertEqual([], service.search_service.calls)
        self.assertEqual([], result.semantic_queries)

    def test_plan_meals_runs_semantic_search_and_prepares_slot_payloads(self) -> None:
        breakfast_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-breakfast-1",
                name="Egg Bowl",
                meal_type=MealType.BREAKFAST,
                protein=25,
                calories=420,
            ),
            semantic_score=0.91,
            why_it_matched=["High protein"],
            estimated_cost_amount=4.5,
        )
        lunch_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-lunch-1",
                name="Chicken Rice Bowl",
                meal_type=MealType.LUNCH,
                protein=38,
                calories=560,
            ),
            semantic_score=0.88,
            why_it_matched=["Balanced"],
            estimated_cost_amount=4.8,
        )
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService(
                {
                    "breakfast": [breakfast_item],
                    "lunch": [lunch_item],
                }
            )
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Plan breakfast and lunch for me.",
                "type": "generate_day_plan",
                "slots": ["breakfast", "lunch"],
                "requested_culture": "british",
                "country_code": "GB",
                "low_budget_mode": True,
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
            trace_id="trace-1",
        )

        self.assertEqual(2, len(service.search_service.calls))
        self.assertEqual("breakfast", service.search_service.calls[0]["meal_type"])
        self.assertEqual("lunch", service.search_service.calls[1]["meal_type"])
        self.assertEqual("british", result.prepared_action_payload["requested_culture"])
        self.assertEqual("GB", result.prepared_action_payload["country_code"])
        self.assertEqual(2, result.prepared_action_payload["user_context"]["household_size"])
        self.assertTrue(result.prepared_action_payload["ranked_bundles"])
        self.assertIn("breakfast_slots", result.prepared_action_payload)
        self.assertIn("lunch_slots", result.prepared_action_payload)
        self.assertEqual("Egg Bowl", result.prepared_action_payload["breakfast_slots"][0]["name"])
        self.assertEqual("Chicken Rice Bowl", result.prepared_action_payload["lunch_slots"][0]["name"])
        self.assertIsNotNone(service.planner_call)
        assert service.planner_call is not None
        self.assertEqual("generate_day_plan", service.planner_call["request_type"])
        self.assertEqual("trace-1", service.planner_call["trace_id"])
        self.assertEqual("day_plan_generated", result.turn_result.turn_mode)
        self.assertEqual(2, len(result.turn_result.planned_meals))
        self.assertEqual(["breakfast", "lunch"], [item.slot.value for item in result.semantic_queries])
        self.assertIn("bundle_summary", result.turn_result.metadata)
        self.assertIn("cart_summary", result.turn_result.metadata)

    def test_plan_meals_returns_clarification_when_all_requested_slots_have_no_candidates(self) -> None:
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService(
                {
                    "breakfast": [],
                    "dinner": [],
                }
            )
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Plan breakfast and dinner for me.",
                "type": "generate_day_plan",
                "slots": ["breakfast", "dinner"],
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
        )

        self.assertEqual("clarification_request", result.turn_result.turn_mode)
        self.assertEqual("missing_slot_candidates", result.turn_result.metadata["issue"])
        self.assertIsNone(service.planner_call)

    def test_plan_meals_continues_when_only_some_requested_slots_have_candidates(self) -> None:
        breakfast_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-breakfast-1",
                name="Egg Bowl",
                meal_type=MealType.BREAKFAST,
                protein=25,
                calories=420,
            ),
            semantic_score=0.91,
            why_it_matched=["High protein"],
            estimated_cost_amount=4.5,
        )
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService(
                {
                    "breakfast": [breakfast_item],
                    "dinner": [],
                }
            )
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Plan breakfast and dinner for me.",
                "type": "generate_day_plan",
                "slots": ["breakfast", "dinner"],
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
        )

        self.assertIsNotNone(service.planner_call)
        assert service.planner_call is not None
        self.assertEqual(["breakfast", "dinner"], service.planner_call["action_payload"]["requested_slots"])
        self.assertEqual(["dinner"], list(service.planner_call["action_payload"]["missing_slots"]))
        self.assertEqual("day_plan_generated", result.turn_result.turn_mode)
        self.assertEqual(1, len(result.turn_result.planned_meals))
        self.assertEqual("breakfast", result.turn_result.planned_meals[0]["slot"])

    def test_plan_meals_supports_generate_week_plan_with_effective_date(self) -> None:
        breakfast_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-breakfast-1",
                name="Egg Bowl",
                meal_type=MealType.BREAKFAST,
                protein=25,
                calories=420,
            ),
            semantic_score=0.91,
            why_it_matched=["High protein"],
            estimated_cost_amount=4.5,
        )
        dinner_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-dinner-1",
                name="Chicken Tray Bake",
                meal_type=MealType.DINNER,
                protein=40,
                calories=610,
            ),
            semantic_score=0.89,
            why_it_matched=["Good for batch cooking"],
            estimated_cost_amount=5.2,
        )
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService(
                {
                    "breakfast": [breakfast_item],
                    "dinner": [dinner_item],
                }
            )
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Build me a weekly meal plan.",
                "type": "generate_week_plan",
                "slots": ["breakfast", "dinner"],
                "effective_date": "2026-06-29",
            }
        )

        result = service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
        )

        self.assertIsNotNone(service.planner_call)
        assert service.planner_call is not None
        self.assertEqual("generate_week_plan", service.planner_call["request_type"])
        self.assertEqual("week_plan_request", service.planner_call["action_payload"]["request_kind"])
        self.assertEqual("2026-06-29", service.planner_call["action_payload"]["effective_date"])
        self.assertEqual(["2026-06-29"], service.planner_call["action_payload"]["selected_dates"])
        self.assertEqual(date(2026, 6, 29), payload.effective_date)
        self.assertEqual("day_plan_generated", result.turn_result.turn_mode)
        self.assertEqual(1, len(service.saved_repo.upsert_calls))
        self.assertEqual("draft", service.saved_repo.upsert_calls[0]["status"])
        self.assertEqual("draft", result.turn_result.ui_blocks[0]["payload"]["state"])

    def test_plan_meals_preserves_selected_dates_for_week_plan(self) -> None:
        breakfast_item = MealSemanticSearchItem(
            meal=build_meal(
                meal_id="meal-breakfast-2",
                name="Greek Yogurt Bowl",
                meal_type=MealType.BREAKFAST,
                protein=22,
                calories=390,
            ),
            semantic_score=0.9,
            why_it_matched=["High protein"],
            estimated_cost_amount=4.1,
        )
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService({"breakfast": [breakfast_item]})
        )
        payload = MealPlannerRequest.model_validate(
            {
                "message": "Build me a weekly meal plan.",
                "type": "generate_week_plan",
                "slots": ["breakfast"],
                "effective_date": "2026-07-01",
                "selected_dates": ["2026-07-03", "2026-07-01", "2026-07-04"],
            }
        )

        service.plan_meals(
            current_user=build_user(goal="Weight Gain"),
            payload=payload,
        )

        self.assertIsNotNone(service.planner_call)
        assert service.planner_call is not None
        self.assertEqual(
            ["2026-07-01", "2026-07-03", "2026-07-04"],
            service.planner_call["action_payload"]["selected_dates"],
        )

    def test_enrich_prepared_meal_planner_turn_aggregates_weekly_fresh_cooks_only(self) -> None:
        service = PlannerServiceUnderTest(
            search_service=FakeSemanticSearchService({}),
            grocery_products=[
                build_grocery_product(
                    product_id="prod-1",
                    name="Chicken Breast",
                    amount=4.0,
                    price_unit="500 g",
                )
            ],
            pantry_items=[
                build_pantry_item(
                    product_id="prod-1",
                    product_name="Chicken Breast",
                    quantity=100,
                    unit="g",
                )
            ],
        )
        turn_result = MealConversationTurnResult(
            assistant_text="Weekly plan ready.",
            turn_mode="day_plan_generated",
            agent_type="meal_planner_agent",
            target_domain="meal_planning",
            meal_type=MealType.LUNCH,
            country_code=CountryCode.UNITED_KINGDOM,
            planned_meals=[
                {
                    "slot": "lunch",
                    "meal_id": "meal-lunch-1",
                    "meal_name": "Chicken Rice Bowl",
                    "meal_source": "catalog",
                    "created_meal_draft": None,
                }
            ],
            requested_culture="british",
            ui_blocks=[
                {
                    "id": "week-1",
                    "block_type": "meal_plan_week",
                    "title": "Meal Plan",
                    "payload": {
                        "snapshot_id": "week-1",
                        "view_mode": "week",
                        "days": [
                            {
                                "date": "2026-06-29",
                                "sections": [
                                    {
                                        "slot": "lunch",
                                        "items": [
                                            {
                                                "meal_id": "meal-lunch-1",
                                                "name": "Chicken Rice Bowl",
                                                "source_type": "fresh",
                                                "yield_servings": 4.0,
                                                "consumed_servings": 2.0,
                                                "meal_detail": {
                                                    "servings": 2.0,
                                                    "ingredients": [
                                                        {
                                                            "id": "ingredient-1",
                                                            "name": "Chicken",
                                                            "quantity": 200.0,
                                                            "unit": "g",
                                                            "linked_product_ids": ["prod-1"],
                                                        }
                                                    ],
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "date": "2026-06-30",
                                "sections": [
                                    {
                                        "slot": "lunch",
                                        "items": [
                                            {
                                                "meal_id": "meal-lunch-1",
                                                "name": "Chicken Rice Bowl",
                                                "source_type": "leftover",
                                                "origin_batch_id": "batch-lunch-2026-06-29-1",
                                                "yield_servings": 4.0,
                                                "consumed_servings": 2.0,
                                                "meal_detail": {
                                                    "servings": 2.0,
                                                    "ingredients": [
                                                        {
                                                            "id": "ingredient-1",
                                                            "name": "Chicken",
                                                            "quantity": 200.0,
                                                            "unit": "g",
                                                            "linked_product_ids": ["prod-1"],
                                                        }
                                                    ],
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                }
            ],
            metadata={"issue": None},
        )

        result = service._enrich_prepared_meal_planner_turn(
            current_user=build_user(goal="Weight Gain", weekly_budget=20),
            action_payload={
                "user_context": {
                    "goal": "Weight Gain",
                    "weekly_budget": 20,
                    "household_size": 2,
                },
                "country_code": "GB",
            },
            turn_result=turn_result,
        )

        cart_summary = result.metadata["cart_summary"]
        bundle_summary = result.metadata["bundle_summary"]
        inventory_summary = result.metadata["inventory_summary"]

        self.assertEqual(1, cart_summary["items_to_buy_count"])
        self.assertEqual(4.0, cart_summary["estimated_total_cost"])
        self.assertEqual("within_budget", bundle_summary["budget_status"])
        self.assertEqual(2, bundle_summary["meal_count"])
        self.assertEqual(100.0, inventory_summary["used_items"][0]["used_quantity"])
        self.assertEqual(300.0, cart_summary["buy_items"][0]["required_quantity"])
        self.assertEqual(1, cart_summary["buy_items"][0]["estimated_units_to_buy"])
        self.assertEqual("https://example.com/product.jpg", cart_summary["buy_items"][0]["image_url"])
        self.assertEqual("https://example.com/product.jpg", inventory_summary["used_items"][0]["image_url"])


if __name__ == "__main__":
    unittest.main()
