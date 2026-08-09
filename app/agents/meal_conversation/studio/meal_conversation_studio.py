"""LangGraph Studio entrypoint for SafeDaet meal conversation testing."""
from __future__ import annotations

import os
from typing import Any, TypedDict


def _normalize_debug_env() -> None:
    value = str(os.getenv("DEBUG") or "").strip().lower()
    if value and value not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
        os.environ["DEBUG"] = "false"


_normalize_debug_env()

from langgraph.graph import END, StateGraph

from app.agents.meal_conversation.graph import MealConversationGraph
from app.agents.meal_conversation.runtime import MealConversationRuntime
from app.agents.meal_conversation.subagents.chef.graph import ChefAgentGraph
from app.agents.meal_conversation.subagents.meal_planner.graph import MealPlannerGraph
from app.agents.meal_conversation.subagents.order.graph import OrderAgentGraph
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.mongodb import mongo_manager
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.meal_repository import MealRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.user_repository import UserRepository


class MealConversationStudioState(TypedDict, total=False):
    studio_user_id: str
    studio_user_text: str
    studio_quick_action_type: str | None
    studio_action_payload: dict[str, Any]
    studio_meal_type: str | None
    studio_country_code: str | None
    studio_conversation_id: str | None
    studio_history: list[dict[str, Any]]
    studio_result: dict[str, Any]


settings = get_settings()
configure_logging(settings.log_level)


def _build_runtime() -> MealConversationRuntime:
    mongo_manager.connect()
    mongo_manager.ensure_indexes()

    grocery_repository = GroceryRepository(
        mongo_manager.grocery_categories_collection(),
        mongo_manager.grocery_products_collection(),
    )
    grocery_repository.ensure_seed_data()

    meal_repository = MealRepository(
        mongo_manager.meal_categories_collection(),
        mongo_manager.meals_collection(),
    )
    meal_repository.ensure_seed_data()

    return MealConversationRuntime(
        user_repository=UserRepository(mongo_manager.users_collection()),
        meal_repository=meal_repository,
        grocery_repository=grocery_repository,
        meal_conversation_repository=MealConversationRepository(
            mongo_manager.meal_planning_conversations_collection(),
            mongo_manager.meal_planning_messages_collection(),
        ),
        saved_meal_plan_repository=SavedMealPlanRepository(
            mongo_manager.saved_meal_plans_collection(),
        ),
        openai_api_key=(
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else None
        ),
        model_name=settings.openai_meal_conversation_model,
        timeout_seconds=settings.openai_meal_conversation_timeout_seconds,
        embedding_model_name=settings.openai_meal_search_embedding_model,
        embedding_timeout_seconds=settings.openai_meal_search_embedding_timeout_seconds,
        semantic_candidate_pool_limit=settings.meal_semantic_search_candidate_pool_limit,
        semantic_embedding_batch_size=settings.meal_semantic_search_embedding_batch_size,
    )


_runtime = _build_runtime()
_meal_conversation_graph = MealConversationGraph(runtime=_runtime)
_meal_planner_graph = MealPlannerGraph(runtime=_runtime)
_order_agent_graph = OrderAgentGraph(runtime=_runtime)
_chef_agent_graph = ChefAgentGraph(runtime=_runtime)


def _resolve_test_user_id(explicit_user_id: str | None) -> str:
    if explicit_user_id:
        return explicit_user_id

    document = mongo_manager.users_collection().find_one({}, sort=[("created_at", 1)])
    if document is None:
        raise RuntimeError(
            "No users found in MongoDB. Create a SafeDaet user first or provide studio_user_id."
        )
    return str(document["_id"])


def _resolve_meal_type(raw_value: str | None) -> MealType | None:
    if not raw_value:
        return None
    try:
        return MealType(str(raw_value))
    except ValueError:
        return None


def _resolve_country_code(raw_value: str | None) -> CountryCode | None:
    if not raw_value:
        return None
    try:
        return CountryCode(str(raw_value))
    except ValueError:
        return None


def _serialize_result(result: Any) -> dict[str, Any]:
    return {
        "assistant_text": result.assistant_text,
        "agent_type": result.agent_type,
        "target_domain": result.target_domain,
        "meal_type": result.meal_type.value if result.meal_type is not None else None,
        "country_code": result.country_code.value if result.country_code is not None else None,
        "planned_meals": result.planned_meals,
        "selected_meal_id": result.selected_meal_id,
        "selected_meal_name": result.selected_meal_name,
        "meal_source": result.meal_source,
        "requested_culture": result.requested_culture,
        "last_user_intent": result.last_user_intent,
        "ui_blocks": result.ui_blocks,
        "quick_actions": result.quick_actions,
        "metadata": result.metadata,
    }


