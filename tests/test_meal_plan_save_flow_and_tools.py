from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.api.v1.endpoints.meal_planner import save_meal_planner_draft as save_meal_planner_draft_endpoint
from app.agents.meal_conversation.tools.get_user_saved_meal_plans import (
    GetUserSavedMealPlansTool,
)
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.schemas.meal_conversation import MealPlannerDraftSaveRequest, SendConversationMessageRequest
from app.services.meal_conversation_service import MealConversationService, MealPlannerDraftSaveResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_saved_plan(
    *,
    saved_plan_id: str,
    snapshot_id: str,
    title: str = "Meal Plan",
    meal_name: str = "Chicken Curry",
    status: str = "saved",
    updated_at: datetime | None = None,
) -> SavedMealPlan:
    resolved_updated_at = updated_at or utc_now()
    return SavedMealPlan(
        id=saved_plan_id,
        user_id="user-1",
        title=title,
        status=status,
        view_mode="day",
        plan_scope="standalone_day",
        effective_date=date(2026, 6, 20),
        week_start=None,
        week_end=None,
        day_index=None,
        parent_saved_plan_id=None,
        source_saved_plan_id=None,
        linked_day_plan_ids=[],
        meal_type=MealType.DINNER,
        country_code=CountryCode.UNITED_KINGDOM,
        planned_meals=[
            {
                "slot": "dinner",
                "meal_id": "meal-1",
                "meal_name": meal_name,
                "meal_source": "catalog",
            }
        ],
        plan_payload={
            "snapshot_id": snapshot_id,
            "view_mode": "day",
            "state": "saved",
            "tracked_text": "Tracked 0/1 meals",
            "totals": {"calories": 640},
            "sections": [
                {
                    "slot": "dinner",
                    "title": "Dinner",
                    "items": [
                        {
                            "meal_id": "meal-1",
                            "name": meal_name,
                            "meal_source": "catalog",
                        }
                    ],
                }
            ],
        },
        requested_culture="british",
        user_goal="gain_weight",
        source_snapshot_id=snapshot_id,
        source_conversation_id="conv-1",
        agent_type="meal_coordinator",
        created_at=resolved_updated_at,
        updated_at=resolved_updated_at,
    )


class FakeSavedMealPlanRepository:
    def __init__(self, *, existing_plan: SavedMealPlan | None = None) -> None:
        self.existing_by_snapshot: dict[str, SavedMealPlan] = {}
        self.upsert_calls: list[dict] = []
        if existing_plan is not None:
            self.existing_by_snapshot[existing_plan.source_snapshot_id] = existing_plan

    def get_by_user_snapshot(self, *, user_id: str, source_snapshot_id: str) -> SavedMealPlan | None:
        return self.existing_by_snapshot.get(source_snapshot_id)

    def upsert_saved_plan(self, **kwargs) -> SavedMealPlan:
        self.upsert_calls.append(kwargs)
        saved_plan = make_saved_plan(
            saved_plan_id=f"saved-{len(self.upsert_calls)}",
            snapshot_id=str(kwargs["source_snapshot_id"]),
            title=str(kwargs["title"]),
            meal_name=str((kwargs.get("planned_meals") or [{}])[0].get("meal_name") or "Planned Meal"),
            status=str(kwargs.get("status") or "saved"),
            updated_at=utc_now(),
        )
        self.existing_by_snapshot[saved_plan.source_snapshot_id] = saved_plan
        return saved_plan

    def list_saved_plans(
        self,
        *,
        user_id: str | None = None,
        view_mode: str | None = None,
        effective_date=None,
        status: str | None = None,
        updated_before=None,
        limit: int = 20,
    ):
        items = list(self.existing_by_snapshot.values())
        if view_mode:
            items = [item for item in items if item.view_mode == view_mode]
        if status:
            items = [item for item in items if item.status == status]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[:limit], len(items)


class FakeConversationRepository:
    def __init__(self, conversation: dict) -> None:
        self.conversation = conversation
        self.messages: list[dict] = []

    def append_message(self, **kwargs) -> dict:
        message = {
            "_id": f"msg-{len(self.messages) + 1}",
            "conversation_id": kwargs["conversation_id"],
            "role": kwargs["role"],
            "text": kwargs.get("text", ""),
            "ui_blocks": list(kwargs.get("ui_blocks", [])),
            "quick_actions": list(kwargs.get("quick_actions", [])),
            "metadata": dict(kwargs.get("metadata", {})),
            "created_at": utc_now(),
        }
        self.messages.append(message)
        return message

    def get_conversation(self, conversation_id: str):
        return self.conversation if self.conversation["_id"] == conversation_id else None

    def store_turn_result(self, *, conversation_id: str, user_goal: str | None, agent_type: str, status: str, current_summary: dict):
        self.conversation["user_goal"] = user_goal
        self.conversation["agent_type"] = agent_type
        self.conversation["status"] = status
        self.conversation["current_summary"] = current_summary
        self.conversation["updated_at"] = utc_now()
        return self.conversation


