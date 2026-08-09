from __future__ import annotations

from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    END = None
    StateGraph = None

from app.agents.promotions.routing import CHEF_DOMAIN
from app.agents.promotions.types import PromotionSubagentEnrichment
from app.models.user import User

CHEF_PROMOTION_AGENT_TYPE = "chef_agent"


class ChefPromotionState(TypedDict, total=False):
    campaign: dict[str, Any]
    current_user: User
    user_context: dict[str, Any]
    final_enrichment: PromotionSubagentEnrichment


class ChefPromotionSubagentGraph:
    def __init__(self) -> None:
        self._compiled_graph = self._compile_graph()

    def run_enrichment(
        self,
        *,
        campaign: dict[str, Any],
        current_user: User,
        user_context: dict[str, Any],
    ) -> PromotionSubagentEnrichment:
        initial_state: ChefPromotionState = {
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
        workflow = StateGraph(ChefPromotionState)
        workflow.add_node("finalize", self._finalize)
        workflow.set_entry_point("finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    @staticmethod
    def _finalize(state: ChefPromotionState) -> dict[str, Any]:
        context = dict(state.get("user_context") or {})
        preferences = dict(context.get("preference_snapshot") or {})
        allergies = [
            str(item).replace("_", " ").strip()
            for item in list(preferences.get("allergies") or [])
            if str(item).strip()
        ]
        diet_rules = [
            str(item).replace("_", " ").strip()
            for item in list(preferences.get("diet_rules") or [])
            if str(item).strip()
        ]
        guidance = [
            "Respect allergy and diet rule signals in any recipe or cooking angle.",
            "Prefer practical cooking value over generic hype when a recipe-led message is appropriate.",
        ]
        highlights: list[str] = []
        if allergies or diet_rules:
            highlights.append("Built with your food preferences in mind.")

        specs: list[dict[str, str]] = []
        if diet_rules:
            specs.append({"label": "Diet", "value": ", ".join(diet_rules[:2])[:60]})
        if allergies:
            specs.append({"label": "Avoids", "value": ", ".join(allergies[:2])[:60]})

        return {
            "final_enrichment": PromotionSubagentEnrichment(
                domain=CHEF_DOMAIN,
                agent_type=CHEF_PROMOTION_AGENT_TYPE,
                highlights=highlights[:1],
                specs=specs[:2],
                message_guidance=guidance,
                meal_data={
                    "diet_rules": diet_rules[:3],
                    "allergies": allergies[:3],
                },
                metadata={"source": "promotion_chef"},
            )
        }
