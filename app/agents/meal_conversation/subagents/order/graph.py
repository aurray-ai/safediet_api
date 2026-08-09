from __future__ import annotations

from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    END = None
    StateGraph = None

from app.agents.meal_conversation.coordinator import ORDER_DOMAIN
from app.agents.meal_conversation.state import MealConversationTurnResult
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.user import User

ORDER_AGENT_TYPE = "order_agent"


class OrderAgentState(TypedDict, total=False):
    explicit_meal_type: MealType | None
    explicit_country_code: CountryCode | None
    final_result: MealConversationTurnResult


class OrderAgentGraph:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._compiled_graph = self._compile_graph()

    def run_turn(
        self,
        *,
        current_user: User,
        conversation_id: str,
        conversation_history: list[dict[str, Any]],
        user_text: str,
        quick_action_type: str | None,
        action_payload: dict[str, Any],
        explicit_meal_type: MealType | None,
        explicit_country_code: CountryCode | None,
        trace_id: str | None = None,
    ) -> MealConversationTurnResult:
        initial_state: OrderAgentState = {
            "explicit_meal_type": explicit_meal_type,
            "explicit_country_code": explicit_country_code,
        }
        if self._compiled_graph is None:
            state = dict(initial_state)
            state.update(self._finalize(initial_state))
        else:
            state = self._compiled_graph.invoke(initial_state)
        return state["final_result"]

    def _compile_graph(self):
        if StateGraph is None or END is None:
            return None
        workflow = StateGraph(OrderAgentState)
        workflow.add_node("finalize", self._finalize)
        workflow.set_entry_point("finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    @staticmethod
    def _finalize(state: OrderAgentState) -> dict[str, Any]:
        return {
            "final_result": MealConversationTurnResult(
                assistant_text=(
                    "I can coordinate order support soon, but the order agent is not connected yet."
                ),
                turn_mode="conversation_reply",
                agent_type=ORDER_AGENT_TYPE,
                target_domain=ORDER_DOMAIN,
                meal_type=state.get("explicit_meal_type"),
                country_code=state.get("explicit_country_code"),
                planned_meals=[],
                metadata={"agent_status": "not_connected"},
            )
        }