class FakeUserMealUsageService:
    def __init__(self) -> None:
        self.sync_calls: list[str] = []

    def sync_saved_day_plan(self, *, saved_plan: SavedMealPlan):
        self.sync_calls.append(saved_plan.id)
        return []


class FakeNotificationService:
    def __init__(self) -> None:
        self.approved_calls: list[dict] = []

    async def create_and_deliver_meal_plan_approved_notification(self, **kwargs) -> None:
        self.approved_calls.append(kwargs)


class MealPlanSaveFlowTests(unittest.TestCase):
    def _make_service(self, saved_repo: FakeSavedMealPlanRepository, conversation_repo: FakeConversationRepository, usage_service: FakeUserMealUsageService) -> MealConversationService:
        return MealConversationService(
            settings=SimpleNamespace(
                openai_api_key=None,
                openai_meal_conversation_model="",
                openai_meal_conversation_timeout_seconds=0,
            ),
            user_repository=SimpleNamespace(),
            meal_conversation_repository=conversation_repo,
            meal_repository=SimpleNamespace(),
            grocery_repository=SimpleNamespace(),
            saved_meal_plan_repository=saved_repo,
            user_pantry_repository=SimpleNamespace(list_items=lambda user_id: []),
            kitchen_service=SimpleNamespace(
                list_planning_items=lambda user_id, include_saved_plan_id=None: [],
                release_saved_plan_allocations=lambda **kwargs: None,
                sync_saved_plan_allocations=lambda **kwargs: None,
            ),
            user_meal_usage_service=usage_service,
        )

    def _make_conversation(self) -> dict:
        now = utc_now()
        return {
            "_id": "conv-1",
            "user_id": "user-1",
            "user_goal": "gain_weight",
            "agent_type": "meal_coordinator",
            "status": "active",
            "message_count": 2,
            "last_message_at": now,
            "created_at": now,
            "updated_at": now,
            "current_summary": {
                "meal_type": "dinner",
                "country_code": "GB",
                "requested_culture": "british",
                "planned_meals": [
                    {
                        "slot": "dinner",
                        "meal_id": "meal-1",
                        "meal_name": "Chicken Curry",
                        "meal_source": "catalog",
                    }
                ],
                "latest_ui_blocks": [
                    {
                        "id": "block-1",
                        "block_type": "meal_plan_draft",
                        "title": "Meal Plan",
                        "payload": {
                            "snapshot_id": "snap-1",
                            "title": "Meal Plan",
                            "view_mode": "day",
                            "state": "draft",
                            "effective_date": "2026-06-20",
                            "period_label": "Saturday",
                            "primary_action": {"label": "Save meal"},
                        },
                    }
                ],
            },
        }

    def test_first_save_creates_saved_plan_and_notification_event(self) -> None:
        conversation = self._make_conversation()
        saved_repo = FakeSavedMealPlanRepository()
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(conversation)
        service = self._make_service(saved_repo, conversation_repo, usage_service)

        assistant_message, _ = service._save_meal_plan_snapshot(
            conversation=conversation,
            payload=SendConversationMessageRequest(
                quick_action_type="save_meal_plan",
                action_payload={"snapshot_id": "snap-1"},
            ),
            trace_id="trace-1",
        )

        self.assertEqual(assistant_message["text"], "Meal saved.")
        self.assertEqual(len(saved_repo.upsert_calls), 1)
        self.assertEqual(len(usage_service.sync_calls), 1)
        self.assertEqual(
            assistant_message["metadata"]["notification_event"]["type"],
            "meal_plan_approved",
        )
        self.assertEqual(
            assistant_message["metadata"]["notification_event"]["snapshot_id"],
            "snap-1",
        )

    def test_duplicate_save_does_not_upsert_again(self) -> None:
        conversation = self._make_conversation()
        existing_plan = make_saved_plan(saved_plan_id="saved-existing", snapshot_id="snap-1")
        saved_repo = FakeSavedMealPlanRepository(existing_plan=existing_plan)
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(conversation)
        service = self._make_service(saved_repo, conversation_repo, usage_service)

        assistant_message, _ = service._save_meal_plan_snapshot(
            conversation=conversation,
            payload=SendConversationMessageRequest(
                quick_action_type="save_meal_plan",
                action_payload={"snapshot_id": "snap-1"},
            ),
            trace_id="trace-2",
        )

        self.assertEqual(assistant_message["text"], "This meal is already saved.")
        self.assertEqual(len(saved_repo.upsert_calls), 0)
        self.assertEqual(len(usage_service.sync_calls), 0)
        self.assertIsNone(assistant_message["metadata"]["notification_event"])
        updated_payload = assistant_message["ui_blocks"][0]["payload"]
        self.assertEqual(updated_payload["saved_plan_id"], "saved-existing")

    def test_draft_save_promotes_existing_draft_to_saved(self) -> None:
        conversation = self._make_conversation()
        existing_plan = make_saved_plan(saved_plan_id="draft-existing", snapshot_id="snap-1", status="draft")
        saved_repo = FakeSavedMealPlanRepository(existing_plan=existing_plan)
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(conversation)
        service = self._make_service(saved_repo, conversation_repo, usage_service)

        result = service.save_meal_planner_draft_result(
            current_user=User(
                id="user-1",
                name="Favour",
                email="favour@example.com",
                password_hash="hashed",
                user_types=[UserType.CUSTOMER],
                user_configuration={"goal": "gain_weight"},
                created_at=utc_now(),
            ),
            payload=MealPlannerDraftSaveRequest.model_validate(
                {
                    "ui_block": {
                        "id": "block-1",
                        "block_type": "meal_plan_draft",
                        "title": "Meal Plan",
                        "payload": {
                            "snapshot_id": "snap-1",
                            "title": "Meal Plan",
                            "view_mode": "day",
                            "state": "draft",
                            "effective_date": "2026-06-20",
                            "period_label": "Saturday",
                        },
                    },
                    "planned_meals": [
                        {
                            "slot": "dinner",
                            "meal_id": "meal-1",
                            "meal_name": "Chicken Curry",
                            "meal_source": "catalog",
                        }
                    ],
                    "country_code": "GB",
                }
            ),
        )

        self.assertFalse(result.already_saved)
        self.assertEqual(1, len(saved_repo.upsert_calls))
        self.assertEqual("saved", result.saved_plan.status)
        self.assertEqual("saved", result.saved_plan.plan_payload["state"])
        self.assertIsNotNone(result.notification_event)

    def test_direct_planner_draft_save_persists_without_conversation(self) -> None:
        saved_repo = FakeSavedMealPlanRepository()
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(self._make_conversation())
        service = self._make_service(saved_repo, conversation_repo, usage_service)
        current_user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hashed",
            user_types=[UserType.CUSTOMER],
            user_configuration={"goal": "gain_weight"},
            created_at=utc_now(),
        )

        saved_plan = service.save_meal_planner_draft(
            current_user=current_user,
            payload=MealPlannerDraftSaveRequest.model_validate(
                {
                    "ui_block": {
                        "id": "block-1",
                        "block_type": "meal_plan_draft",
                        "title": "Meal Plan",
                        "payload": {
                            "snapshot_id": "snap-direct-1",
                            "title": "Meal Plan",
                            "view_mode": "day",
                            "state": "draft",
                            "effective_date": "2026-06-20",
                            "period_label": "Saturday",
                            "primary_action": {"label": "Save meal"},
                        },
                    },
                    "planned_meals": [
                        {
                            "slot": "dinner",
                            "meal_id": "meal-1",
                            "meal_name": "Chicken Curry",
                            "meal_source": "catalog",
                        }
                    ],
                    "country_code": "GB",
                    "requested_culture": "british",
                }
            ),
        )

        self.assertEqual(saved_plan.source_snapshot_id, "snap-direct-1")
        self.assertEqual(saved_plan.plan_payload["state"], "saved")
        self.assertIsNone(saved_plan.plan_payload["primary_action"])
        self.assertEqual(len(saved_repo.upsert_calls), 1)
        self.assertEqual(len(usage_service.sync_calls), 1)

    def test_direct_planner_draft_save_result_exposes_notification_event_for_new_save(self) -> None:
        saved_repo = FakeSavedMealPlanRepository()
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(self._make_conversation())
        service = self._make_service(saved_repo, conversation_repo, usage_service)
        current_user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hashed",
            user_types=[UserType.CUSTOMER],
            user_configuration={"goal": "gain_weight"},
            created_at=utc_now(),
        )

        result = service.save_meal_planner_draft_result(
            current_user=current_user,
            payload=MealPlannerDraftSaveRequest.model_validate(
                {
                    "ui_block": {
                        "id": "block-week-1",
                        "block_type": "meal_plan_week",
                        "title": "Meal Plan",
                        "payload": {
                            "snapshot_id": "snap-week-1",
                            "title": "Meal Plan",
                            "view_mode": "week",
                            "state": "draft",
                            "effective_date": "2026-06-20",
                            "period_label": "This Week, Jun 20 - 26",
                            "primary_action": {"label": "Save week"},
                        },
                    },
                    "planned_meals": [
                        {
                            "slot": "dinner",
                            "meal_id": "meal-1",
                            "meal_name": "Chicken Curry",
                            "meal_source": "catalog",
                        }
                    ],
                    "country_code": "GB",
                    "requested_culture": "british",
                }
            ),
        )

        self.assertFalse(result.already_saved)
        self.assertEqual("meal_plan_approved", result.notification_event["type"])
        self.assertEqual("week", result.notification_event["view_mode"])
        self.assertEqual("This Week, Jun 20 - 26", result.notification_event["period_label"])

    def test_direct_planner_missing_groceries_save_result_has_no_primary_action(self) -> None:
        saved_repo = FakeSavedMealPlanRepository()
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(self._make_conversation())
        service = self._make_service(saved_repo, conversation_repo, usage_service)
        current_user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hashed",
            user_types=[UserType.CUSTOMER],
            user_configuration={"goal": "gain_weight"},
            created_at=utc_now(),
        )

        service._refresh_plan_grocery_summaries = lambda **kwargs: (dict(kwargs["payload_data"]), True)

        result = service.save_meal_planner_draft_result(
            current_user=current_user,
            payload=MealPlannerDraftSaveRequest.model_validate(
                {
                    "ui_block": {
                        "id": "block-week-1",
                        "block_type": "meal_plan_week",
                        "title": "Meal Plan",
                        "payload": {
                            "snapshot_id": "snap-week-1",
                            "title": "Meal Plan",
                            "view_mode": "week",
                            "state": "draft",
                            "effective_date": "2026-06-20",
                            "period_label": "This Week, Jun 20 - 26",
                            "primary_action": {"label": "Start Plan"},
                        },
                    },
                    "planned_meals": [
                        {
                            "slot": "dinner",
                            "meal_id": "meal-1",
                            "meal_name": "Chicken Curry",
                            "meal_source": "catalog",
                        }
                    ],
                    "country_code": "GB",
                    "requested_culture": "british",
                }
            ),
        )

        self.assertFalse(result.already_saved)
        self.assertEqual("missing_groceries", result.saved_plan.status)
        self.assertIsNone(saved_repo.upsert_calls[0]["plan_payload"]["primary_action"])
        self.assertIsNone(result.notification_event)

    def test_direct_planner_draft_save_result_skips_notification_for_duplicate_save(self) -> None:
        existing_plan = make_saved_plan(saved_plan_id="saved-existing", snapshot_id="snap-direct-1")
        saved_repo = FakeSavedMealPlanRepository(existing_plan=existing_plan)
        usage_service = FakeUserMealUsageService()
        conversation_repo = FakeConversationRepository(self._make_conversation())
        service = self._make_service(saved_repo, conversation_repo, usage_service)
        current_user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hashed",
            user_types=[UserType.CUSTOMER],
            user_configuration={"goal": "gain_weight"},
            created_at=utc_now(),
        )

        result = service.save_meal_planner_draft_result(
            current_user=current_user,
            payload=MealPlannerDraftSaveRequest.model_validate(
                {
                    "ui_block": {
                        "id": "block-1",
                        "block_type": "meal_plan_draft",
                        "title": "Meal Plan",
                        "payload": {
                            "snapshot_id": "snap-direct-1",
                            "title": "Meal Plan",
                            "view_mode": "day",
                            "state": "draft",
                            "effective_date": "2026-06-20",
                            "period_label": "Saturday",
                        },
                    },
                    "planned_meals": [
                        {
                            "slot": "dinner",
                            "meal_id": "meal-1",
                            "meal_name": "Chicken Curry",
                            "meal_source": "catalog",
                        }
                    ],
                    "country_code": "GB",
                }
            ),
        )

        self.assertTrue(result.already_saved)
        self.assertIsNone(result.notification_event)


