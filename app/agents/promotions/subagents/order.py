from __future__ import annotations

from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    END = None
    StateGraph = None

from app.agents.promotions.routing import ORDER_DOMAIN
from app.agents.promotions.types import PromotionSubagentEnrichment
from app.models.user import User

ORDER_PROMOTION_AGENT_TYPE = "order_agent"


class OrderPromotionState(TypedDict, total=False):
    campaign: dict[str, Any]
    current_user: User
    user_context: dict[str, Any]
    final_enrichment: PromotionSubagentEnrichment


class OrderPromotionSubagentGraph:
    def __init__(self) -> None:
        self._compiled_graph = self._compile_graph()

    def run_enrichment(
        self,
        *,
        campaign: dict[str, Any],
        current_user: User,
        user_context: dict[str, Any],
    ) -> PromotionSubagentEnrichment:
        initial_state: OrderPromotionState = {
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
        workflow = StateGraph(OrderPromotionState)
        workflow.add_node("finalize", self._finalize)
        workflow.set_entry_point("finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    @staticmethod
    def _finalize(state: OrderPromotionState) -> dict[str, Any]:
        campaign = dict(state.get("campaign") or {})
        constraints = dict(campaign.get("constraints") or {})
        budget = str(constraints.get("budget") or "").strip()
        country_code = str(constraints.get("country_code") or "").strip()
        delivery_window = str(constraints.get("delivery_window") or "").strip()

        highlights: list[str] = []
        if budget:
            highlights.append(f"Shaped for a {budget} budget.")

        specs: list[dict[str, str]] = []
        if country_code:
            specs.append({"label": "Market", "value": country_code[:30]})
        if budget:
            specs.append({"label": "Budget", "value": budget[:60]})
        if delivery_window:
            specs.append({"label": "Delivery", "value": delivery_window[:60]})

        guidance = [
            "Frame the value around grocery convenience, reorder readiness, or delivery follow-through.",
            "Keep the CTA actionable for shopping, ordering, or checking basket progress when relevant.",
        ]

        return {
            "final_enrichment": PromotionSubagentEnrichment(
                domain=ORDER_DOMAIN,
                agent_type=ORDER_PROMOTION_AGENT_TYPE,
                highlights=highlights[:1],
                specs=specs[:3],
                message_guidance=guidance,
                grocery_data={
                    "budget": budget or None,
                    "country_code": country_code or None,
                    "delivery_window": delivery_window or None,
                },
                metadata={"source": "promotion_order"},
            )
        }