def _run_meal_conversation_graph(
    state: MealConversationStudioState,
) -> MealConversationStudioState:
    user_id = _resolve_test_user_id(state.get("studio_user_id"))
    current_user = _runtime.get_user(user_id)
    if current_user is None:
        raise RuntimeError(f"Could not load user '{user_id}' for LangStudio testing.")

    meal_type = _resolve_meal_type(state.get("studio_meal_type"))
    country_code = _resolve_country_code(state.get("studio_country_code"))
    result = _meal_conversation_graph.run_turn(
        current_user=current_user,
        conversation_id=state.get("studio_conversation_id") or "langstudio-meal-conversation",
        conversation_history=list(state.get("studio_history") or []),
        user_text=state.get("studio_user_text") or "Suggest a dinner that fits my preferences.",
        quick_action_type=state.get("studio_quick_action_type"),
        action_payload=dict(state.get("studio_action_payload") or {}),
        explicit_meal_type=meal_type,
        explicit_country_code=country_code,
    )
    return {
        **state,
        "studio_result": _serialize_result(result),
    }


def _run_meal_planner_graph(
    state: MealConversationStudioState,
) -> MealConversationStudioState:
    user_id = _resolve_test_user_id(state.get("studio_user_id"))
    current_user = _runtime.get_user(user_id)
    if current_user is None:
        raise RuntimeError(f"Could not load user '{user_id}' for LangStudio testing.")

    meal_type = _resolve_meal_type(state.get("studio_meal_type"))
    country_code = _resolve_country_code(state.get("studio_country_code"))
    result = _meal_planner_graph.run_turn(
        current_user=current_user,
        conversation_id=state.get("studio_conversation_id") or "langstudio-meal-planner",
        conversation_history=list(state.get("studio_history") or []),
        user_text=state.get("studio_user_text") or "Build me a dinner that fits my preferences.",
        quick_action_type=state.get("studio_quick_action_type"),
        action_payload=dict(state.get("studio_action_payload") or {}),
        explicit_meal_type=meal_type,
        explicit_country_code=country_code,
        trace_id=None,
    )
    return {
        **state,
        "studio_result": _serialize_result(result),
    }


def _run_order_agent_graph(
    state: MealConversationStudioState,
) -> MealConversationStudioState:
    user_id = _resolve_test_user_id(state.get("studio_user_id"))
    current_user = _runtime.get_user(user_id)
    if current_user is None:
        raise RuntimeError(f"Could not load user '{user_id}' for LangStudio testing.")

    meal_type = _resolve_meal_type(state.get("studio_meal_type"))
    country_code = _resolve_country_code(state.get("studio_country_code"))
    result = _order_agent_graph.run_turn(
        current_user=current_user,
        conversation_id=state.get("studio_conversation_id") or "langstudio-order-agent",
        conversation_history=list(state.get("studio_history") or []),
        user_text=state.get("studio_user_text") or "Track my order",
        quick_action_type=state.get("studio_quick_action_type"),
        action_payload=dict(state.get("studio_action_payload") or {}),
        explicit_meal_type=meal_type,
        explicit_country_code=country_code,
        trace_id=None,
    )
    return {
        **state,
        "studio_result": _serialize_result(result),
    }


def _run_chef_agent_graph(
    state: MealConversationStudioState,
) -> MealConversationStudioState:
    user_id = _resolve_test_user_id(state.get("studio_user_id"))
    current_user = _runtime.get_user(user_id)
    if current_user is None:
        raise RuntimeError(f"Could not load user '{user_id}' for LangStudio testing.")

    meal_type = _resolve_meal_type(state.get("studio_meal_type"))
    country_code = _resolve_country_code(state.get("studio_country_code"))
    result = _chef_agent_graph.run_turn(
        current_user=current_user,
        conversation_id=state.get("studio_conversation_id") or "langstudio-chef-agent",
        conversation_history=list(state.get("studio_history") or []),
        user_text=state.get("studio_user_text") or "What can I use instead of eggs?",
        quick_action_type=state.get("studio_quick_action_type"),
        action_payload=dict(state.get("studio_action_payload") or {}),
        explicit_meal_type=meal_type,
        explicit_country_code=country_code,
        trace_id=None,
    )
    return {
        **state,
        "studio_result": _serialize_result(result),
    }


def _compile_studio_graph(node_name: str, runner):
    builder = StateGraph(MealConversationStudioState)
    builder.add_node(node_name, runner)
    builder.set_entry_point(node_name)
    builder.add_edge(node_name, END)
    return builder.compile()


meal_conversation_graph = _compile_studio_graph("run_meal_conversation", _run_meal_conversation_graph)
meal_planner_graph = _compile_studio_graph("run_meal_planner", _run_meal_planner_graph)
order_agent_graph = _compile_studio_graph("run_order_agent", _run_order_agent_graph)
chef_agent_graph = _compile_studio_graph("run_chef_agent", _run_chef_agent_graph)