class GetUserSavedMealPlansToolTests(unittest.TestCase):
    def test_tool_returns_recent_saved_plans_for_current_user_context(self) -> None:
        repo = FakeSavedMealPlanRepository(
            existing_plan=make_saved_plan(
                saved_plan_id="saved-1",
                snapshot_id="snap-1",
                title="Saturday Dinner",
                meal_name="Chicken Curry",
            )
        )
        tool = GetUserSavedMealPlansTool(
            repo,
            current_user_id_provider=lambda: "user-1",
        )

        result = tool.execute(limit=5, query="curry")

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["saved_plan_id"], "saved-1")
        self.assertIn("Chicken Curry", result["items"][0]["meal_names"])


class MealPlannerDraftSaveEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_dispatches_approved_notification_for_weekly_home_save(self) -> None:
        current_user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hashed",
            user_types=[UserType.CUSTOMER],
            user_configuration={"goal": "gain_weight"},
            created_at=utc_now(),
        )
        saved_plan = make_saved_plan(saved_plan_id="saved-week-1", snapshot_id="snap-week-1")
        meal_service = SimpleNamespace(
            save_meal_planner_draft_result=lambda **_: MealPlannerDraftSaveResult(
                saved_plan=saved_plan,
                notification_event={
                    "type": "meal_plan_approved",
                    "saved_plan_id": "saved-week-1",
                    "snapshot_id": "snap-week-1",
                    "view_mode": "week",
                    "period_label": "This Week, Jun 20 - 26",
                    "conversation_id": "direct-planner",
                    "ui_block_id": "block-week-1",
                },
                already_saved=False,
            )
        )
        notification_service = FakeNotificationService()
        payload = MealPlannerDraftSaveRequest.model_validate(
            {
                "ui_block": {
                    "id": "block-week-1",
                    "block_type": "meal_plan_week",
                    "title": "Meal Plan",
                    "payload": {
                        "snapshot_id": "snap-week-1",
                        "title": "Meal Plan",
                        "view_mode": "week",
                        "state": "draft",
                        "effective_date": "2026-06-20",
                        "period_label": "This Week, Jun 20 - 26",
                    },
                },
                "planned_meals": [
                    {
                        "slot": "dinner",
                        "meal_id": "meal-1",
                        "meal_name": "Chicken Curry",
                        "meal_source": "catalog",
                    }
                ],
                "country_code": "GB",
            }
        )

        response = await save_meal_planner_draft_endpoint(
            payload=payload,
            current_user=current_user,
            meal_conversation_service=meal_service,
            notification_service=notification_service,
        )

        self.assertEqual(response.id, "saved-week-1")
        self.assertEqual(len(notification_service.approved_calls), 1)
        self.assertEqual(notification_service.approved_calls[0]["view_mode"], "week")
        self.assertEqual(notification_service.approved_calls[0]["period_label"], "This Week, Jun 20 - 26")
        self.assertEqual(notification_service.approved_calls[0]["conversation_id"], "direct-planner")

    async def test_endpoint_skips_approved_notification_for_duplicate_home_save(self) -> None:
        current_user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hashed",
            user_types=[UserType.CUSTOMER],
            user_configuration={"goal": "gain_weight"},
            created_at=utc_now(),
        )
        saved_plan = make_saved_plan(saved_plan_id="saved-day-1", snapshot_id="snap-day-1")
        meal_service = SimpleNamespace(
            save_meal_planner_draft_result=lambda **_: MealPlannerDraftSaveResult(
                saved_plan=saved_plan,
                notification_event=None,
                already_saved=True,
            )
        )
        notification_service = FakeNotificationService()
        payload = MealPlannerDraftSaveRequest.model_validate(
            {
                "ui_block": {
                    "id": "block-day-1",
                    "block_type": "meal_plan_draft",
                    "title": "Meal Plan",
                    "payload": {
                        "snapshot_id": "snap-day-1",
                        "title": "Meal Plan",
                        "view_mode": "day",
                        "state": "draft",
                        "effective_date": "2026-06-20",
                        "period_label": "Saturday",
                    },
                },
                "planned_meals": [
                    {
                        "slot": "dinner",
                        "meal_id": "meal-1",
                        "meal_name": "Chicken Curry",
                        "meal_source": "catalog",
                    }
                ],
                "country_code": "GB",
            }
        )

        response = await save_meal_planner_draft_endpoint(
            payload=payload,
            current_user=current_user,
            meal_conversation_service=meal_service,
            notification_service=notification_service,
        )

        self.assertEqual(response.id, "saved-day-1")
        self.assertEqual(notification_service.approved_calls, [])
