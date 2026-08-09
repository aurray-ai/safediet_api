from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import BackgroundTasks, HTTPException, Request, Response, status

from app.api.v1.endpoints.meal_planner import run_meal_planner, save_meal_planner_draft
from app.api.v1.endpoints.saved_meal_plans import mutate_saved_meal_plan_slot
from app.models.meal import MealType
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.schemas.meal_conversation import (
    MealPlannerDraftSaveRequest,
    MealPlannerDraftUIBlockRequest,
    MealPlannerRequest,
    MealPlannerRunAcceptedResponse,
    MealPlannerRunResponse,
)
from app.schemas.saved_meal_plan import HomeMealPlanResponse, SavedMealPlanSlotMutationRequest
from app.services.saved_meal_plan_service import SavedMealPlanMutationError, SavedMealPlanNotFoundError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_user() -> User:
    return User(
        id="user-1",
        name="Test User",
        email="test@example.com",
        password_hash="x",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_saved_plan(*, plan_id: str, view_mode: str, effective_date: date) -> SavedMealPlan:
    now = utc_now()
    return SavedMealPlan(
        id=plan_id,
        user_id="user-1",
        title="Meal Plan",
        status="saved",
        view_mode=view_mode,
        plan_scope="standalone_day" if view_mode == "day" else "weekly_parent",
        effective_date=effective_date,
        week_start=None,
        week_end=None,
        day_index=None,
        parent_saved_plan_id=None,
        source_saved_plan_id=None,
        linked_day_plan_ids=[],
        meal_type=None,
        country_code=None,
        planned_meals=[],
        plan_payload={"snapshot_id": f"snapshot-{plan_id}", "sections": []},
        requested_culture=None,
        user_goal=None,
        source_snapshot_id=f"snapshot-{plan_id}",
        source_conversation_id="conversation-1",
        agent_type="meal_planner_agent",
        created_at=now,
        updated_at=now,
    )


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    scope = {"type": "http", "method": "POST", "headers": raw_headers, "query_string": b""}
    return Request(scope=scope)


class StubMealConversationService:
    def __init__(self, *, generation_error: HTTPException | None = None) -> None:
        self._generation_error = generation_error
        self.plan_meals_calls: list[dict[str, object]] = []

    def assert_plan_generation_allowed(self, **kwargs: object) -> None:
        if self._generation_error is not None:
            raise self._generation_error

    def plan_meals(self, *, current_user: User, payload: MealPlannerRequest, trace_id: str | None):
        self.plan_meals_calls.append({"current_user": current_user, "payload": payload, "trace_id": trace_id})
        turn_result = SimpleNamespace(
            assistant_text="Here is your plan.",
            turn_mode="day_plan_generated",
            planned_meals=[{"meal_id": "meal-a"}],
            requested_culture=None,
            metadata={"bundle_summary": {"meal_count": 1}},
            ui_blocks=[],
            quick_actions=[],
        )
        return SimpleNamespace(turn_result=turn_result, prepared_action_payload={}, semantic_queries=[])


class StubDraftSaveService:
    def __init__(self, *, saved_plan: SavedMealPlan, notification_event: dict[str, object] | None) -> None:
        self._saved_plan = saved_plan
        self._notification_event = notification_event

    def save_meal_planner_draft_result(self, *, current_user: User, payload: MealPlannerDraftSaveRequest):
        return SimpleNamespace(
            saved_plan=self._saved_plan,
            notification_event=self._notification_event,
            already_saved=False,
        )


class StubNotificationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create_and_deliver_meal_plan_approved_notification(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class StubSavedMealPlanServiceForMutation:
    def __init__(self, *, response: HomeMealPlanResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[SavedMealPlanSlotMutationRequest] = []

    def mutate_slot(self, *, current_user: User, payload: SavedMealPlanSlotMutationRequest) -> HomeMealPlanResponse:
        self.calls.append(payload)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class MealPlannerEndpointTests(unittest.TestCase):
    def test_run_meal_planner_day_plan_returns_200_sync_response(self) -> None:
        payload = MealPlannerRequest(
            message="Plan my lunch",
            request_type="generate_day_plan",
            slots=["lunch"],
        )
        background_tasks = BackgroundTasks()
        response = Response()
        service = StubMealConversationService()

        result = run_meal_planner(
            background_tasks=background_tasks,
            request=make_request({"x-meal-trace-id": "trace-1"}),
            response=response,
            payload=payload,
            current_user=make_user(),
            meal_conversation_service=service,
        )

        self.assertIsInstance(result, MealPlannerRunResponse)
        self.assertEqual("day_plan_generated", result.turn_mode)
        self.assertEqual(1, len(service.plan_meals_calls))
        self.assertEqual(0, len(background_tasks.tasks))

    def test_run_meal_planner_week_plan_schedules_background_task_and_returns_202(self) -> None:
        payload = MealPlannerRequest(
            message="Plan my week",
            request_type="generate_week_plan",
            slots=["breakfast", "lunch", "dinner"],
        )
        background_tasks = BackgroundTasks()
        response = Response()
        service = StubMealConversationService()

        result = run_meal_planner(
            background_tasks=background_tasks,
            request=make_request({"x-meal-trace-id": "trace-2"}),
            response=response,
            payload=payload,
            current_user=make_user(),
            meal_conversation_service=service,
        )

        self.assertIsInstance(result, MealPlannerRunAcceptedResponse)
        self.assertEqual(status.HTTP_202_ACCEPTED, response.status_code)
        self.assertEqual(1, len(background_tasks.tasks))
        self.assertEqual("trace-2", result.trace_id)
        self.assertEqual("week", result.view_mode)
        self.assertEqual(0, len(service.plan_meals_calls))

    def test_run_meal_planner_propagates_conflict_from_generation_guard(self) -> None:
        payload = MealPlannerRequest(
            message="Plan my lunch",
            request_type="generate_day_plan",
            slots=["lunch"],
            effective_date=date(2026, 6, 24),
        )
        service = StubMealConversationService(
            generation_error=HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan already exists.")
        )

        with self.assertRaises(HTTPException) as context:
            run_meal_planner(
                background_tasks=BackgroundTasks(),
                request=make_request(),
                response=Response(),
                payload=payload,
                current_user=make_user(),
                meal_conversation_service=service,
            )

        self.assertEqual(409, context.exception.status_code)

    def test_save_meal_planner_draft_returns_saved_plan_and_sends_notification_when_approved(self) -> None:
        saved_plan = make_saved_plan(plan_id="saved-1", view_mode="day", effective_date=date(2026, 6, 24))
        notification_event = {
            "type": "meal_plan_approved",
            "conversation_id": "conv-1",
            "saved_plan_id": "saved-1",
            "snapshot_id": "snapshot-1",
            "view_mode": "day",
            "period_label": None,
            "ui_block_id": "block-1",
        }
        service = StubDraftSaveService(saved_plan=saved_plan, notification_event=notification_event)
        notification_service = StubNotificationService()
        payload = MealPlannerDraftSaveRequest(
            ui_block=MealPlannerDraftUIBlockRequest(id="block-1", block_type="meal_plan_draft", title="Plan", payload={}),
        )

        result = asyncio.run(
            save_meal_planner_draft(
                payload=payload,
                current_user=make_user(),
                meal_conversation_service=service,
                notification_service=notification_service,
            )
        )

        self.assertEqual("saved-1", result.id)
        self.assertEqual(1, len(notification_service.calls))
        self.assertEqual("saved-1", notification_service.calls[0]["saved_plan_id"])

    def test_save_meal_planner_draft_skips_notification_when_no_approval_event(self) -> None:
        saved_plan = make_saved_plan(plan_id="saved-2", view_mode="day", effective_date=date(2026, 6, 24))
        service = StubDraftSaveService(saved_plan=saved_plan, notification_event=None)
        notification_service = StubNotificationService()
        payload = MealPlannerDraftSaveRequest(
            ui_block=MealPlannerDraftUIBlockRequest(id="block-2", block_type="meal_plan_draft", title="Plan", payload={}),
        )

        result = asyncio.run(
            save_meal_planner_draft(
                payload=payload,
                current_user=make_user(),
                meal_conversation_service=service,
                notification_service=notification_service,
            )
        )

        self.assertEqual("saved-2", result.id)
        self.assertEqual(0, len(notification_service.calls))


class SavedMealPlanSlotMutationEndpointTests(unittest.TestCase):
    def test_mutate_saved_meal_plan_slot_passes_payload_through_for_each_operation(self) -> None:
        cases = [
            ("add", {"meal_id": "meal-a"}),
            ("swap", {"meal_id": "meal-a", "replacing_meal_id": "meal-old"}),
            ("remove", {"meal_id": "meal-old"}),
        ]
        for operation, extra_fields in cases:
            with self.subTest(operation=operation):
                canned_response = HomeMealPlanResponse(
                    selected_date=date(2026, 6, 24),
                    view_mode="day",
                    resolution_mode="draft_day_plan",
                    ui_block=None,
                )
                service = StubSavedMealPlanServiceForMutation(response=canned_response)
                payload = SavedMealPlanSlotMutationRequest(
                    operation=operation,
                    slot=MealType.LUNCH,
                    effective_date=date(2026, 6, 24),
                    **extra_fields,
                )

                result = mutate_saved_meal_plan_slot(
                    payload=payload,
                    current_user=make_user(),
                    saved_meal_plan_service=service,
                )

                self.assertIs(canned_response, result)
                self.assertEqual(1, len(service.calls))
                self.assertEqual(operation, service.calls[0].operation)

    def test_mutate_saved_meal_plan_slot_maps_not_found_to_404(self) -> None:
        service = StubSavedMealPlanServiceForMutation(error=SavedMealPlanNotFoundError())
        payload = SavedMealPlanSlotMutationRequest(
            operation="add",
            slot=MealType.LUNCH,
            meal_id="meal-a",
            effective_date=date(2026, 6, 24),
        )

        with self.assertRaises(HTTPException) as context:
            mutate_saved_meal_plan_slot(payload=payload, current_user=make_user(), saved_meal_plan_service=service)

        self.assertEqual(404, context.exception.status_code)

    def test_mutate_saved_meal_plan_slot_maps_mutation_error_to_422(self) -> None:
        service = StubSavedMealPlanServiceForMutation(error=SavedMealPlanMutationError("The selected meal could not be found."))
        payload = SavedMealPlanSlotMutationRequest(
            operation="remove",
            slot=MealType.LUNCH,
            meal_id="meal-a",
            effective_date=date(2026, 6, 24),
        )

        with self.assertRaises(HTTPException) as context:
            mutate_saved_meal_plan_slot(payload=payload, current_user=make_user(), saved_meal_plan_service=service)

        self.assertEqual(422, context.exception.status_code)
        self.assertEqual("The selected meal could not be found.", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
