from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.user import User, UserType
from app.services.meal_conversation_service import MealConversationService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeMealConversationRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, dict] = {}
        self.create_calls = 0

    def create_conversation(self, *, user_id: str, user_goal: str | None, agent_type: str, status: str, current_summary: dict):
        self.create_calls += 1
        now = utc_now()
        conversation_id = f"conv-{self.create_calls}"
        conversation = {
            "_id": conversation_id,
            "user_id": user_id,
            "user_goal": user_goal,
            "agent_type": agent_type,
            "status": status,
            "current_summary": current_summary,
            "created_at": now,
            "updated_at": now,
            "last_message_at": None,
            "message_count": 0,
        }
        self.conversations[conversation_id] = conversation
        return conversation

    def find_reusable_conversation(self, *, user_id: str, user_goal: str):
        matches = [
            conversation
            for conversation in self.conversations.values()
            if conversation["user_id"] == user_id and conversation.get("user_goal") == user_goal
        ]
        matches.sort(key=lambda item: (item["updated_at"], item["_id"]), reverse=True)
        return matches[0] if matches else None

    def update_conversation_summary(self, *, conversation_id: str, user_goal: str | None, agent_type: str, status: str, current_summary: dict):
        conversation = self.conversations[conversation_id]
        conversation["user_goal"] = user_goal
        conversation["agent_type"] = agent_type
        conversation["status"] = status
        conversation["current_summary"] = current_summary
        conversation["updated_at"] = utc_now()
        return conversation

    def get_conversation(self, conversation_id: str):
        return self.conversations.get(conversation_id)

    def get_current_conversation(self, *, user_id: str, user_goal: str | None = None):
        matches = [
            conversation
            for conversation in self.conversations.values()
            if conversation["user_id"] == user_id and conversation["status"] == "active"
        ]
        if user_goal is not None:
            matches = [conversation for conversation in matches if conversation.get("user_goal") == user_goal]
        matches.sort(key=lambda item: (item["updated_at"], item["_id"]), reverse=True)
        return matches[0] if matches else None

    def append_message(self, **kwargs):  # pragma: no cover - not used by these tests
        raise AssertionError("append_message should not be called in these tests")

    def store_turn_result(self, **kwargs):  # pragma: no cover - not used by these tests
        raise AssertionError("store_turn_result should not be called in these tests")


class MealConversationServiceGoalReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeMealConversationRepository()
        self.service = MealConversationService(
            settings=SimpleNamespace(
                openai_api_key=None,
                openai_meal_conversation_model="",
                openai_meal_conversation_timeout_seconds=0,
            ),
            user_repository=SimpleNamespace(),
            meal_conversation_repository=self.repository,
            meal_repository=SimpleNamespace(),
            grocery_repository=SimpleNamespace(),
            saved_meal_plan_repository=SimpleNamespace(),
            user_pantry_repository=SimpleNamespace(list_items=lambda user_id: []),
            user_meal_usage_service=SimpleNamespace(),
        )

    def test_start_conversation_reuses_existing_conversation_for_same_goal(self) -> None:
        user = make_user("user-1", goal="weight_loss")

        first = self.service.start_conversation(
            current_user=user,
            opening_message=None,
            meal_type=None,
            country_code=None,
        )
        second = self.service.start_conversation(
            current_user=user,
            opening_message=None,
            meal_type=None,
            country_code=None,
        )

        self.assertEqual(first.conversation.conversation_id, second.conversation.conversation_id)
        self.assertEqual(self.repository.create_calls, 1)
        self.assertEqual(len(self.repository.conversations), 1)
        stored = self.repository.get_conversation(first.conversation.conversation_id)
        self.assertEqual(stored["user_goal"], "weight_loss")
        self.assertEqual(stored["agent_type"], "meal_coordinator")

    def test_start_conversation_creates_new_conversation_after_goal_change(self) -> None:
        weight_loss_user = make_user("user-1", goal="weight_loss")
        weight_gain_user = make_user("user-1", goal="weight_gain")

        first = self.service.start_conversation(
            current_user=weight_loss_user,
            opening_message=None,
            meal_type=None,
            country_code=None,
        )
        second = self.service.start_conversation(
            current_user=weight_gain_user,
            opening_message=None,
            meal_type=None,
            country_code=None,
        )

        self.assertNotEqual(first.conversation.conversation_id, second.conversation.conversation_id)
        self.assertEqual(self.repository.create_calls, 2)
        self.assertEqual(len(self.repository.conversations), 2)

    def test_get_current_conversation_is_scoped_to_user_goal(self) -> None:
        weight_loss_user = make_user("user-1", goal="weight_loss")
        weight_gain_user = make_user("user-1", goal="weight_gain")

        loss = self.service.start_conversation(
            current_user=weight_loss_user,
            opening_message=None,
            meal_type=None,
            country_code=None,
        )
        gain = self.service.start_conversation(
            current_user=weight_gain_user,
            opening_message=None,
            meal_type=None,
            country_code=None,
        )

        current_for_loss = self.service.get_current_conversation(current_user=weight_loss_user)

        self.assertIsNotNone(current_for_loss.conversation)
        self.assertEqual(current_for_loss.conversation.conversation_id, loss.conversation.conversation_id)
        self.assertNotEqual(current_for_loss.conversation.conversation_id, gain.conversation.conversation_id)

    def test_should_surface_turn_as_error_for_generation_failure(self) -> None:
        turn_result = SimpleNamespace(
            turn_mode="conversation_reply",
            planned_meals=[],
            ui_blocks=[],
            metadata={"issue": "graph_execution_failed"},
        )

        self.assertTrue(self.service._should_surface_turn_as_error(turn_result))

    def test_should_not_surface_turn_as_error_for_normal_reply(self) -> None:
        turn_result = SimpleNamespace(
            turn_mode="conversation_reply",
            planned_meals=[],
            ui_blocks=[],
            metadata={},
        )

        self.assertFalse(self.service._should_surface_turn_as_error(turn_result))


def make_user(user_id: str, *, goal: str) -> User:
    return User(
        id=user_id,
        name="Favour",
        email=f"{user_id}@example.com",
        password_hash="hashed",
        user_types=[UserType.CUSTOMER],
        user_configuration={"goal": goal},
        created_at=utc_now(),
    )
