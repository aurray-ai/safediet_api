from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.agents.promotions.graph import PromotionAgentGraph
from app.agents.promotions.runtime import PromotionGenerationRuntime
from app.models.user import User, UserType


class PromotionAgentGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = PromotionGenerationRuntime(
            openai_api_key=None,
            model_name="gpt-5-mini-test",
            timeout_seconds=30,
        )
        self.graph = PromotionAgentGraph(runtime=self.runtime)
        self.user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hash",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=datetime.now(timezone.utc),
        )

    def test_routes_meal_and_order_supporting_subagents(self) -> None:
        result = self.graph.run_generation(
            campaign={
                "_id": "camp-1",
                "promotion_type": "meal_promotion",
                "delivery_type": "conversation",
                "target_location": "ios.conversations",
                "admin_instruction": "Generate a meal and grocery follow-up for tomorrow plan.",
                "constraints": {"budget": "low", "country_code": "GB"},
            },
            current_user=self.user,
            user_context={
                "conversation_summary": "You asked for a plan for tomorrow.",
                "latest_plan_summary": "British-style meals for Wednesday (breakfast, lunch, dinner).",
                "preference_snapshot": {"goal": "gain_weight"},
                "recent_messages_summary": [],
            },
        )

        self.assertIn("meal_planner_agent", result.selected_subagents)
        self.assertIn("order_agent", result.selected_subagents)
        self.assertEqual(result.payload.metadata["agent_type"], "promotion_agent")

    def test_fallback_does_not_expose_admin_instruction(self) -> None:
        admin_instruction = "Generate a milk-free breakfast promotion for users who want quick weekday meals."
        result = self.graph.run_generation(
            campaign={
                "_id": "camp-2",
                "promotion_type": "meal_promotion",
                "delivery_type": "conversation",
                "target_location": "ios.conversations",
                "admin_instruction": admin_instruction,
                "constraints": {},
            },
            current_user=self.user,
            user_context={
                "conversation_summary": "",
                "latest_plan_summary": "",
                "preference_snapshot": {"goal": "gain_weight", "culture_preferences": ["british"]},
                "recent_messages_summary": [],
            },
        )

        self.assertNotIn(admin_instruction, result.payload.full_message)
        self.assertEqual(result.payload.metadata["generation_source"], "fallback")


if __name__ == "__main__":
    unittest.main()
