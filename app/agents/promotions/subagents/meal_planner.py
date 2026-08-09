from __future__ import annotations

from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    END = None
    StateGraph = None

from app.agents.promotions.routing import MEAL_PLANNER_DOMAIN
from app.agents.promotions.types import PromotionSubagentEnrichment
from app.models.user import User

MEAL_PLANNER_PROMOTION_AGENT_TYPE = "meal_planner_agent"


class MealPlannerPromotionState(TypedDict, total=False):
    campaign: dict[str, Any]
    current_user: User
    user_context: dict[str, Any]
    final_enrichment: PromotionSubagentEnrichment


class MealPlannerPromotionSubagentGraph:
    def __init__(self) -> None:
        self._compiled_graph = self._compile_graph()

    def run_enrichment(
        self,
        *,
        campaign: dict[str, Any],
        current_user: User,
        user_context: dict[str, Any],
    ) -> PromotionSubagentEnrichment:
        initial_state: MealPlannerPromotionState = {
            "campaign": campaign,
            "current_user": current_user,
            "user_context": user_context,
        }
        if self._compiled_graph is None:
            state = dict(initial_state)
            state.update(self._finalize(state))
        else:
            state = self._compiled_graph.invoke(initial_state)
        return state["final_enrichment"]

    def _compile_graph(self):
        if StateGraph is None or END is None:
            return None
        workflow = StateGraph(MealPlannerPromotionState)
        workflow.add_node("finalize", self._finalize)
        workflow.set_entry_point("finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    @staticmethod
    def _finalize(state: MealPlannerPromotionState) -> dict[str, Any]:
        context = dict(state.get("user_context") or {})
        preferences = dict(context.get("preference_snapshot") or {})
        latest_plan_summary = str(context.get("latest_plan_summary") or "").strip()
        goal = str(preferences.get("goal") or "").replace("_", " ").strip()
        selected_plan_types = [
            str(item).replace("_", " ").strip()
            for item in list(preferences.get("selected_plan_types") or [])
            if str(item).strip()
        ]

        highlights: list[str] = []
        if latest_plan_summary:
            highlights.append(latest_plan_summary[:120])
        if goal:
            highlights.append(f"Supports your {goal} goal.")

        specs: list[dict[str, str]] = []
        if goal:
            specs.append({"label": "Goal", "value": goal[:60]})
        if selected_plan_types:
            specs.append({"label": "Plan focus", "value": ", ".join(selected_plan_types[:2])[:60]})

        guidance = [
            "Keep the message anchored to meal planning progress or next-plan momentum.",
            "Use a planning-forward CTA when the delivery target is the conversations surface.",
        ]

        return {
            "final_enrichment": PromotionSubagentEnrichment(
                domain=MEAL_PLANNER_DOMAIN,
                agent_type=MEAL_PLANNER_PROMOTION_AGENT_TYPE,
                highlights=highlights[:2],
                specs=specs[:2],
                message_guidance=guidance,
                meal_data={
                    "latest_plan_summary": latest_plan_summary or None,
                    "goal": goal or None,
                    "selected_plan_types": selected_plan_types[:3],
                },
                metadata={"source": "promotion_meal_planner"},
            )
        }
