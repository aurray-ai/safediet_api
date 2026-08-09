from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any, Protocol, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    END = None
    StateGraph = None

from app.agents.meal_conversation.coordinator import (
    CHEF_DOMAIN,
    MEAL_COORDINATOR_AGENT_TYPE,
    MEAL_PLANNING_DOMAIN,
    ORDER_DOMAIN,
    infer_target_domain,
)
from app.agents.meal_conversation.runtime import MealConversationRuntime
from app.agents.meal_conversation.state import MealConversationTurnResult
from app.agents.meal_conversation.subagents.chef.graph import ChefAgentGraph
from app.agents.meal_conversation.subagents.meal_planner.graph import MealPlannerGraph
from app.agents.meal_conversation.subagents.order.graph import OrderAgentGraph
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.user import User

logger = logging.getLogger(__name__)


class CoordinatorGraphState(TypedDict, total=False):
    current_user: User
    conversation_id: str
    conversation_history: list[dict[str, Any]]
    user_text: str
    quick_action_type: str | None
    action_payload: dict[str, Any]
    explicit_meal_type: MealType | None
    explicit_country_code: CountryCode | None
    trace_id: str | None
    target_domain: str
    selected_subagent: str
    subagent_result: MealConversationTurnResult


class ConversationSubagent(Protocol):
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
    ) -> MealConversationTurnResult: ...


class MealConversationGraph:
    def __init__(self, runtime: MealConversationRuntime) -> None:
        self.runtime = runtime
        self._subagents: dict[str, ConversationSubagent] = {
            MEAL_PLANNING_DOMAIN: MealPlannerGraph(runtime=runtime),
            ORDER_DOMAIN: OrderAgentGraph(runtime=runtime),
            CHEF_DOMAIN: ChefAgentGraph(runtime=runtime),
        }
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
        initial_state: CoordinatorGraphState = {
            "current_user": current_user,
            "conversation_id": conversation_id,
            "conversation_history": list(conversation_history),
            "user_text": user_text,
            "quick_action_type": quick_action_type,
            "action_payload": dict(action_payload or {}),
            "explicit_meal_type": explicit_meal_type,
            "explicit_country_code": explicit_country_code,
            "trace_id": trace_id,
        }
        logger.info(
            "planner.coordinator.run_turn.start trace_id=%s conversation_id=%s text_len=%s quick_action_type=%s",
            trace_id or "-",
            conversation_id,
            len(user_text.strip()),
            quick_action_type or "-",
        )
        if self._compiled_graph is None:
            state = dict(initial_state)
            state.update(self._route_request(state))
            state.update(self._delegate_to_subagent(state))
            state.update(self._finalize_turn(state))
        else:
            state = self._compiled_graph.invoke(initial_state)
        result = state["subagent_result"]
        logger.info(
            "planner.coordinator.run_turn.completed trace_id=%s conversation_id=%s target_domain=%s subagent=%s turn_mode=%s",
            trace_id or "-",
            conversation_id,
            result.target_domain,
            state.get("selected_subagent", "-"),
            result.turn_mode,
        )
        return result

    def _compile_graph(self):
        if StateGraph is None or END is None:
            return None

        workflow = StateGraph(CoordinatorGraphState)
        workflow.add_node("route_request", self._route_request)
        workflow.add_node("delegate_to_subagent", self._delegate_to_subagent)
        workflow.add_node("finalize_turn", self._finalize_turn)
        workflow.set_entry_point("route_request")
        workflow.add_edge("route_request", "delegate_to_subagent")
        workflow.add_edge("delegate_to_subagent", "finalize_turn")
        workflow.add_edge("finalize_turn", END)
        return workflow.compile()

    def _route_request(self, state: CoordinatorGraphState) -> dict[str, Any]:
        target_domain = infer_target_domain(
            user_message=state.get("user_text"),
            quick_action_type=state.get("quick_action_type"),
            action_payload=state.get("action_payload"),
        )
        return {
            "target_domain": target_domain,
            "selected_subagent": self._selected_subagent_name(target_domain),
        }

    def _delegate_to_subagent(self, state: CoordinatorGraphState) -> dict[str, Any]:
        target_domain = str(state.get("target_domain") or MEAL_PLANNING_DOMAIN)
        subagent = self._subagents.get(target_domain) or self._subagents[MEAL_PLANNING_DOMAIN]
        result = subagent.run_turn(
            current_user=state["current_user"],
            conversation_id=state["conversation_id"],
            conversation_history=list(state.get("conversation_history") or []),
            user_text=state.get("user_text") or "",
            quick_action_type=state.get("quick_action_type"),
            action_payload=dict(state.get("action_payload") or {}),
            explicit_meal_type=state.get("explicit_meal_type"),
            explicit_country_code=state.get("explicit_country_code"),
            trace_id=state.get("trace_id"),
        )
        return {"subagent_result": result}

    def _finalize_turn(self, state: CoordinatorGraphState) -> dict[str, Any]:
        result = state.get("subagent_result")
        if result is None:
            result = MealConversationTurnResult(
                assistant_text="I could not route that request yet.",
                turn_mode="conversation_reply",
                agent_type=MEAL_COORDINATOR_AGENT_TYPE,
                target_domain=str(state.get("target_domain") or MEAL_PLANNING_DOMAIN),
                meal_type=state.get("explicit_meal_type"),
                country_code=state.get("explicit_country_code"),
                metadata={"routing_error": "missing_subagent_result"},
            )

        metadata = {
            **dict(result.metadata or {}),
            "coordinator_agent_type": MEAL_COORDINATOR_AGENT_TYPE,
            "selected_subagent": state.get("selected_subagent"),
            "selected_subagent_type": result.agent_type,
            "target_domain": result.target_domain,
        }
        normalized_result = replace(
            result,
            agent_type=MEAL_COORDINATOR_AGENT_TYPE,
            metadata=metadata,
        )
        return {"subagent_result": normalized_result}

    @staticmethod
    def _selected_subagent_name(target_domain: str) -> str:
        if target_domain == ORDER_DOMAIN:
            return "order_agent"
        if target_domain == CHEF_DOMAIN:
            return "chef_agent"
        return "meal_planner_agent"
