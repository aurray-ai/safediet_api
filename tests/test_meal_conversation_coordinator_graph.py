from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.agents.meal_conversation.coordinator import CHEF_DOMAIN, MEAL_PLANNING_DOMAIN, ORDER_DOMAIN
from app.agents.meal_conversation.graph import MealConversationGraph
from app.agents.meal_conversation.state import MealConversationTurnResult
from app.models.user import User, UserType


def make_user(user_id: str) -> User:
    return User(
        id=user_id,
        name="Favour",
        email="favour@example.com",
        password_hash="hash",
        user_types=[UserType.CUSTOMER],
        user_configuration={"goal": "weight_gain"},
        created_at=datetime.now(timezone.utc),
    )


class StubSubagent:
    def __init__(self, result: MealConversationTurnResult) -> None:
        self.result = result

    def run_turn(self, **kwargs) -> MealConversationTurnResult:
        return self.result


class MealConversationCoordinatorGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = MealConversationGraph(runtime=SimpleNamespace())
        self.user = make_user("user-1")

    def test_order_requests_route_to_order_subagent_and_preserve_coordinator_identity(self) -> None:
        result = self.graph.run_turn(
            current_user=self.user,
            conversation_id="conv-1",
            conversation_history=[],
            user_text="Track my order please",
            quick_action_type=None,
            action_payload={},
            explicit_meal_type=None,
            explicit_country_code=None,
        )

        self.assertEqual(result.agent_type, "meal_coordinator")
        self.assertEqual(result.target_domain, ORDER_DOMAIN)
        self.assertEqual(result.metadata["selected_subagent"], "order_agent")
        self.assertEqual(result.metadata["selected_subagent_type"], "order_agent")

    def test_chef_requests_route_to_chef_subagent_and_preserve_coordinator_identity(self) -> None:
        result = self.graph.run_turn(
            current_user=self.user,
            conversation_id="conv-1",
            conversation_history=[],
            user_text="What can I use instead of eggs?",
            quick_action_type=None,
            action_payload={},
            explicit_meal_type=None,
            explicit_country_code=None,
        )

        self.assertEqual(result.agent_type, "meal_coordinator")
        self.assertEqual(result.target_domain, CHEF_DOMAIN)
        self.assertEqual(result.metadata["selected_subagent"], "chef_agent")
        self.assertEqual(result.metadata["selected_subagent_type"], "chef_agent")

    def test_meal_planning_subagent_result_is_wrapped_by_coordinator(self) -> None:
        self.graph._subagents[MEAL_PLANNING_DOMAIN] = StubSubagent(
            MealConversationTurnResult(
                assistant_text="Meal draft ready.",
                turn_mode="day_plan_generated",
                agent_type="meal_planner_agent",
                target_domain=MEAL_PLANNING_DOMAIN,
                meal_type=None,
                country_code=None,
                planned_meals=[{"slot": "dinner", "meal_name": "Chicken Rice", "meal_source": "catalog"}],
                metadata={"request_kind": "day_plan_request"},
            )
        )

        result = self.graph.run_turn(
            current_user=self.user,
            conversation_id="conv-1",
            conversation_history=[],
            user_text="Build me dinner",
            quick_action_type=None,
            action_payload={},
            explicit_meal_type=None,
            explicit_country_code=None,
        )

        self.assertEqual(result.agent_type, "meal_coordinator")
        self.assertEqual(result.target_domain, MEAL_PLANNING_DOMAIN)
        self.assertEqual(result.metadata["selected_subagent"], "meal_planner_agent")
        self.assertEqual(result.metadata["selected_subagent_type"], "meal_planner_agent")
        self.assertEqual(result.planned_meals[0]["meal_name"], "Chicken Rice")


if __name__ == "__main__":
    unittest.main()
