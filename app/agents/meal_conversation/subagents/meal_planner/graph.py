from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    AIMessage = None
    HumanMessage = None
    SystemMessage = None
    END = None
    StateGraph = None

from app.agents.meal_conversation.coordinator import MEAL_PLANNING_DOMAIN
from app.agents.meal_conversation.guardrails import review_guardrails
from app.agents.meal_conversation.prompting import build_meal_conversation_system_prompt
from app.agents.meal_conversation.runtime import MealConversationRuntime
from app.agents.meal_conversation.state import MealConversationGraphState, MealConversationTurnResult
from app.models.grocery import CountryCode
from app.models.measurement import RoundingRule
from app.models.meal import MealType
from app.services.meal_scaling_service import MealScalingService
from app.models.user import User

logger = logging.getLogger(__name__)

MEAL_PLANNER_AGENT_TYPE = "meal_planner_agent"
REQUESTED_SLOT_FIELDS: tuple[tuple[str, str], ...] = (
    ("breakfast", "breakfast_slots"),
    ("lunch", "lunch_slots"),
    ("dinner", "dinner_slots"),
    ("snack", "snack_slots"),
)


class MealPlannerGraph:
    def __init__(self, runtime: MealConversationRuntime) -> None:
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
        monitoring_recorder: Any | None = None,
    ) -> MealConversationTurnResult:
        started_at = time.perf_counter()
        self.runtime.set_active_user_id(current_user.id)
        initial_state = self._initialize_state(
            current_user=current_user,
            conversation_id=conversation_id,
            conversation_history=conversation_history,
            user_text=user_text,
            quick_action_type=quick_action_type,
            action_payload=action_payload,
            explicit_meal_type=explicit_meal_type,
            explicit_country_code=explicit_country_code,
            trace_id=trace_id,
            monitoring_recorder=monitoring_recorder,
        )
        logger.info(
            "planner.graph.run_turn.start trace_id=%s turn_id=%s conversation_id=%s history_messages=%s text_len=%s quick_action_type=%s",
            trace_id or "-",
            initial_state["run_context"]["turn_id"],
            conversation_id,
            len(conversation_history),
            len(user_text.strip()),
            quick_action_type or "-",
        )

        if self._compiled_graph is None:
            state = dict(initial_state)
            self._merge_state(state, self._prepare_planner_input(state))
            if not state.get("final_plan"):
                self._merge_state(state, self._agent(state))
                self._merge_state(state, self._finalize_plan(state))
                self._merge_state(state, self._materialize_selected_meals(state))
            self._merge_state(state, self._guardrail_review(state))
            self._merge_state(state, self._ui_response_builder(state))
            self._merge_state(state, self._finalize_turn(state))
            final_state = state
        else:
            try:
                final_state = self._compiled_graph.invoke(initial_state)
            except Exception:
                logger.exception(
                    "Meal planner graph failed for conversation %s.",
                    conversation_id,
                )
                final_state = self._failed_state(
                    initial_state,
                    assistant_text="Meal generation failed right now. Please try again.",
                    rationale="The meal planner could not complete this turn safely.",
                    issue="graph_execution_failed",
                )

        result = self._to_turn_result(final_state)
        logger.info(
            "planner.graph.run_turn.completed trace_id=%s turn_id=%s conversation_id=%s duration_ms=%s turn_mode=%s planned_meals=%s",
            trace_id or "-",
            final_state.get("run_context", {}).get("turn_id", "-"),
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            result.turn_mode,
            len(result.planned_meals),
        )
        return result

    def _compile_graph(self):
        if StateGraph is None or END is None:
            return None

        workflow = StateGraph(MealConversationGraphState)
        workflow.add_node("prepare_planner_input", self._prepare_planner_input)
        workflow.add_node("agent", self._agent)
        workflow.add_node("finalize_plan", self._finalize_plan)
        workflow.add_node("materialize_selected_meals", self._materialize_selected_meals)
        workflow.add_node("guardrail_review", self._guardrail_review)
        workflow.add_node("ui_response_builder", self._ui_response_builder)
        workflow.add_node("finalize_turn", self._finalize_turn)

        workflow.set_entry_point("prepare_planner_input")
        workflow.add_conditional_edges(
            "prepare_planner_input",
            self._route_after_prepare_input,
            {
                "agent": "agent",
                "guardrail_review": "guardrail_review",
            },
        )
        workflow.add_edge("agent", "finalize_plan")
        workflow.add_edge("finalize_plan", "materialize_selected_meals")
        workflow.add_edge("materialize_selected_meals", "guardrail_review")
        workflow.add_edge("guardrail_review", "ui_response_builder")
        workflow.add_edge("ui_response_builder", "finalize_turn")
        workflow.add_edge("finalize_turn", END)
        return workflow.compile()

    def _initialize_state(
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
        trace_id: str | None,
        monitoring_recorder: Any | None,
    ) -> MealConversationGraphState:
        resolved_meal_type = (
            explicit_meal_type.value if explicit_meal_type is not None else action_payload.get("meal_type")
        )
        resolved_country_code = (
            explicit_country_code.value if explicit_country_code is not None else action_payload.get("country_code")
        )
        return {
            "run_context": {
                "conversation_id": conversation_id,
                "user_id": current_user.id,
                "turn_id": uuid4().hex,
                "meal_type": resolved_meal_type,
                "country_code": resolved_country_code,
                "trace_id": trace_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "agent_type": MEAL_PLANNER_AGENT_TYPE,
            "latest_user_message": user_text,
            "latest_user_intent": quick_action_type or None,
            "action_payload": dict(action_payload or {}),
            "monitoring_recorder": monitoring_recorder,
            "messages": self._history_to_messages(conversation_history),
            "candidate_meals_by_slot": {},
            "ranked_bundles": [],
            "selected_meal_ids": {},
            "selected_meal_details": {},
            "created_meal_drafts": {},
            "grocery_matches_by_slot": {},
            "nutrition_assessments": {},
            "budget_assessments": {},
            "tool_trace": [],
        }

    def _prepare_planner_input(self, state: MealConversationGraphState) -> dict[str, Any]:
        action_payload = dict(state.get("action_payload") or {})
        user_context = self._normalize_user_context(action_payload.get("user_context"))
        candidate_meals_by_slot = self._normalize_slot_candidates(action_payload)
        ranked_bundles = self._normalize_ranked_bundles(action_payload.get("ranked_bundles"))
        requested_slots = [
            slot
            for slot in self._normalized_string_list(action_payload.get("requested_slots"))
            if slot in {item.value for item in MealType}
        ]
        if not requested_slots:
            requested_slots = list(candidate_meals_by_slot.keys())
        missing_slots = [
            slot
            for slot in self._normalized_string_list(action_payload.get("missing_slots"))
            if slot in {item.value for item in MealType}
        ]
        available_slots = list(candidate_meals_by_slot.keys())
        requested_culture = self._resolved_requested_culture(action_payload, user_context)
        request_kind = str(action_payload.get("request_kind") or "day_plan_request").strip() or "day_plan_request"
        primary_slot = requested_slots[0] if len(requested_slots) == 1 else None
        effective_date = self._resolved_effective_date(action_payload)
        selected_dates = self._resolved_selected_dates(action_payload)

        updates: dict[str, Any] = {
            "user_context": user_context,
            "candidate_meals_by_slot": candidate_meals_by_slot,
            "ranked_bundles": ranked_bundles,
            "constraint_state": {
                "target_domain": MEAL_PLANNING_DOMAIN,
                "user_id": state.get("run_context", {}).get("user_id"),
                "meal_type": primary_slot,
                "target_meal_types": available_slots,
                "requested_meal_types": requested_slots,
                "missing_meal_types": missing_slots,
                "request_kind": request_kind,
                "requested_culture": requested_culture,
                "slot_candidate_counts": {
                    slot: len(items)
                    for slot, items in candidate_meals_by_slot.items()
                },
                "bundle_count": len(ranked_bundles),
                "culture_preferences": list(user_context.get("culture_preferences", [])),
                "weekly_budget": user_context.get("weekly_budget"),
                "household_size": user_context.get("household_size"),
                "budget_priority": bool(action_payload.get("low_budget_mode")),
                "diet_rules": list(user_context.get("diet_rules", [])),
                "allergies": list(user_context.get("allergies", [])),
                "goal": user_context.get("goal"),
                "effective_date": effective_date,
                "selected_dates": selected_dates,
                "prompt_constraints": self._build_prompt_constraints(
                    requested_slots=requested_slots,
                    candidate_meals_by_slot=candidate_meals_by_slot,
                    requested_culture=requested_culture,
                    user_context=user_context,
                    request_kind=request_kind,
                    effective_date=effective_date,
                    selected_dates=selected_dates,
                    available_slots=available_slots,
                    missing_slots=missing_slots,
                ),
            },
        }

        logger.info(
            "planner.graph.prepare_input trace_id=%s turn_id=%s request_kind=%s requested_slots=%s available_slots=%s missing_slots=%s",
            self._trace_id(state),
            self._turn_id(state),
            request_kind,
            ",".join(requested_slots) or "-",
            ",".join(available_slots) or "-",
            ",".join(missing_slots) or "-",
        )
        recorder = self._monitoring_recorder(state)
        if recorder is not None:
            recorder.log(
                step_key="planner.graph.prepare_input",
                parent_step_id=recorder.root_step_id,
                branch_key="graph",
                input_data={
                    "request_kind": request_kind,
                    "requested_slots": requested_slots,
                },
                output_data={
                    "available_slots": available_slots,
                    "missing_slots": missing_slots,
                    "bundle_count": len(ranked_bundles),
                },
            )

        if not user_context:
            updates["final_plan"] = self._clarification_response(
                issue="missing_user_context",
                assistant_text=(
                    "I need your meal-planning context first. Please provide your goal, allergies, diet rules, culture preferences, and budget."
                ),
                rationale="The planner requires user context before it can evaluate meal candidates.",
            )
            return updates

        if not requested_slots:
            updates["final_plan"] = self._clarification_response(
                issue="missing_requested_slots",
                assistant_text=(
                    "Send at least one requested meal slot with candidate meals for breakfast, lunch, dinner, or snack."
                ),
                rationale="No requested slot candidate lists were provided to the planner.",
            )
            return updates

        return updates

    @staticmethod
    def _route_after_prepare_input(state: MealConversationGraphState) -> str:
        return "guardrail_review" if state.get("final_plan") else "agent"

    def _agent(self, state: MealConversationGraphState) -> dict[str, Any]:
        started_at = time.perf_counter()
        recorder = self._monitoring_recorder(state)
        llm_step_id = (
            recorder.start_step(
                step_key="planner.llm.invoke",
                parent_step_id=recorder.root_step_id,
                branch_key="llm",
                step_type="llm",
                input_data={
                    "request_kind": state.get("constraint_state", {}).get("request_kind"),
                    "requested_slots": list(state.get("constraint_state", {}).get("target_meal_types", [])),
                },
            )
            if recorder is not None
            else None
        )
        if state.get("constraint_state", {}).get("target_domain") != MEAL_PLANNING_DOMAIN:
            response = self._json_ai_message(self._unsupported_domain_response(state))
            llm_duration_ms = int((time.perf_counter() - started_at) * 1000)
            if recorder is not None and llm_step_id is not None:
                recorder.complete_step(
                    step_id=llm_step_id,
                    step_key="planner.llm.invoke",
                    parent_step_id=recorder.root_step_id,
                    branch_key="llm",
                    step_type="llm",
                    output_data={"provider": "coordinator_guard"},
                    metrics={"duration_ms": llm_duration_ms, "tool_calls": 0},
                )
            return {
                "messages": [response],
                "llm_raw": self._extract_text_content(response),
                "llm_metrics": {
                    "provider": "coordinator_guard",
                    "model_name": None,
                    "duration_ms": llm_duration_ms,
                    "tool_calls": 0,
                },
            }

        model = self.runtime.build_model()
        if model is None or AIMessage is None or SystemMessage is None or HumanMessage is None:
            response = self._json_ai_message(
                self._generation_failed_response(
                    state,
                    issue="llm_unavailable",
                    rationale="The planner model or message runtime is unavailable for this turn.",
                    assistant_text="Meal generation is unavailable right now. Please try again shortly.",
                )
            )
            llm_duration_ms = int((time.perf_counter() - started_at) * 1000)
            if recorder is not None and llm_step_id is not None:
                recorder.complete_step(
                    step_id=llm_step_id,
                    step_key="planner.llm.invoke",
                    parent_step_id=recorder.root_step_id,
                    branch_key="llm",
                    step_type="llm",
                    output_data={"provider": "unavailable"},
                    metrics={"duration_ms": llm_duration_ms, "tool_calls": 0},
                    status="degraded",
                )
            return {
                "messages": [response],
                "llm_raw": self._extract_text_content(response),
                "llm_metrics": {
                    "provider": "unavailable",
                    "model_name": None,
                    "duration_ms": llm_duration_ms,
                    "tool_calls": 0,
                },
            }

        system_prompt = build_meal_conversation_system_prompt(
            constraint_state=state.get("constraint_state") or {},
        )
        request_messages = [
            SystemMessage(content=system_prompt),
            *list(state.get("messages") or []),
            HumanMessage(content=self._planner_request_payload(state)),
        ]
        llm_request_payload = self._llm_request_payload(model=model, messages=request_messages)
        logger.info(
            "planner.graph.agent.invoke trace_id=%s turn_id=%s request_kind=%s requested_slots=%s",
            self._trace_id(state),
            self._turn_id(state),
            state.get("constraint_state", {}).get("request_kind"),
            ",".join(state.get("constraint_state", {}).get("target_meal_types", [])) or "-",
        )
        logger.debug(
            "planner.graph.agent.request trace_id=%s turn_id=%s payload=%s",
            self._trace_id(state),
            self._turn_id(state),
            self._json_string(llm_request_payload),
        )
        llm_failed = False
        try:
            response = model.invoke(request_messages)
        except Exception as exc:
            llm_failed = True
            if recorder is not None and llm_step_id is not None:
                recorder.fail_step(
                    step_id=llm_step_id,
                    step_key="planner.llm.invoke",
                    parent_step_id=recorder.root_step_id,
                    branch_key="llm",
                    step_type="llm",
                    error={
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                )
            logger.exception(
                "Meal planner LLM call failed for conversation %s.",
                state.get("run_context", {}).get("conversation_id"),
            )
            response = self._json_ai_message(
                self._generation_failed_response(
                    state,
                    issue="llm_invocation_failed",
                    rationale="The planner model could not complete this turn.",
                    assistant_text="Meal generation failed right now. Please try again.",
                )
            )
        llm_duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.debug(
            "planner.graph.agent.response trace_id=%s turn_id=%s payload=%s",
            self._trace_id(state),
            self._turn_id(state),
            self._message_payload(response),
        )
        usage_metadata = dict(getattr(response, "usage_metadata", None) or {})
        response_metadata = dict(getattr(response, "response_metadata", None) or {})
        if recorder is not None and llm_step_id is not None and not llm_failed:
            recorder.complete_step(
                step_id=llm_step_id,
                step_key="planner.llm.invoke",
                parent_step_id=recorder.root_step_id,
                branch_key="llm",
                step_type="llm",
                output_data={
                    "response_id": response_metadata.get("id"),
                    "finish_reason": response_metadata.get("finish_reason"),
                    "model_name": response_metadata.get("model_name") or self.runtime.model_name,
                },
                metrics={
                    "duration_ms": llm_duration_ms,
                    "tool_calls": 0,
                    "input_tokens": usage_metadata.get("input_tokens"),
                    "output_tokens": usage_metadata.get("output_tokens"),
                    "total_tokens": usage_metadata.get("total_tokens"),
                },
            )
        return {
            "messages": [response],
            "llm_raw": self._extract_text_content(response),
            "llm_metrics": {
                "provider": "openai" if response_metadata else "error_response",
                "model_name": response_metadata.get("model_name") or self.runtime.model_name,
                "duration_ms": llm_duration_ms,
                "tool_calls": 0,
                "response_id": response_metadata.get("id"),
                "finish_reason": response_metadata.get("finish_reason"),
                "input_tokens": usage_metadata.get("input_tokens"),
                "output_tokens": usage_metadata.get("output_tokens"),
                "total_tokens": usage_metadata.get("total_tokens"),
            },
        }

    def _finalize_plan(self, state: MealConversationGraphState) -> dict[str, Any]:
        parsed = self._parse_final_plan_from_messages(state)
        if parsed is None:
            parsed = self._generation_failed_response(
                state,
                issue="final_plan_missing",
                rationale="The planner did not return a valid final payload for this turn.",
                assistant_text="Meal generation failed right now. Please try again.",
            )
        ranked_bundles = list(state.get("ranked_bundles") or [])
        if ranked_bundles and not str(parsed.get("selected_bundle_id") or "").strip():
            matched_bundle = self._match_ranked_bundle_for_plan(
                ranked_bundles=ranked_bundles,
                planned_meals=list(parsed.get("planned_meals") or []),
            )
            if matched_bundle is not None:
                parsed["selected_bundle_id"] = matched_bundle.get("bundle_id")
            elif str(parsed.get("turn_mode") or "") in {"day_plan_generated", "day_plan_updated"}:
                fallback_bundle = dict(ranked_bundles[0])
                parsed["selected_bundle_id"] = fallback_bundle.get("bundle_id")
                if not list(parsed.get("planned_meals") or []):
                    parsed["planned_meals"] = list(fallback_bundle.get("planned_meals") or [])
                if not dict(parsed.get("totals") or {}):
                    parsed["totals"] = dict(fallback_bundle.get("totals") or {})
        recorder = self._monitoring_recorder(state)
        if recorder is not None:
            recorder.log(
                step_key="planner.llm.parsed",
                parent_step_id=recorder.root_step_id,
                branch_key="llm",
                output_data={
                    "turn_mode": parsed.get("turn_mode"),
                    "selected_bundle_id": parsed.get("selected_bundle_id"),
                    "planned_meal_count": len(parsed.get("planned_meals") or []),
                },
            )
        return {
            "llm_parsed": parsed,
            "final_plan": parsed,
        }

    def _materialize_selected_meals(self, state: MealConversationGraphState) -> dict[str, Any]:
        final_plan = dict(state.get("final_plan") or {})
        turn_mode = str(final_plan.get("turn_mode") or "conversation_reply")
        if turn_mode not in {"day_plan_generated", "day_plan_updated"}:
            return {}

        requested_slots = list(state.get("constraint_state", {}).get("target_meal_types", []))
        candidate_meals_by_slot = dict(state.get("candidate_meals_by_slot") or {})
        ranked_bundles = list(state.get("ranked_bundles") or [])
        selected_meal_ids: dict[str, str] = {}
        selected_meal_details: dict[str, dict[str, Any]] = {}
        nutrition_assessments: dict[str, dict[str, Any]] = {}
        normalized_planned_meals: list[dict[str, Any]] = []
        missing_slots: list[str] = []

        selected_bundle_id = str(final_plan.get("selected_bundle_id") or "").strip()
        if selected_bundle_id and ranked_bundles:
            selected_bundle = next(
                (
                    dict(bundle)
                    for bundle in ranked_bundles
                    if str(bundle.get("bundle_id") or "").strip() == selected_bundle_id
                ),
                None,
            )
            if selected_bundle is not None:
                meals_by_slot = {
                    self._normalize_slot_name(slot): dict(meal)
                    for slot, meal in dict(selected_bundle.get("meals_by_slot") or {}).items()
                    if self._normalize_slot_name(slot)
                }
                for slot in requested_slots:
                    selected_candidate = meals_by_slot.get(slot)
                    if selected_candidate is None:
                        missing_slots.append(slot)
                        continue
                    selected_meal_ids[slot] = str(selected_candidate["id"])
                    selected_meal_details[slot] = {"meal": selected_candidate}
                    nutrition_assessments[slot] = {
                        "slot": slot,
                        "summary": dict(selected_candidate.get("nutrition_summary") or {}),
                        "fit": "ranked_bundle",
                        "notes": ["Nutrition summary is sourced from the selected ranked bundle."],
                    }
                    normalized_planned_meals.append(
                        {
                            "slot": slot,
                            "meal_id": selected_candidate["id"],
                            "meal_name": self._candidate_display_name(selected_candidate),
                            "meal_source": "catalog",
                            "created_meal_draft": None,
                        }
                    )
                if not missing_slots:
                    updates = {
                        "selected_meal_ids": selected_meal_ids,
                        "selected_meal_details": selected_meal_details,
                        "nutrition_assessments": nutrition_assessments,
                    }
                    recompute_state = dict(state)
                    recompute_state.update(updates)
                    final_plan["planned_meals"] = normalized_planned_meals
                    final_plan["totals"] = dict(selected_bundle.get("totals") or self._compute_totals(recompute_state))
                    final_plan["bundle_summary"] = dict(selected_bundle.get("bundle_summary") or {})
                    final_plan["inventory_summary"] = dict(selected_bundle.get("inventory_summary") or {})
                    final_plan["cart_summary"] = dict(selected_bundle.get("cart_summary") or {})
                    updates["final_plan"] = final_plan
                    return updates

        for slot in requested_slots:
            planned_entry = next(
                (
                    dict(item)
                    for item in list(final_plan.get("planned_meals") or [])
                    if self._normalize_slot_name(item.get("slot")) == slot
                ),
                None,
            )
            if planned_entry is None:
                missing_slots.append(slot)
                continue

            selected_candidate = self._find_candidate_for_selection(
                slot=slot,
                candidates=list(candidate_meals_by_slot.get(slot) or []),
                planned_entry=planned_entry,
            )
            if selected_candidate is None:
                missing_slots.append(slot)
                continue

            selected_meal_ids[slot] = str(selected_candidate["id"])
            selected_meal_details[slot] = {"meal": selected_candidate}
            nutrition_assessments[slot] = {
                "slot": slot,
                "summary": dict(selected_candidate.get("nutrition_summary") or {}),
                "fit": "provided_candidate",
                "notes": ["Nutrition summary is sourced from the provided planner candidates."],
            }
            normalized_planned_meals.append(
                {
                    "slot": slot,
                    "meal_id": selected_candidate["id"],
                    "meal_name": self._candidate_display_name(selected_candidate),
                    "meal_source": "catalog",
                    "created_meal_draft": None,
                }
            )

        if missing_slots:
            return {
                "final_plan": self._clarification_response(
                    issue="invalid_meal_selection",
                    assistant_text=(
                        "I need better meal candidates for "
                        + ", ".join(slot.capitalize() for slot in missing_slots)
                        + "."
                    ),
                    rationale="The planner response did not produce a valid candidate-backed selection for every requested slot.",
                ),
                "selected_meal_ids": {},
                "selected_meal_details": {},
                "nutrition_assessments": {},
            }

        updates = {
            "selected_meal_ids": selected_meal_ids,
            "selected_meal_details": selected_meal_details,
            "nutrition_assessments": nutrition_assessments,
        }
        recompute_state = dict(state)
        recompute_state.update(updates)
        final_plan["planned_meals"] = normalized_planned_meals
        final_plan["totals"] = self._compute_totals(recompute_state)
        updates["final_plan"] = final_plan
        return updates

    def _guardrail_review(self, state: MealConversationGraphState) -> dict[str, Any]:
        final_plan = dict(state.get("final_plan") or {})
        if final_plan.get("turn_mode") in {"conversation_reply", "clarification_request"}:
            return {"guardrail_report": {"passed": True, "issues": []}}

        report = review_guardrails(
            selected_meal_details=dict(state.get("selected_meal_details") or {}),
            created_meal_drafts=dict(state.get("created_meal_drafts") or {}),
            user_context=state.get("user_context") or {},
            final_plan=final_plan,
        )
        updates: dict[str, Any] = {"guardrail_report": report}
        if report.get("passed", False):
            return updates

        updates.update(
            {
                "final_plan": {
                    "turn_mode": "clarification_request",
                    "assistant_text": "I couldn’t safely finalize this meal plan yet. Please send safer alternatives for the requested slots.",
                    "planned_meals": [],
                    "rationale": "Guardrail review rejected the selected meals.",
                    "issue": "; ".join(report.get("issues", [])),
                    "totals": {},
                },
                "selected_meal_ids": {},
                "selected_meal_details": {},
                "nutrition_assessments": {},
            }
        )
        return updates

    def _ui_response_builder(self, state: MealConversationGraphState) -> dict[str, Any]:
        final_plan = dict(state.get("final_plan") or {})
        turn_mode = str(final_plan.get("turn_mode") or "conversation_reply")
        request_kind = str(state.get("constraint_state", {}).get("request_kind") or "day_plan_request")
        target_meal_types = self._resolve_presentation_slots(state=state)
        ui_blocks: list[dict[str, Any]] = []
        recorder = self._monitoring_recorder(state)
        ui_step_id = (
            recorder.start_step(
                step_key="planner.ui_response.build",
                parent_step_id=recorder.root_step_id,
                branch_key="ui",
                step_type="ui",
            )
            if recorder is not None
            else None
        )
        day_plan_sections = self._build_meal_plan_sections(state=state, target_meal_types=target_meal_types)
        start_date = self._effective_start_date(state)
        effective_date = start_date.isoformat()

        if turn_mode in {"day_plan_generated", "day_plan_updated"} and day_plan_sections:
            snapshot_id = uuid4().hex
            totals = dict(final_plan.get("totals") or self._compute_totals(state))
            is_multi_day_request = request_kind in {"week_plan_request", "multi_day_plan_request"}
            week_days = (
                self._build_week_plan_days(
                    state=state,
                    sections=day_plan_sections,
                    totals=totals,
                )
                if is_multi_day_request
                else []
            )
            period_start = self._multi_day_period_start(state=state, days=week_days)
            period_end = self._multi_day_period_end(state=state, days=week_days)
            actions_payload = self._build_meal_plan_actions(
                state=state,
                target_meal_types=target_meal_types,
                snapshot_id=snapshot_id,
                saved=False,
            )
            shared_payload = {
                "snapshot_id": snapshot_id,
                "title": "Meal Plan",
                "view_mode": "week" if is_multi_day_request else "day",
                "state": "draft",
                "effective_date": effective_date,
                "tracked_text": f"Tracked 0/{len(day_plan_sections)} meals",
                "totals": totals,
                "sections": day_plan_sections,
                "days": week_days,
                "monitoring": {
                    "run_id": ((state.get("action_payload") or {}).get("monitoring") or {}).get("run_id"),
                    "trace_id": ((state.get("action_payload") or {}).get("monitoring") or {}).get("trace_id"),
                    "root_step_id": ((state.get("action_payload") or {}).get("monitoring") or {}).get("root_step_id"),
                    "ui_step_id": ui_step_id,
                },
                **actions_payload,
            }
            if is_multi_day_request:
                shared_payload["week_start"] = period_start.isoformat()
                shared_payload["week_end"] = period_end.isoformat()
                shared_payload["period_label"] = self._period_label(
                    state=state,
                    days=week_days,
                    request_kind=request_kind,
                )
                shared_payload["daily_snapshots"] = self._build_weekly_day_snapshots(
                    state=state,
                    days=week_days,
                )
                shared_payload["batch_groups"] = self._build_weekly_batch_groups(days=week_days)
                shared_payload["leftover_links"] = self._build_weekly_leftover_links(days=week_days)
                shared_payload["grocery_rollup"] = self._build_weekly_grocery_rollup(days=week_days)
            ui_blocks.append(
                {
                    "id": snapshot_id,
                    "block_type": "meal_plan_week" if is_multi_day_request else "meal_plan_draft",
                    "title": "Meal Plan",
                    "payload": shared_payload,
                }
            )

        if state.get("guardrail_report", {}).get("issues"):
            ui_blocks.append(
                {
                    "id": uuid4().hex,
                    "block_type": "planner_notice",
                    "title": "Guardrail review",
                    "payload": {
                        "message": "Some issues were detected while finalizing this turn.",
                        "issues": state["guardrail_report"]["issues"],
                    },
                }
            )

        if recorder is not None and ui_step_id is not None:
            recorder.complete_step(
                step_id=ui_step_id,
                step_key="planner.ui_response.build",
                parent_step_id=recorder.root_step_id,
                branch_key="ui",
                step_type="ui",
                output_data={
                    "ui_block_count": len(ui_blocks),
                    "target_slots": target_meal_types,
                    "view_mode": "week" if request_kind in {"week_plan_request", "multi_day_plan_request"} else "day",
                },
            )
        return {
            "ui_blocks": ui_blocks,
            "quick_actions": [],
        }

    def _resolve_presentation_slots(self, *, state: MealConversationGraphState) -> list[str]:
        declared_slots = [
            slot
            for slot in state.get("constraint_state", {}).get("target_meal_types", [])
            if slot in {item.value for item in MealType}
        ]
        if declared_slots:
            return declared_slots

        final_plan = dict(state.get("final_plan") or {})
        planned_slots: list[str] = []
        seen_slots: set[str] = set()
        for meal in final_plan.get("planned_meals") or []:
            slot = self._normalize_slot_name(meal.get("slot"))
            if slot and slot not in seen_slots:
                planned_slots.append(slot)
                seen_slots.add(slot)
        return planned_slots

    def _build_meal_plan_sections(
        self,
        *,
        state: MealConversationGraphState,
        target_meal_types: list[str],
    ) -> list[dict[str, Any]]:
        nutrition_assessments = dict(state.get("nutrition_assessments") or {})
        selected_meal_details = dict(state.get("selected_meal_details") or {})
        candidate_meals_by_slot = dict(state.get("candidate_meals_by_slot") or {})
        planned_meals_by_slot = {
            self._normalize_slot_name(item.get("slot")): dict(item)
            for item in list((state.get("final_plan") or {}).get("planned_meals") or [])
            if self._normalize_slot_name(item.get("slot"))
        }
        sections: list[dict[str, Any]] = []

        for slot in target_meal_types:
            detail = selected_meal_details.get(slot)
            planned_meal = planned_meals_by_slot.get(slot) or {}
            summary = (nutrition_assessments.get(slot) or {}).get("summary", {})
            items: list[dict[str, Any]] = []

            if detail:
                meal = detail["meal"]
                items.append(
                    {
                        "meal_id": meal.get("id"),
                        "name": self._candidate_display_name(meal),
                        "hero_image_url": meal.get("hero_image_url"),
                        "servings": meal.get("servings"),
                        "serving_text": self._serving_text(meal.get("servings")),
                        "calories": meal.get("nutrition_summary", {}).get("calories"),
                        "description": meal.get("description"),
                        "meal_source": "catalog",
                        "meal_detail": self._build_presentation_meal_detail(
                            slot=slot,
                            meal_source="catalog",
                            meal=meal,
                            grocery_items=[],
                        ),
                    }
                )
            elif planned_meal:
                items.append(
                    {
                        "meal_id": planned_meal.get("meal_id"),
                        "name": planned_meal.get("meal_name"),
                        "hero_image_url": None,
                        "servings": None,
                        "serving_text": None,
                        "calories": summary.get("calories"),
                        "description": None,
                        "meal_source": planned_meal.get("meal_source"),
                        "meal_detail": None,
                    }
                )
            elif candidate_meals_by_slot.get(slot):
                preview = candidate_meals_by_slot[slot][0]
                items.append(
                    {
                        "meal_id": preview.get("id"),
                        "name": self._candidate_display_name(preview),
                        "hero_image_url": preview.get("hero_image_url"),
                        "servings": preview.get("servings"),
                        "serving_text": self._serving_text(preview.get("servings")),
                        "calories": preview.get("nutrition_summary", {}).get("calories"),
                        "description": preview.get("description"),
                        "meal_source": "candidate",
                        "meal_detail": self._build_presentation_meal_detail(
                            slot=slot,
                            meal_source="catalog",
                            meal=preview,
                            grocery_items=[],
                        ),
                    }
                )

            sections.append(
                {
                    "slot": slot,
                    "title": slot.capitalize(),
                    "calories": summary.get("calories") or (items[0].get("calories") if items else None),
                    "items": items,
                }
            )

        return sections

    def _build_meal_plan_actions(
        self,
        *,
        state: MealConversationGraphState,
        target_meal_types: list[str],
        snapshot_id: str,
        saved: bool,
    ) -> dict[str, Any]:
        focus_meal_type = state.get("constraint_state", {}).get("meal_type")
        primary_action = None
        if not saved:
            primary_action = {
                "id": f"save-{snapshot_id}",
                "label": "Start Plan",
                "action_type": "save_meal_plan",
                "message": "Start Plan",
                "payload": {
                    "snapshot_id": snapshot_id,
                },
            }

        overflow_actions = [
            {
                "id": f"swap-{slot}-{snapshot_id}",
                "label": f"Swap {slot.capitalize()}",
                "action_type": "swap_meal",
                "message": f"Swap my {slot}.",
                "payload": {
                    "meal_type": slot,
                    "snapshot_id": snapshot_id,
                },
            }
            for slot in target_meal_types
        ]
        overflow_actions.extend(
            [
                {
                    "id": f"cheaper-{snapshot_id}",
                    "label": "Make cheaper",
                    "action_type": "make_cheaper",
                    "message": "Make it cheaper.",
                    "payload": {
                        "meal_type": focus_meal_type,
                        "meal_types": target_meal_types,
                        "snapshot_id": snapshot_id,
                    },
                },
                {
                    "id": f"protein-{snapshot_id}",
                    "label": "More protein",
                    "action_type": "more_protein",
                    "message": "I want more protein.",
                    "payload": {
                        "meal_type": focus_meal_type,
                        "meal_types": target_meal_types,
                        "snapshot_id": snapshot_id,
                    },
                },
            ]
        )
        return {
            "primary_action": primary_action,
            "overflow_actions": overflow_actions,
        }

    def _build_presentation_meal_detail(
        self,
        *,
        slot: str,
        meal_source: str,
        meal: dict[str, Any],
        grocery_items: list[dict[str, Any]],
        nutrition_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        description = str(meal.get("description") or "").strip()
        servings = self._normalized_float(meal.get("servings"))
        prep_time = self._normalized_int(meal.get("prep_time_minutes"))
        cook_time = self._normalized_int(meal.get("cook_time_minutes"))
        total_time = prep_time + cook_time
        nutrition = self._normalized_nutrition_summary(nutrition_override or meal.get("nutrition_summary") or {})
        estimated_cost = self._normalized_estimated_cost(meal, meal_source=meal_source)
        linked_products = self._normalized_linked_products(meal=meal, grocery_items=grocery_items)
        ingredients = self._normalized_ingredients(meal.get("ingredient_items") or [])
        steps = self._normalized_step_by_step(
            recipe_step_items=meal.get("recipe_step_items") or [],
            recipe_steps=meal.get("recipe_steps") or [],
        )
        return {
            "meal_id": meal.get("id"),
            "name": self._candidate_display_name(meal),
            "meal_type": meal.get("meal_type") or slot,
            "hero_image_url": meal.get("hero_image_url"),
            "description": description or f"Planned {slot} meal.",
            "servings": servings,
            "ingredients_scaled_for_servings": servings,
            "prep_time_minutes": prep_time,
            "cook_time_minutes": cook_time,
            "total_time_minutes": total_time,
            "difficulty": meal.get("difficulty"),
            "culture_tags": list(meal.get("culture_tags") or []),
            "diet_rules_supported": list(meal.get("diet_rules_supported") or []),
            "allergy_exclusions": list(meal.get("allergy_exclusions") or []),
            "estimated_cost": estimated_cost,
            "estimated_cost_gbp": self._estimated_cost_gbp(meal, estimated_cost=estimated_cost),
            "estimated_nutrition_per_serving": nutrition,
            "ingredients": ingredients,
            "step_by_step": steps,
            "quick_tips": self._build_quick_tips(
                servings=servings,
                total_time_minutes=total_time,
                estimated_cost=estimated_cost,
                culture_tags=list(meal.get("culture_tags") or []),
            ),
            "shopping_list_grouped": self._build_shopping_list_grouped(
                ingredients=ingredients,
                linked_products=linked_products,
            ),
            "linked_products": linked_products,
        }

    def _normalized_nutrition_summary(self, raw_summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "calories": self._normalized_int(raw_summary.get("calories")),
            "protein_g": self._normalized_float(raw_summary.get("protein_g")),
            "carbs_g": self._normalized_float(raw_summary.get("carbs_g")),
            "fat_g": self._normalized_float(raw_summary.get("fat_g")),
        }

    def _normalized_estimated_cost(
        self,
        meal: dict[str, Any],
        *,
        meal_source: str,
    ) -> dict[str, Any] | None:
        if meal_source == "catalog":
            resolved = dict(meal.get("estimated_cost") or {})
            if not resolved:
                estimated_costs = list(meal.get("estimated_costs") or [])
                resolved = (
                    next(
                        (
                            dict(cost)
                            for cost in estimated_costs
                            if str(cost.get("currency_code") or "").upper() == "GBP"
                            or str(cost.get("country_code") or "").upper() == "GB"
                        ),
                        dict(estimated_costs[0]) if estimated_costs else {},
                    )
                )
            if not resolved:
                return None
            amount = self._normalized_float(resolved.get("amount"))
            if amount is None:
                return None
            currency_code = str(resolved.get("currency_code") or "").upper() or None
            country_code = str(resolved.get("country_code") or "").upper() or None
            return {
                "country_code": country_code,
                "currency_code": currency_code,
                "amount": amount,
                "formatted_amount": self._format_currency(amount=amount, currency_code=currency_code),
            }

        estimated_costs = list(meal.get("estimated_costs") or [])
        preferred = next(
            (
                dict(cost)
                for cost in estimated_costs
                if str(cost.get("currency_code") or "").upper() == "GBP"
                or str(cost.get("country_code") or "").upper() == "GB"
            ),
            dict(estimated_costs[0]) if estimated_costs else {},
        )
        if not preferred:
            return None
        amount = self._normalized_float(preferred.get("amount"))
        if amount is None:
            return None
        currency_code = str(preferred.get("currency_code") or "").upper() or None
        country_code = str(preferred.get("country_code") or "").upper() or None
        return {
            "country_code": country_code,
            "currency_code": currency_code,
            "amount": amount,
            "formatted_amount": self._format_currency(amount=amount, currency_code=currency_code),
        }

    def _estimated_cost_gbp(
        self,
        meal: dict[str, Any],
        *,
        estimated_cost: dict[str, Any] | None,
    ) -> float | None:
        estimated_costs = list(meal.get("estimated_costs") or [])
        gbp_cost = next(
            (
                cost
                for cost in estimated_costs
                if str(cost.get("currency_code") or "").upper() == "GBP"
                or str(cost.get("country_code") or "").upper() == "GB"
            ),
            None,
        )
        if gbp_cost is not None:
            return self._normalized_float(gbp_cost.get("amount"))
        if estimated_cost and str(estimated_cost.get("currency_code") or "").upper() == "GBP":
            return self._normalized_float(estimated_cost.get("amount"))
        return None

    def _normalized_ingredients(self, raw_ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ingredients: list[dict[str, Any]] = []
        for index, ingredient in enumerate(raw_ingredients, start=1):
            quantity = self._normalized_float(ingredient.get("quantity"))
            unit = str(ingredient.get("unit") or "").strip()
            ingredients.append(
                {
                    "id": ingredient.get("id") or f"ingredient-{index}",
                    "name": str(ingredient.get("name") or "").strip(),
                    "quantity": quantity,
                    "unit": unit,
                    "quantity_label": self._quantity_label(quantity=quantity, unit=unit),
                    "base_quantity": self._normalized_float(ingredient.get("base_quantity")) or quantity,
                    "optional": bool(ingredient.get("optional", False)),
                    "linked_product_ids": list(ingredient.get("linked_product_ids") or []),
                    "measurement_type": ingredient.get("measurement_type"),
                    "unit_code": ingredient.get("unit_code"),
                    "canonical_quantity": self._normalized_float(ingredient.get("canonical_quantity")),
                    "canonical_unit": ingredient.get("canonical_unit"),
                    "conversion_profile_id": ingredient.get("conversion_profile_id"),
                    "scaling_behavior": ingredient.get("scaling_behavior"),
                    "rounding_rule": ingredient.get("rounding_rule"),
                    "scale_factor": self._normalized_float(ingredient.get("scale_factor")),
                }
            )
        return [ingredient for ingredient in ingredients if ingredient.get("name")]

    @staticmethod
    def _resolved_rounding_rule(value: Any) -> RoundingRule | None:
        if isinstance(value, RoundingRule):
            return value
        normalized = str(value or "").strip()
        if not normalized:
            return None
        try:
            return RoundingRule(normalized)
        except ValueError:
            return None

    def _scaled_ingredients(
        self,
        *,
        ingredients: list[dict[str, Any]],
        base_servings: float,
        target_servings: float,
    ) -> list[dict[str, Any]]:
        scale_factor = max(float(target_servings), 0.0) / max(float(base_servings), 1.0)
        scaled_ingredients: list[dict[str, Any]] = []
        for index, ingredient in enumerate(ingredients, start=1):
            quantity = self._normalized_float(
                ingredient.get("base_quantity")
                if ingredient.get("base_quantity") not in (None, "")
                else ingredient.get("quantity")
            )
            unit = str(ingredient.get("unit") or "").strip()
            scaled_quantity = (
                MealScalingService._apply_rounding_rule(
                    float(quantity) * scale_factor,
                    self._resolved_rounding_rule(ingredient.get("rounding_rule")),
                )
                if quantity is not None
                else None
            )
            canonical_base_quantity = self._normalized_float(ingredient.get("canonical_quantity"))
            canonical_quantity = (
                round(float(canonical_base_quantity) * scale_factor, 2)
                if canonical_base_quantity is not None
                else None
            )
            scaled_ingredients.append(
                {
                    "id": ingredient.get("id") or f"ingredient-{index}",
                    "name": str(ingredient.get("name") or "").strip(),
                    "quantity": scaled_quantity,
                    "unit": unit,
                    "quantity_label": self._quantity_label(quantity=scaled_quantity, unit=unit),
                    "base_quantity": quantity,
                    "optional": bool(ingredient.get("optional", False)),
                    "linked_product_ids": list(ingredient.get("linked_product_ids") or []),
                    "measurement_type": ingredient.get("measurement_type"),
                    "unit_code": ingredient.get("unit_code"),
                    "canonical_quantity": canonical_quantity,
                    "canonical_unit": ingredient.get("canonical_unit"),
                    "conversion_profile_id": ingredient.get("conversion_profile_id"),
                    "scaling_behavior": ingredient.get("scaling_behavior"),
                    "rounding_rule": ingredient.get("rounding_rule"),
                    "scale_factor": round(scale_factor, 4),
                }
            )
        return [ingredient for ingredient in scaled_ingredients if ingredient.get("name")]

    def _normalized_step_by_step(
        self,
        *,
        recipe_step_items: list[dict[str, Any]],
        recipe_steps: list[str],
    ) -> list[dict[str, Any]]:
        normalized_steps: list[dict[str, Any]] = []
        if recipe_step_items:
            for index, step in enumerate(recipe_step_items, start=1):
                instruction = str(step.get("instruction") or "").strip()
                if not instruction:
                    continue
                normalized_steps.append(
                    {
                        "step_number": index,
                        "instruction": instruction,
                        "ingredient_ids": list(step.get("ingredient_ids") or []),
                    }
                )
            return normalized_steps

        for index, instruction in enumerate(recipe_steps, start=1):
            text = str(instruction or "").strip()
            if not text:
                continue
            normalized_steps.append(
                {
                    "step_number": index,
                    "instruction": text,
                    "ingredient_ids": [],
                }
            )
        return normalized_steps

    def _normalized_linked_products(
        self,
        *,
        meal: dict[str, Any],
        grocery_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        linked_products = list(meal.get("linked_products") or [])
        if linked_products:
            normalized: list[dict[str, Any]] = []
            for product in linked_products:
                resolved_price = dict(product.get("resolved_price") or {})
                amount = self._normalized_float(resolved_price.get("amount"))
                currency_code = str(resolved_price.get("currency_code") or "").upper() or None
                normalized.append(
                    {
                        "id": product.get("id"),
                        "name": product.get("name"),
                        "image_url": product.get("img_url"),
                        "estimated_cost": {
                            "country_code": str(resolved_price.get("country_code") or "").upper() or None,
                            "currency_code": currency_code,
                            "amount": amount,
                            "formatted_amount": self._format_currency(amount=amount, currency_code=currency_code)
                            if amount is not None
                            else None,
                        }
                        if amount is not None
                        else None,
                    }
                )
            return normalized

        normalized = []
        for product in grocery_items:
            resolved_price = dict(product.get("resolved_price") or {})
            amount = self._normalized_float(resolved_price.get("amount"))
            currency_code = str(resolved_price.get("currency_code") or "").upper() or None
            normalized.append(
                {
                    "id": product.get("id"),
                    "name": product.get("name") or product.get("product"),
                    "image_url": product.get("img_url"),
                    "estimated_cost": {
                        "country_code": str(resolved_price.get("country_code") or "").upper() or None,
                        "currency_code": currency_code,
                        "amount": amount,
                        "formatted_amount": self._format_currency(amount=amount, currency_code=currency_code)
                        if amount is not None
                        else None,
                    }
                    if amount is not None
                    else None,
                }
            )
        return [product for product in normalized if product.get("name")]

    def _build_quick_tips(
        self,
        *,
        servings: float | None,
        total_time_minutes: int,
        estimated_cost: dict[str, Any] | None,
        culture_tags: list[str],
    ) -> list[str]:
        tips: list[str] = []
        if total_time_minutes > 0:
            tips.append(f"Set aside about {total_time_minutes} minutes from prep to finish.")
        if servings not in (None, 0):
            serving_text = self._serving_text(servings)
            if serving_text:
                tips.append(f"This draft is portioned for {serving_text}.")
        if estimated_cost and estimated_cost.get("formatted_amount"):
            tips.append(f"Estimated ingredient spend is about {estimated_cost['formatted_amount']}.")
        if culture_tags:
            primary_tag = str(culture_tags[0]).replace("_", " ").strip()
            if primary_tag:
                tips.append(f"Built to reflect a {primary_tag.lower()} flavor profile.")
        return tips[:3]

    def _build_shopping_list_grouped(
        self,
        *,
        ingredients: list[dict[str, Any]],
        linked_products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: list[dict[str, Any]] = []
        products_by_id = {
            str(product.get("id") or ""): product
            for product in linked_products
            if str(product.get("id") or "").strip()
        }
        if ingredients:
            ingredient_items: list[dict[str, Any]] = []
            for ingredient in ingredients:
                image_url = None
                for product_id in list(ingredient.get("linked_product_ids") or []):
                    linked_product = products_by_id.get(str(product_id))
                    if linked_product is None:
                        continue
                    image_url = linked_product.get("image_url") or linked_product.get("img_url")
                    if image_url:
                        break
                ingredient_items.append(
                    {
                        "id": ingredient.get("id"),
                        "name": ingredient.get("name"),
                        "subtitle": ingredient.get("quantity_label"),
                        "optional": ingredient.get("optional", False),
                        "image_url": image_url,
                    }
                )
            grouped.append(
                {
                    "title": "Ingredients",
                    "items": ingredient_items,
                }
            )
        if linked_products:
            grouped.append(
                {
                    "title": "Shop items",
                    "items": [
                        {
                            "id": product.get("id"),
                            "name": product.get("name"),
                            "subtitle": ((product.get("estimated_cost") or {}).get("formatted_amount")),
                            "optional": False,
                            "image_url": product.get("image_url") or product.get("img_url"),
                        }
                        for product in linked_products
                    ],
                }
            )
        return grouped

    @staticmethod
    def _normalized_int(value: Any) -> int:
        try:
            return int(round(float(value or 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalized_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _quantity_label(cls, *, quantity: float | None, unit: str) -> str | None:
        if quantity is None and not unit:
            return None
        quantity_text = ""
        if quantity is not None:
            if float(quantity).is_integer():
                quantity_text = str(int(quantity))
            else:
                quantity_text = f"{quantity:.1f}".rstrip("0").rstrip(".")
        parts = [part for part in [quantity_text, unit] if part]
        return " ".join(parts) or None

    @staticmethod
    def _format_currency(*, amount: float | None, currency_code: str | None) -> str | None:
        if amount is None:
            return None
        if currency_code == "GBP":
            return f"£{amount:.2f}"
        if currency_code:
            return f"{currency_code} {amount:.2f}"
        return f"{amount:.2f}"

    def _build_week_plan_days(
        self,
        *,
        state: MealConversationGraphState,
        sections: list[dict[str, Any]],
        totals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recorder = self._monitoring_recorder(state)
        week_step_id = (
            recorder.start_step(
                step_key="planner.week.expansion",
                parent_step_id=recorder.root_step_id,
                branch_key="week",
                step_type="expansion",
            )
            if recorder is not None
            else None
        )
        effective_start_date = self._effective_start_date(state)
        request_kind = str(state.get("constraint_state", {}).get("request_kind") or "week_plan_request").strip()
        selected_date_set = self._selected_planning_dates(state)
        selected_date_list = sorted(selected_date_set)
        is_multi_day_request = request_kind == "multi_day_plan_request"
        if is_multi_day_request and selected_date_list:
            iteration_dates = selected_date_list
            period_start = selected_date_list[0]
            period_end = selected_date_list[-1]
        else:
            week_start, week_end = self._week_bounds(effective_start_date)
            iteration_dates = [
                week_start + timedelta(days=offset)
                for offset in range((week_end - week_start).days + 1)
            ]
            period_start = week_start
            period_end = week_end
        today = self._run_context_timestamp(state).date()
        requested_slots = self._resolve_presentation_slots(state=state)
        household_size = max(
            self._normalized_positive_int((state.get("user_context") or {}).get("household_size"))
            or self._normalized_positive_int((state.get("constraint_state") or {}).get("household_size"))
            or 1,
            1,
        )
        section_titles = {
            str(section.get("slot") or "").strip().lower(): str(section.get("title") or "").strip()
            for section in sections
            if str(section.get("slot") or "").strip()
        }
        anchor_sources = self._build_weekly_anchor_sources(
            state=state,
            requested_slots=requested_slots,
            fallback_sections=sections,
        )
        days: list[dict[str, Any]] = []
        previous_fresh_batches: dict[str, str] = {}
        previous_fresh_items: dict[str, dict[str, Any]] = {}
        generated_lookup = {item: index for index, item in enumerate(selected_date_list)}

        for day_index, current_date in enumerate(iteration_dates):
            day_step_id = (
                recorder.start_step(
                    step_key="planner.week.day",
                    parent_step_id=week_step_id or recorder.root_step_id,
                    branch_key=current_date.isoformat(),
                    step_type="day",
                    input_data={"date": current_date.isoformat()},
                )
                if recorder is not None
                else None
            )
            is_today = current_date == today
            is_generated_day = current_date in selected_date_set or is_multi_day_request
            day_sections: list[dict[str, Any]] = []

            if is_generated_day:
                generated_day_index = generated_lookup.get(
                    current_date,
                    max((current_date - effective_start_date).days, 0),
                )
                use_leftovers = generated_day_index % 2 == 1
                anchor_index = min(generated_day_index // 2, max(len(anchor_sources) - 1, 0))
                source_index = min(anchor_index + (1 if use_leftovers else 0), max(len(anchor_sources) - 1, 0))
                day_source_items = anchor_sources[source_index] if anchor_sources else {}

                for item_index, slot in enumerate(requested_slots, start=1):
                    base_item = dict(day_source_items.get(slot) or {})
                    normalized_items: list[dict[str, Any]] = []
                    section_calories = 0

                    if use_leftovers and slot in {"lunch", "dinner"} and previous_fresh_items.get(slot):
                        normalized_item = self._build_weekly_item_variant(
                            item=previous_fresh_items[slot],
                            slot=slot,
                            current_date=current_date,
                            use_leftovers=True,
                            previous_fresh_batch_id=previous_fresh_batches.get(slot),
                            item_index=item_index,
                            household_size=household_size,
                        )
                        normalized_items.append(normalized_item)
                        section_calories += self._normalized_int(normalized_item.get("calories"))
                    elif base_item:
                        normalized_item = self._build_weekly_item_variant(
                            item=base_item,
                            slot=slot,
                            current_date=current_date,
                            use_leftovers=False,
                            previous_fresh_batch_id=None,
                            item_index=item_index,
                            household_size=household_size,
                        )
                        normalized_items.append(normalized_item)
                        section_calories += self._normalized_int(normalized_item.get("calories"))

                        batch_id = str(normalized_item.get("batch_id") or "").strip()
                        if batch_id and str(normalized_item.get("source_type") or "") == "fresh":
                            previous_fresh_batches[slot] = batch_id
                            previous_fresh_items[slot] = dict(base_item)

                    day_sections.append(
                        {
                            "slot": slot,
                            "title": section_titles.get(slot) or slot.capitalize(),
                            "calories": section_calories,
                            "items": normalized_items,
                        }
                    )
            else:
                for slot in requested_slots:
                    day_sections.append(
                        {
                            "slot": slot,
                            "title": section_titles.get(slot) or slot.capitalize(),
                            "calories": 0,
                            "items": [],
                        }
                    )

            day_totals = self._compute_section_totals(day_sections)
            if recorder is not None and day_step_id is not None:
                recorder.complete_step(
                    step_id=day_step_id,
                    step_key="planner.week.day",
                    parent_step_id=week_step_id or recorder.root_step_id,
                    branch_key=current_date.isoformat(),
                    step_type="day",
                    output_data={
                        "generated": is_generated_day,
                        "section_count": len(day_sections),
                        "calories": int(day_totals.get("calories") or 0),
                    },
                )
            days.append(
                {
                    "id": f"day-{day_index}",
                    "date": current_date.isoformat(),
                    "monitor_step_id": day_step_id,
                    "accent_label": "Today" if is_today else current_date.strftime("%A"),
                    "full_label": (
                        f"Today, {current_date.strftime('%B %d')}"
                        if is_today
                        else current_date.strftime("%A, %B %d")
                    ),
                    "calories": int(day_totals.get("calories") or 0),
                    "expanded": current_date == effective_start_date or day_index == 0,
                    "sections": day_sections,
                    "totals": day_totals,
                    "tracked_text": (
                        f"Tracked 0/{len(day_sections)} meals"
                        if is_generated_day
                        else "No meals planned yet"
                    ),
                }
            )

        if recorder is not None and week_step_id is not None:
            recorder.complete_step(
                step_id=week_step_id,
                step_key="planner.week.expansion",
                parent_step_id=recorder.root_step_id,
                branch_key="week",
                step_type="expansion",
                output_data={
                    "day_count": len(days),
                    "week_start": period_start.isoformat(),
                    "week_end": period_end.isoformat(),
                    "effective_start_date": effective_start_date.isoformat(),
                    "selected_dates": sorted(item.isoformat() for item in selected_date_set),
                },
            )
        return days

    def _build_weekly_anchor_sources(
        self,
        *,
        state: MealConversationGraphState,
        requested_slots: list[str],
        fallback_sections: list[dict[str, Any]],
    ) -> list[dict[str, dict[str, Any]]]:
        if not requested_slots:
            return []

        fallback_items = {
            str(section.get("slot") or "").strip().lower(): dict((section.get("items") or [None])[0] or {})
            for section in fallback_sections
            if str(section.get("slot") or "").strip() and list(section.get("items") or [])
        }
        candidate_meals_by_slot = dict(state.get("candidate_meals_by_slot") or {})
        ranked_bundles = list(state.get("ranked_bundles") or [])
        anchor_sources: list[dict[str, dict[str, Any]]] = []

        first_anchor: dict[str, dict[str, Any]] = {}
        for slot in requested_slots:
            fallback_item = dict(fallback_items.get(slot) or {})
            if fallback_item:
                first_anchor[slot] = fallback_item
                continue
            rotated_item = self._build_weekly_rotated_section_item(
                slot=slot,
                rotation_step=0,
                candidate_meals_by_slot=candidate_meals_by_slot,
            )
            if rotated_item:
                first_anchor[slot] = rotated_item
        anchor_sources.append(first_anchor)

        for anchor_offset in range(1, 4):
            bundle = ranked_bundles[(anchor_offset - 1) % len(ranked_bundles)] if ranked_bundles else None
            bundle_meals_by_slot = dict(bundle.get("meals_by_slot") or {}) if isinstance(bundle, dict) else {}
            anchor_payload: dict[str, dict[str, Any]] = {}
            for slot in requested_slots:
                meal_payload = dict(bundle_meals_by_slot.get(slot) or {})
                if meal_payload:
                    anchor_payload[slot] = self._build_weekly_section_item_from_candidate(
                        slot=slot,
                        meal=meal_payload,
                    )
                    continue
                rotated_item = self._build_weekly_rotated_section_item(
                    slot=slot,
                    rotation_step=anchor_offset,
                    candidate_meals_by_slot=candidate_meals_by_slot,
                )
                if rotated_item:
                    anchor_payload[slot] = rotated_item
                elif fallback_items.get(slot):
                    anchor_payload[slot] = dict(fallback_items[slot])
            anchor_sources.append(anchor_payload)

        return anchor_sources

    def _build_weekly_rotated_section_item(
        self,
        *,
        slot: str,
        rotation_step: int,
        candidate_meals_by_slot: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        candidates = list(candidate_meals_by_slot.get(slot) or [])
        if not candidates:
            return {}
        candidate_index = self._weekly_rotation_index(rotation_step=rotation_step, candidate_count=len(candidates))
        return self._build_weekly_section_item_from_candidate(
            slot=slot,
            meal=dict(candidates[candidate_index]),
        )

    def _build_weekly_section_item_from_candidate(
        self,
        *,
        slot: str,
        meal: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "meal_id": meal.get("id"),
            "name": self._candidate_display_name(meal),
            "hero_image_url": meal.get("hero_image_url"),
            "servings": meal.get("servings"),
            "serving_text": self._serving_text(meal.get("servings")),
            "calories": meal.get("nutrition_summary", {}).get("calories"),
            "description": meal.get("description"),
            "meal_source": "catalog",
            "meal_detail": self._build_presentation_meal_detail(
                slot=slot,
                meal_source="catalog",
                meal=meal,
                grocery_items=[],
            ),
        }

    @staticmethod
    def _weekly_rotation_index(*, rotation_step: int, candidate_count: int) -> int:
        if candidate_count <= 1:
            return 0
        rotation_pattern = [0, 1, 0, 2, 0, 1, 2]
        return min(rotation_pattern[rotation_step % len(rotation_pattern)], candidate_count - 1)

    def _build_weekly_item_variant(
        self,
        *,
        item: dict[str, Any],
        slot: str,
        current_date: date,
        use_leftovers: bool,
        previous_fresh_batch_id: str | None,
        item_index: int,
        household_size: int,
    ) -> dict[str, Any]:
        normalized = dict(item)
        meal_detail = dict(normalized.get("meal_detail") or {})
        source_type = "fresh"
        batch_id = None
        origin_batch_id = None
        storage_type = None
        safe_until = None
        consumed_servings = float(max(household_size, 1))
        yield_servings = consumed_servings

        if slot in {"lunch", "dinner"} and use_leftovers and previous_fresh_batch_id:
            source_type = "leftover"
            origin_batch_id = previous_fresh_batch_id
            storage_type = "refrigerated"
            safe_until = (current_date + timedelta(days=1)).isoformat()
        elif slot in {"lunch", "dinner"}:
            batch_id = f"batch-{slot}-{current_date.isoformat()}-{item_index}"
            storage_type = "refrigerated"
            safe_until = (current_date + timedelta(days=2)).isoformat()
            yield_servings = consumed_servings * 2.0

        estimated_cost_gbp = self._normalized_float(
            meal_detail.get("estimated_cost_gbp")
            or normalized.get("estimated_cost_gbp")
        )
        allocated_cost_gbp = estimated_cost_gbp
        if estimated_cost_gbp is not None and slot in {"lunch", "dinner"}:
            allocated_cost_gbp = round(estimated_cost_gbp / 2.0, 2)

        if meal_detail:
            base_servings = self._normalized_float(meal_detail.get("servings")) or 1.0
            scaled_ingredients = self._scaled_ingredients(
                ingredients=list(meal_detail.get("ingredients") or []),
                base_servings=base_servings,
                target_servings=yield_servings,
            )
            meal_detail["estimated_cost_gbp"] = allocated_cost_gbp
            estimated_cost = dict(meal_detail.get("estimated_cost") or {})
            if allocated_cost_gbp is not None:
                estimated_cost["amount"] = allocated_cost_gbp
                estimated_cost["formatted_amount"] = self._format_currency(
                    amount=allocated_cost_gbp,
                    currency_code=str(estimated_cost.get("currency_code") or "GBP").upper(),
                )
                if not estimated_cost.get("currency_code"):
                    estimated_cost["currency_code"] = "GBP"
                meal_detail["estimated_cost"] = estimated_cost
            meal_detail["planned_servings"] = consumed_servings
            meal_detail["yield_servings"] = yield_servings
            meal_detail["consumed_servings"] = consumed_servings
            meal_detail["ingredients"] = scaled_ingredients
            meal_detail["ingredients_scaled_for_servings"] = yield_servings
            meal_detail["source_type"] = source_type
            meal_detail["batch_id"] = batch_id
            meal_detail["origin_batch_id"] = origin_batch_id
            meal_detail["storage_type"] = storage_type
            meal_detail["safe_until"] = safe_until
            meal_detail["shopping_list_grouped"] = self._build_shopping_list_grouped(
                ingredients=scaled_ingredients,
                linked_products=list(meal_detail.get("linked_products") or []),
            )
            normalized["meal_detail"] = meal_detail

        normalized["source_type"] = source_type
        normalized["planned_servings"] = consumed_servings
        normalized["yield_servings"] = yield_servings
        normalized["consumed_servings"] = consumed_servings
        normalized["batch_id"] = batch_id
        normalized["origin_batch_id"] = origin_batch_id
        normalized["storage_type"] = storage_type
        normalized["safe_until"] = safe_until
        normalized["estimated_cost_gbp"] = allocated_cost_gbp
        return normalized

    def _build_weekly_day_snapshots(
        self,
        *,
        state: MealConversationGraphState,
        days: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for day in days:
            sections = list(day.get("sections") or [])
            snapshots.append(
                {
                    "snapshot_id": f"{day.get('id')}-snapshot",
                    "effective_date": day.get("date"),
                    "title": "Meal Plan",
                    "view_mode": "day",
                    "state": "draft",
                    "tracked_text": day.get("tracked_text") or f"Tracked 0/{len(sections)} meals",
                    "totals": dict(day.get("totals") or self._compute_section_totals(sections)),
                    "sections": sections,
                    "days": [],
                    "planned_meals": self._build_planned_meals_from_sections(sections),
                    "source": "weekly_plan",
                    "parent_day_id": day.get("id"),
                }
            )
        return snapshots

    def _build_weekly_batch_groups(self, *, days: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for day in days:
            for section in list(day.get("sections") or []):
                slot = str(section.get("slot") or "")
                for item in list(section.get("items") or []):
                    batch_id = str(item.get("batch_id") or "").strip()
                    if not batch_id:
                        continue
                    groups.append(
                        {
                            "batch_id": batch_id,
                            "slot": slot,
                            "origin_date": day.get("date"),
                            "meal_name": item.get("name"),
                            "yield_servings": item.get("yield_servings"),
                            "consumed_servings": item.get("consumed_servings"),
                            "remaining_servings": max(
                                float(item.get("yield_servings") or 0)
                                - float(item.get("consumed_servings") or 0),
                                0.0,
                            ),
                            "storage_type": item.get("storage_type"),
                            "safe_until": item.get("safe_until"),
                        }
                    )
        return groups

    def _build_weekly_leftover_links(self, *, days: list[dict[str, Any]]) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        for day in days:
            for section in list(day.get("sections") or []):
                for item in list(section.get("items") or []):
                    origin_batch_id = str(item.get("origin_batch_id") or "").strip()
                    if not origin_batch_id:
                        continue
                    links.append(
                        {
                            "origin_batch_id": origin_batch_id,
                            "target_date": day.get("date"),
                            "target_slot": section.get("slot"),
                            "meal_name": item.get("name"),
                            "consumed_servings": item.get("consumed_servings"),
                        }
                    )
        return links

    def _build_weekly_grocery_rollup(self, *, days: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        items: list[dict[str, Any]] = []
        for day in days:
            for section in list(day.get("sections") or []):
                for item in list(section.get("items") or []):
                    meal_detail = dict(item.get("meal_detail") or {})
                    for group in list(meal_detail.get("shopping_list_grouped") or []):
                        group_title = str(group.get("title") or "Items")
                        for group_item in list(group.get("items") or []):
                            key = (group_title, str(group_item.get("name") or ""))
                            if not key[1] or key in seen:
                                continue
                            seen.add(key)
                            items.append(
                                {
                                    "group": group_title,
                                    "name": group_item.get("name"),
                                    "subtitle": group_item.get("subtitle"),
                                    "optional": bool(group_item.get("optional", False)),
                                    "image_url": group_item.get("image_url"),
                                }
                            )
        return items

    def _build_planned_meals_from_sections(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        planned_meals: list[dict[str, Any]] = []
        for section in sections:
            slot = str(section.get("slot") or "").strip().lower()
            for item in list(section.get("items") or []):
                meal_name = str(item.get("name") or "").strip()
                if not meal_name:
                    continue
                planned_meals.append(
                    {
                        "slot": slot,
                        "meal_id": item.get("meal_id"),
                        "meal_name": meal_name,
                        "meal_source": item.get("meal_source"),
                        "created_meal_draft": None,
                        "source_type": item.get("source_type"),
                        "batch_id": item.get("batch_id"),
                        "origin_batch_id": item.get("origin_batch_id"),
                    }
                )
        return planned_meals

    def _compute_section_totals(self, sections: list[dict[str, Any]]) -> dict[str, Any]:
        totals = {
            "calories": 0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
        }
        for section in sections:
            totals["calories"] += self._normalized_int(section.get("calories"))
            for item in list(section.get("items") or []):
                meal_detail = dict(item.get("meal_detail") or {})
                nutrition = dict(meal_detail.get("estimated_nutrition_per_serving") or {})
                totals["protein_g"] += float(nutrition.get("protein_g") or 0)
                totals["carbs_g"] += float(nutrition.get("carbs_g") or 0)
                totals["fat_g"] += float(nutrition.get("fat_g") or 0)
        return {
            "calories": int(totals["calories"]),
            "protein_g": round(totals["protein_g"], 1),
            "carbs_g": round(totals["carbs_g"], 1),
            "fat_g": round(totals["fat_g"], 1),
        }

    def _week_period_label(self, state: MealConversationGraphState) -> str:
        week_start, week_end = self._week_bounds(self._effective_start_date(state))
        if week_start.month == week_end.month:
            return f"{week_start.strftime('%b %d')} - {week_end.strftime('%d')}"
        return f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}"

    def _period_label(
        self,
        *,
        state: MealConversationGraphState,
        days: list[dict[str, Any]],
        request_kind: str,
    ) -> str:
        if request_kind == "week_plan_request":
            return self._week_period_label(state)
        period_start = self._multi_day_period_start(state=state, days=days)
        period_end = self._multi_day_period_end(state=state, days=days)
        if period_start == period_end:
            return period_start.strftime("%b %d")
        if period_start.month == period_end.month:
            return f"{period_start.strftime('%b %d')} - {period_end.strftime('%d')}"
        return f"{period_start.strftime('%b %d')} - {period_end.strftime('%b %d')}"

    @staticmethod
    def _resolved_effective_date(action_payload: dict[str, Any]) -> str | None:
        raw = str(action_payload.get("effective_date") or "").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _resolved_selected_dates(action_payload: dict[str, Any]) -> list[str]:
        selected_dates: list[str] = []
        for item in list(action_payload.get("selected_dates") or []):
            try:
                normalized = date.fromisoformat(str(item).strip()).isoformat()
            except ValueError:
                continue
            if normalized not in selected_dates:
                selected_dates.append(normalized)
        selected_dates.sort()
        return selected_dates

    def _effective_start_date(self, state: MealConversationGraphState) -> date:
        raw = str(state.get("constraint_state", {}).get("effective_date") or "").strip()
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
        return self._run_context_timestamp(state).date()

    def _selected_planning_dates(self, state: MealConversationGraphState) -> set[date]:
        effective_start_date = self._effective_start_date(state)
        request_kind = str(state.get("constraint_state", {}).get("request_kind") or "week_plan_request").strip()
        selected_dates: set[date] = set()
        for raw in list(state.get("constraint_state", {}).get("selected_dates") or []):
            try:
                value = date.fromisoformat(str(raw).strip())
            except ValueError:
                continue
            if value < effective_start_date:
                continue
            if request_kind == "week_plan_request":
                _, week_end = self._week_bounds(effective_start_date)
                if value > week_end:
                    continue
            selected_dates.add(value)
        if selected_dates:
            return selected_dates
        if request_kind == "multi_day_plan_request":
            return {effective_start_date}
        _, week_end = self._week_bounds(effective_start_date)
        return {
            effective_start_date + timedelta(days=offset)
            for offset in range((week_end - effective_start_date).days + 1)
        }

    def _multi_day_period_start(
        self,
        *,
        state: MealConversationGraphState,
        days: list[dict[str, Any]],
    ) -> date:
        if days:
            try:
                return min(date.fromisoformat(str(day.get("date") or "")) for day in days)
            except ValueError:
                pass
        selected_dates = sorted(self._selected_planning_dates(state))
        if selected_dates:
            return selected_dates[0]
        return self._effective_start_date(state)

    def _multi_day_period_end(
        self,
        *,
        state: MealConversationGraphState,
        days: list[dict[str, Any]],
    ) -> date:
        if days:
            try:
                return max(date.fromisoformat(str(day.get("date") or "")) for day in days)
            except ValueError:
                pass
        selected_dates = sorted(self._selected_planning_dates(state))
        if selected_dates:
            return selected_dates[-1]
        return self._effective_start_date(state)

    @staticmethod
    def _week_bounds(value: date) -> tuple[date, date]:
        week_start = value - timedelta(days=value.weekday())
        return week_start, week_start + timedelta(days=6)

    @staticmethod
    def _serving_text(servings: Any) -> str | None:
        if servings in (None, "", 0):
            return None
        try:
            numeric = float(servings)
        except (TypeError, ValueError):
            return None
        if numeric.is_integer():
            whole = int(numeric)
            return f"{whole} {'serving' if whole == 1 else 'servings'}"
        return f"{numeric:.1f} servings"

    @staticmethod
    def _run_context_timestamp(state: MealConversationGraphState) -> datetime:
        raw = str(state.get("run_context", {}).get("timestamp") or "")
        if raw:
            normalized = raw.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)

    def _finalize_turn(self, state: MealConversationGraphState) -> dict[str, Any]:
        final_plan = dict(state.get("final_plan") or {})
        if not final_plan:
            return {
                "final_plan": self._clarification_response(
                    issue="final_plan_missing",
                    assistant_text="I couldn’t finalize the meal plan yet. Please resend the request with meal candidates.",
                    rationale="No final plan was produced before finalization.",
                )
            }
        logger.info(
            "planner.graph.finalize_turn trace_id=%s turn_id=%s turn_mode=%s planned_meals=%s ui_blocks=%s",
            self._trace_id(state),
            self._turn_id(state),
            final_plan.get("turn_mode"),
            len(final_plan.get("planned_meals") or []),
            len(state.get("ui_blocks") or []),
        )
        return {}

    @staticmethod
    def _turn_id(state: MealConversationGraphState) -> str:
        return str(state.get("run_context", {}).get("turn_id") or "-")

    @staticmethod
    def _trace_id(state: MealConversationGraphState) -> str:
        return str(state.get("run_context", {}).get("trace_id") or "-")

    @staticmethod
    def _monitoring_recorder(state: MealConversationGraphState) -> Any | None:
        return state.get("monitoring_recorder")

    @staticmethod
    def _text_preview(text: str | None, limit: int = 140) -> str:
        normalized = (text or "").replace("\n", " ").strip()
        if len(normalized) <= limit:
            return normalized or "-"
        return normalized[:limit] + "..."

    @staticmethod
    def _json_string(value: Any) -> str:
        try:
            return json.dumps(value, default=str, sort_keys=True)
        except Exception:
            return str(value)

    @classmethod
    def _message_payload(cls, message: Any) -> str:
        if hasattr(message, "model_dump"):
            try:
                return cls._json_string(message.model_dump(exclude_none=True))
            except Exception:
                pass
        return cls._json_string(message)

    @classmethod
    def _llm_request_payload(cls, *, model: Any, messages: list[Any]) -> dict[str, Any]:
        request_builder = getattr(model, "_get_request_payload", None)
        if callable(request_builder):
            try:
                payload = request_builder(messages)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                logger.exception("Failed to build meal planner LLM request payload for logging.")
        return {
            "messages": [
                message.model_dump(exclude_none=True)
                if hasattr(message, "model_dump")
                else str(message)
                for message in messages
            ],
        }

    def _unsupported_domain_response(self, state: MealConversationGraphState) -> dict[str, Any]:
        return {
            "turn_mode": "conversation_reply",
            "assistant_text": "I can only handle meal-planning selections in this planner.",
            "planned_meals": [],
            "requested_culture": None,
            "rationale": "The request was routed outside the meal-planning domain.",
            "totals": {},
        }

    @staticmethod
    def _compute_totals(state: MealConversationGraphState) -> dict[str, Any]:
        nutrition_assessments = dict(state.get("nutrition_assessments") or {})
        totals = {
            "calories": 0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
        }
        for assessment in nutrition_assessments.values():
            summary = assessment.get("summary") or {}
            totals["calories"] += int(summary.get("calories") or 0)
            totals["protein_g"] += float(summary.get("protein_g") or 0)
            totals["carbs_g"] += float(summary.get("carbs_g") or 0)
            totals["fat_g"] += float(summary.get("fat_g") or 0)
        return {
            "calories": int(totals["calories"]),
            "protein_g": round(totals["protein_g"], 1),
            "carbs_g": round(totals["carbs_g"], 1),
            "fat_g": round(totals["fat_g"], 1),
        }

    def _generation_failed_response(
        self,
        state: MealConversationGraphState,
        *,
        issue: str,
        rationale: str,
        assistant_text: str,
    ) -> dict[str, Any]:
        return {
            "turn_mode": "conversation_reply",
            "assistant_text": assistant_text,
            "planned_meals": [],
            "requested_culture": state.get("constraint_state", {}).get("requested_culture"),
            "rationale": rationale,
            "issue": issue,
            "totals": {},
        }

    def _clarification_response(
        self,
        *,
        issue: str,
        assistant_text: str,
        rationale: str,
    ) -> dict[str, Any]:
        return {
            "turn_mode": "clarification_request",
            "assistant_text": assistant_text,
            "planned_meals": [],
            "requested_culture": None,
            "rationale": rationale,
            "issue": issue,
            "totals": {},
        }

    def _failed_state(
        self,
        state: MealConversationGraphState,
        *,
        assistant_text: str,
        rationale: str,
        issue: str,
    ) -> MealConversationGraphState:
        failed = dict(state)
        final_plan = self._generation_failed_response(
            state,
            issue=issue,
            rationale=rationale,
            assistant_text=assistant_text,
        )
        failed["llm_parsed"] = final_plan
        failed["final_plan"] = final_plan
        failed["guardrail_report"] = {"passed": True, "issues": []}
        failed["ui_blocks"] = []
        failed["quick_actions"] = []
        failed["llm_metrics"] = dict(failed.get("llm_metrics") or {})
        return failed

    @staticmethod
    def _json_ai_message(payload: dict[str, Any]):
        if AIMessage is None:
            raise RuntimeError("AIMessage is unavailable for meal planner responses.")
        return AIMessage(content=json.dumps(payload), tool_calls=[])

    def _parse_final_plan_from_messages(self, state: MealConversationGraphState) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        if not messages or AIMessage is None:
            return None

        for message in reversed(messages):
            if not isinstance(message, AIMessage):
                continue
            parsed = self._parse_final_plan_text(self._extract_text_content(message))
            if parsed is not None:
                return parsed
            break
        return None

    @staticmethod
    def _parse_final_plan_text(content: str | None) -> dict[str, Any] | None:
        if not content:
            return None

        candidate = content.strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(parsed, dict):
            return None

        planned_meals = list(parsed.get("planned_meals") or [])
        turn_mode = str(parsed.get("turn_mode") or "").strip()
        if not turn_mode:
            turn_mode = "day_plan_generated" if planned_meals else "conversation_reply"
        return {
            "turn_mode": turn_mode,
            "assistant_text": str(parsed.get("assistant_text") or "I found some meal options for you."),
            "rationale": str(parsed.get("rationale") or ""),
            "requested_culture": parsed.get("requested_culture"),
            "planned_meals": planned_meals,
            "totals": dict(parsed.get("totals") or {}),
            "issue": parsed.get("issue"),
            "selected_bundle_id": str(parsed.get("selected_bundle_id") or "").strip() or None,
        }

    @staticmethod
    def _extract_text_content(message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(part for part in parts if part)
        return str(content)

    @staticmethod
    def _history_to_messages(history: list[dict[str, Any]]) -> list[Any]:
        if HumanMessage is None or AIMessage is None:
            return []

        messages: list[Any] = []
        for item in history[-12:]:
            role = str(item.get("role"))
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            if role == "user":
                messages.append(HumanMessage(content=text))
            elif role == "assistant":
                messages.append(AIMessage(content=text))
        return messages

    @staticmethod
    def _merge_state(state: MealConversationGraphState, updates: dict[str, Any]) -> None:
        if not updates:
            return
        for key, value in updates.items():
            if key == "messages":
                state["messages"] = [*(state.get("messages") or []), *list(value or [])]
                continue
            state[key] = value

    @staticmethod
    def _to_turn_result(state: MealConversationGraphState) -> MealConversationTurnResult:
        final_plan = state.get("final_plan") or {}
        run_context = state.get("run_context") or {}
        planned_meals = list(final_plan.get("planned_meals") or [])
        primary_meal = planned_meals[0] if planned_meals else {}
        resolved_meal_type = run_context.get("meal_type")
        resolved_country = run_context.get("country_code")
        return MealConversationTurnResult(
            assistant_text=str(final_plan.get("assistant_text") or "I found some meal options for you."),
            turn_mode=str(final_plan.get("turn_mode") or "conversation_reply"),
            agent_type=str(state.get("agent_type") or MEAL_PLANNER_AGENT_TYPE),
            target_domain=str(state.get("constraint_state", {}).get("target_domain") or MEAL_PLANNING_DOMAIN),
            meal_type=MealType(str(resolved_meal_type)) if resolved_meal_type else None,
            country_code=CountryCode(str(resolved_country)) if resolved_country else None,
            planned_meals=planned_meals,
            selected_meal_id=primary_meal.get("meal_id"),
            selected_meal_name=primary_meal.get("meal_name"),
            meal_source=primary_meal.get("meal_source"),
            requested_culture=final_plan.get("requested_culture") or state.get("constraint_state", {}).get("requested_culture"),
            last_user_intent=state.get("latest_user_intent"),
            ui_blocks=list(state.get("ui_blocks") or []),
            quick_actions=list(state.get("quick_actions") or []),
            metadata={
                "request_kind": state.get("constraint_state", {}).get("request_kind"),
                "target_domain": state.get("constraint_state", {}).get("target_domain"),
                "issue": final_plan.get("issue"),
                "selected_bundle_id": final_plan.get("selected_bundle_id"),
                "rationale": final_plan.get("rationale"),
                "tool_trace": [],
                "llm_metrics": dict(state.get("llm_metrics") or {}),
                "guardrail_report": dict(state.get("guardrail_report") or {}),
                "selected_meal_details": dict(state.get("selected_meal_details") or {}),
                "created_meal_drafts": dict(state.get("created_meal_drafts") or {}),
                "nutrition_assessments": dict(state.get("nutrition_assessments") or {}),
                "budget_assessments": dict(state.get("budget_assessments") or {}),
                "grocery_matches_by_slot": dict(state.get("grocery_matches_by_slot") or {}),
                "monitoring": dict((state.get("action_payload") or {}).get("monitoring") or {}),
            },
        )

    @staticmethod
    def _normalize_slot_name(value: Any) -> str | None:
        normalized = str(value or "").strip().lower()
        valid_slots = {item.value for item in MealType}
        return normalized if normalized in valid_slots else None

    @classmethod
    def _normalize_slot_candidates(cls, action_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        normalized: dict[str, list[dict[str, Any]]] = {}
        for slot, payload_key in REQUESTED_SLOT_FIELDS:
            items = action_payload.get(payload_key)
            if not isinstance(items, list):
                continue
            slot_candidates = [
                candidate
                for candidate in (
                    cls._normalize_candidate_meal(slot=slot, raw_candidate=item)
                    for item in items
                )
                if candidate is not None
            ]
            if slot_candidates:
                normalized[slot] = slot_candidates
        return normalized

    @classmethod
    def _normalize_candidate_meal(cls, *, slot: str, raw_candidate: Any) -> dict[str, Any] | None:
        if not isinstance(raw_candidate, dict):
            return None
        meal_id = str(raw_candidate.get("id") or "").strip()
        if not meal_id:
            return None
        normalized_recipe_steps = cls._normalized_string_list(raw_candidate.get("recipe_steps"))
        normalized_ingredients = cls._normalized_candidate_ingredients(raw_candidate.get("ingredient_items"))
        return {
            "id": meal_id,
            "name": str(raw_candidate.get("name") or "").strip() or f"Meal {meal_id}",
            "meal_type": cls._normalize_slot_name(raw_candidate.get("meal_type")) or slot,
            "hero_image_url": str(raw_candidate.get("hero_image_url") or "").strip() or None,
            "servings": raw_candidate.get("servings"),
            "description": str(raw_candidate.get("description") or "").strip(),
            "cook_time_minutes": cls._normalized_int(raw_candidate.get("cook_time_minutes")),
            "prep_time_minutes": cls._normalized_int(raw_candidate.get("prep_time_minutes")),
            "culture_tags": cls._normalized_string_list(raw_candidate.get("culture_tags")),
            "diet_rules_supported": cls._normalized_string_list(raw_candidate.get("diet_rules_supported")),
            "allergy_exclusions": cls._normalized_string_list(raw_candidate.get("allergy_exclusions")),
            "estimated_costs": cls._normalized_estimated_costs(raw_candidate.get("estimated_costs")),
            "ingredient_items": normalized_ingredients,
            "linked_product_ids": cls._normalized_string_list(raw_candidate.get("linked_product_ids")),
            "nutrition_summary": cls._normalized_candidate_nutrition(raw_candidate.get("nutrition_summary")),
            "recipe_steps": normalized_recipe_steps,
            "recipe_step_items": cls._normalized_recipe_step_items(raw_candidate.get("recipe_step_items"), normalized_recipe_steps),
            "linked_products": list(raw_candidate.get("linked_products") or []),
            "difficulty": str(raw_candidate.get("difficulty") or "").strip() or None,
        }

    @classmethod
    def _normalize_user_context(cls, raw_context: Any) -> dict[str, Any]:
        if not isinstance(raw_context, dict):
            return {}
        normalized = {
            "goal": str(raw_context.get("goal") or "").strip() or None,
            "weekly_budget": cls._normalized_budget(raw_context.get("weekly_budget")),
            "household_size": cls._normalized_positive_int(raw_context.get("household_size")),
            "culture_preferences": cls._normalized_string_list(raw_context.get("culture_preferences")),
            "diet_rules": cls._normalized_string_list(raw_context.get("diet_rules")),
            "allergies": cls._normalized_string_list(raw_context.get("allergies")),
        }
        if any(
            value
            for value in (
                normalized["goal"],
                normalized["weekly_budget"],
                normalized["culture_preferences"],
                normalized["diet_rules"],
                normalized["allergies"],
            )
        ):
            return normalized
        return {}

    @staticmethod
    def _normalized_budget(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            numeric = int(float(value))
        except (TypeError, ValueError):
            return None
        return numeric if numeric > 0 else None

    @staticmethod
    def _normalized_positive_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            numeric = int(float(value))
        except (TypeError, ValueError):
            return None
        return numeric if numeric > 0 else None

    @staticmethod
    def _normalized_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            cleaned = str(item or "").strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @classmethod
    def _normalized_estimated_costs(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            amount = cls._normalized_float(item.get("amount"))
            if amount is None:
                continue
            normalized.append(
                {
                    "country_code": str(item.get("country_code") or "").upper() or None,
                    "currency_code": str(item.get("currency_code") or "").upper() or None,
                    "amount": amount,
                }
            )
        return normalized

    @classmethod
    def _normalized_candidate_ingredients(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "id": item.get("id") or f"ingredient-{index}",
                    "name": name,
                    "quantity": cls._normalized_float(item.get("quantity")),
                    "unit": str(item.get("unit") or "").strip(),
                    "base_quantity": cls._normalized_float(item.get("base_quantity"))
                    or cls._normalized_float(item.get("quantity")),
                    "optional": bool(item.get("optional", False)),
                    "linked_product_ids": cls._normalized_string_list(item.get("linked_product_ids")),
                    "measurement_type": item.get("measurement_type"),
                    "unit_code": item.get("unit_code"),
                    "canonical_quantity": cls._normalized_float(item.get("canonical_quantity")),
                    "canonical_unit": item.get("canonical_unit"),
                    "conversion_profile_id": item.get("conversion_profile_id"),
                    "scaling_behavior": item.get("scaling_behavior"),
                    "rounding_rule": item.get("rounding_rule"),
                    "scale_factor": cls._normalized_float(item.get("scale_factor")),
                }
            )
        return normalized

    @classmethod
    def _normalized_candidate_nutrition(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = {}
        return {
            "calories": cls._normalized_int(value.get("calories")),
            "protein_g": cls._normalized_float(value.get("protein_g")) or 0.0,
            "carbs_g": cls._normalized_float(value.get("carbs_g")) or 0.0,
            "fat_g": cls._normalized_float(value.get("fat_g")) or 0.0,
        }

    @classmethod
    def _normalized_recipe_step_items(cls, value: Any, fallback_steps: list[str]) -> list[dict[str, Any]]:
        if isinstance(value, list) and value:
            normalized: list[dict[str, Any]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                instruction = str(item.get("instruction") or "").strip()
                if not instruction:
                    continue
                normalized.append(
                    {
                        "instruction": instruction,
                        "ingredient_ids": cls._normalized_string_list(item.get("ingredient_ids")),
                        "image_url": str(item.get("image_url") or "").strip() or None,
                    }
                )
            if normalized:
                return normalized
        return [
            {
                "instruction": step,
                "ingredient_ids": [],
                "image_url": None,
            }
            for step in fallback_steps
        ]

    @staticmethod
    def _resolved_requested_culture(action_payload: dict[str, Any], user_context: dict[str, Any]) -> str | None:
        explicit = str(action_payload.get("requested_culture") or action_payload.get("culture") or "").strip()
        if explicit:
            return explicit
        preferences = list(user_context.get("culture_preferences") or [])
        return preferences[0] if preferences else None

    @staticmethod
    def _build_prompt_constraints(
        *,
        requested_slots: list[str],
        available_slots: list[str],
        missing_slots: list[str],
        candidate_meals_by_slot: dict[str, list[dict[str, Any]]],
        requested_culture: str | None,
        user_context: dict[str, Any],
        request_kind: str,
        effective_date: str | None,
        selected_dates: list[str],
    ) -> list[str]:
        constraints: list[str] = [
            f"Requested slots: {', '.join(requested_slots) if requested_slots else 'none'}.",
            f"Available candidate slots: {', '.join(available_slots) if available_slots else 'none'}.",
            f"Treat this turn as request kind: {request_kind}.",
        ]
        if missing_slots:
            constraints.append(
                f"Some requested slots had no candidates: {', '.join(missing_slots)}. Mention that briefly in assistant_text and proceed with the available slots."
            )
        if effective_date:
            constraints.append(f"Build the plan starting from {effective_date}.")
        if selected_dates:
            constraints.append(f"Only generate meals for these dates: {', '.join(selected_dates)}.")
        for slot in requested_slots:
            constraints.append(
                f"Only choose from the {len(candidate_meals_by_slot.get(slot) or [])} provided {slot} candidates."
            )
        if requested_culture:
            constraints.append(f"Use {requested_culture} as a soft cultural preference.")
        if user_context.get("goal"):
            constraints.append(f"Align the plan with the user goal: {user_context['goal']}.")
        if user_context.get("diet_rules"):
            constraints.append(
                f"Only choose meals compatible with these diet rules: {', '.join(user_context['diet_rules'])}."
            )
        if user_context.get("allergies"):
            constraints.append(
                f"Reject meals that conflict with these allergies: {', '.join(user_context['allergies'])}."
            )
        if user_context.get("weekly_budget"):
            constraints.append("Keep the plan sensible for the weekly budget posture.")
        if user_context.get("household_size"):
            constraints.append(f"Make sure the selected meals make sense for a household size of {user_context['household_size']}.")
        return constraints

    def _planner_request_payload(self, state: MealConversationGraphState) -> str:
        payload = {
            "user_request": str(state.get("latest_user_message") or "").strip(),
            "request_kind": state.get("constraint_state", {}).get("request_kind"),
            "effective_date": state.get("constraint_state", {}).get("effective_date"),
            "selected_dates": list(state.get("constraint_state", {}).get("selected_dates") or []),
            "requested_slots": list(state.get("constraint_state", {}).get("target_meal_types") or []),
            "requested_culture": state.get("constraint_state", {}).get("requested_culture"),
            "country_code": state.get("run_context", {}).get("country_code"),
            "user_context": dict(state.get("user_context") or {}),
            "ranked_bundles": list(state.get("ranked_bundles") or []),
            "slot_candidates": dict(state.get("candidate_meals_by_slot") or {}),
        }
        return json.dumps(payload, default=str)

    @classmethod
    def _normalize_ranked_bundles(cls, raw_bundles: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_bundles, list):
            return []
        normalized: list[dict[str, Any]] = []
        for raw_bundle in raw_bundles:
            if not isinstance(raw_bundle, dict):
                continue
            bundle_id = str(raw_bundle.get("bundle_id") or "").strip()
            if not bundle_id:
                continue
            meals_by_slot = {
                slot: meal
                for slot, meal in (
                    (
                        cls._normalize_slot_name(slot_name),
                        cls._normalize_candidate_meal(slot=slot_name, raw_candidate=meal_payload),
                    )
                    for slot_name, meal_payload in dict(raw_bundle.get("meals_by_slot") or {}).items()
                )
                if slot and meal is not None
            }
            if not meals_by_slot:
                continue
            planned_meals = [
                {
                    "slot": slot,
                    "meal_id": meal.get("id"),
                    "meal_name": cls._candidate_display_name(meal),
                    "meal_source": "catalog",
                    "created_meal_draft": None,
                }
                for slot, meal in meals_by_slot.items()
            ]
            normalized.append(
                {
                    "bundle_id": bundle_id,
                    "score": raw_bundle.get("score"),
                    "score_breakdown": dict(raw_bundle.get("score_breakdown") or {}),
                    "meals_by_slot": meals_by_slot,
                    "planned_meals": list(raw_bundle.get("planned_meals") or planned_meals),
                    "totals": dict(raw_bundle.get("totals") or {}),
                    "bundle_summary": dict(raw_bundle.get("bundle_summary") or {}),
                    "inventory_summary": dict(raw_bundle.get("inventory_summary") or {}),
                    "cart_summary": dict(raw_bundle.get("cart_summary") or {}),
                }
            )
        return normalized

    def _find_candidate_for_selection(
        self,
        *,
        slot: str,
        candidates: list[dict[str, Any]],
        planned_entry: dict[str, Any],
    ) -> dict[str, Any] | None:
        selected_id = str(planned_entry.get("meal_id") or "").strip()
        if selected_id:
            for candidate in candidates:
                if str(candidate.get("id") or "").strip() == selected_id:
                    return candidate

        selected_name = str(planned_entry.get("meal_name") or "").strip().lower()
        if selected_name:
            for candidate in candidates:
                candidate_name = self._candidate_display_name(candidate).strip().lower()
                if candidate_name == selected_name:
                    return candidate
        return None

    @classmethod
    def _match_ranked_bundle_for_plan(
        cls,
        *,
        ranked_bundles: list[dict[str, Any]],
        planned_meals: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        normalized_slots = {
            cls._normalize_slot_name(item.get("slot")): {
                "meal_id": str(item.get("meal_id") or "").strip(),
                "meal_name": str(item.get("meal_name") or "").strip().lower(),
            }
            for item in planned_meals
            if cls._normalize_slot_name(item.get("slot"))
        }
        if not normalized_slots:
            return None
        for bundle in ranked_bundles:
            bundle_slots = {
                cls._normalize_slot_name(item.get("slot")): {
                    "meal_id": str(item.get("meal_id") or "").strip(),
                    "meal_name": str(item.get("meal_name") or "").strip().lower(),
                }
                for item in list(bundle.get("planned_meals") or [])
                if cls._normalize_slot_name(item.get("slot"))
            }
            if bundle_slots == normalized_slots:
                return bundle
        return None

    @staticmethod
    def _candidate_display_name(candidate: dict[str, Any]) -> str:
        name = str(candidate.get("name") or "").strip()
        if name:
            return name
        description = str(candidate.get("description") or "").strip()
        if description:
            return description[:80]
        return str(candidate.get("id") or "Meal")
