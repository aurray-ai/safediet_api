from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict

try:
    from langgraph.graph.message import add_messages
except Exception:  # pragma: no cover - optional runtime dependency
    def add_messages(existing, new):  # type: ignore[no-untyped-def]
        return new

from app.models.grocery import CountryCode
from app.models.meal import MealType


@dataclass(frozen=True, slots=True)
class ConversationRunContext:
    conversation_id: str
    user_id: str
    turn_id: str
    meal_type: MealType | None
    country_code: CountryCode | None
    timestamp: datetime


class UserContextSnapshot(TypedDict, total=False):
    goal: str | None
    weekly_budget: int | None
    household_size: int | None
    culture_preferences: list[str]
    diet_rules: list[str]
    allergies: list[str]
    selected_plan_types: list[str]


class ConstraintState(TypedDict, total=False):
    target_domain: str
    user_id: str | None
    meal_type: str | None
    target_meal_types: list[str]
    requested_meal_types: list[str]
    missing_meal_types: list[str]
    request_kind: str
    requested_culture: str | None
    slot_candidate_counts: dict[str, int]
    bundle_count: int
    culture_preferences: list[str]
    weekly_budget: int | None
    household_size: int | None
    budget_priority: bool
    diet_rules: list[str]
    allergies: list[str]
    selected_plan_types: list[str]
    goal: str | None
    allow_custom_meal_creation: bool
    custom_meal_creation_reason: str | None
    prompt_constraints: list[str]


class ToolTraceEntry(TypedDict, total=False):
    name: str
    args: dict[str, Any]
    result: dict[str, Any]


class FinalPlanPayload(TypedDict, total=False):
    turn_mode: Literal["conversation_reply", "clarification_request", "day_plan_generated", "day_plan_updated"]
    assistant_text: str
    planned_meals: list[dict[str, Any]]
    requested_culture: str | None
    rationale: str | None
    issue: str | None
    totals: dict[str, Any]
    selected_bundle_id: str | None
    bundle_summary: dict[str, Any]
    inventory_summary: dict[str, Any]
    cart_summary: dict[str, Any]


class MealConversationGraphState(TypedDict, total=False):
    run_context: dict[str, Any]
    agent_type: str
    user_context: UserContextSnapshot
    constraint_state: ConstraintState
    latest_user_message: str
    latest_user_intent: str | None
    action_payload: dict[str, Any]
    messages: Annotated[list[Any], add_messages]
    candidate_meals_by_slot: dict[str, list[dict[str, Any]]]
    ranked_bundles: list[dict[str, Any]]
    selected_meal_ids: dict[str, str]
    selected_meal_details: dict[str, dict[str, Any]]
    created_meal_drafts: dict[str, dict[str, Any]]
    conversation_memory: list[dict[str, Any]]
    grocery_matches_by_slot: dict[str, list[dict[str, Any]]]
    nutrition_assessments: dict[str, dict[str, Any]]
    budget_assessments: dict[str, dict[str, Any]]
    tool_trace: list[ToolTraceEntry]
    tool_iterations: int
    monitoring_recorder: Any
    llm_raw: str | None
    llm_parsed: dict[str, Any] | None
    guardrail_report: dict[str, Any]
    final_plan: FinalPlanPayload
    ui_blocks: list[dict[str, Any]]
    quick_actions: list[dict[str, Any]]
    llm_metrics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MealConversationTurnResult:
    assistant_text: str
    turn_mode: Literal["conversation_reply", "clarification_request", "day_plan_generated", "day_plan_updated"]
    agent_type: str
    target_domain: str
    meal_type: MealType | None
    country_code: CountryCode | None
    planned_meals: list[dict[str, Any]] = field(default_factory=list)
    selected_meal_id: str | None = None
    selected_meal_name: str | None = None
    meal_source: str | None = None
    requested_culture: str | None = None
    last_user_intent: str | None = None
    ui_blocks: list[dict[str, Any]] = field(default_factory=list)
    quick_actions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
