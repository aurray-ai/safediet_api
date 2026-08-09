from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.agents.meal_conversation.coordinator import MEAL_COORDINATOR_AGENT_TYPE
from app.agents.meal_conversation.graph import MealConversationGraph
from app.agents.meal_conversation.runtime import MealConversationRuntime
from app.agents.meal_conversation.state import MealConversationTurnResult
from app.agents.meal_conversation.subagents.meal_planner.graph import MealPlannerGraph
from app.core.config import Settings
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.user import User
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.meal_repository import MealRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.user_pantry_repository import UserPantryRepository
from app.repositories.user_repository import UserRepository
from app.schemas.meal_conversation import (
    ConversationMessagesResponse,
    ConversationMessageResponse,
    MealPlannerDraftSaveRequest,
    ConversationQuickActionResponse,
    ConversationSummaryResponse,
    ConversationUIBlockResponse,
    CreateConversationResponse,
    CurrentConversationResponse,
    MealPlannerRequest,
    SendConversationMessageAcceptedResponse,
    SendConversationMessageRequest,
    SendConversationMessageResponse,
)
from app.services.meal_search_embedding_service import MealSearchEmbeddingService
from app.services.meal_inventory_reconciliation_service import MealInventoryReconciliationService
from app.services.meal_plan_cart_service import MealPlanCartService
from app.services.meal_plan_costing_service import MealPlanCostingService
from app.services.meal_plan_optimization_service import MealPlanOptimizationService
from app.services.kitchen_service import KitchenService
from app.services.meal_planner_monitoring_service import (
    MealPlannerMonitoringRecorder,
    meal_planner_monitoring_service,
)
from app.services.meal_semantic_search_service import MealSemanticSearchItem, MealSemanticSearchService
from app.services.user_meal_usage_service import UserMealUsageService
from app.models.saved_meal_plan import SavedMealPlan
from app.services.realtime_delivery_service import realtime_delivery_service

logger = logging.getLogger(__name__)


class MealConversationNotFoundError(Exception):
    pass


class MealConversationTurnDeliveryError(Exception):
    def __init__(self, message: str, *, issue: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.issue = issue


@dataclass(frozen=True, slots=True)
class MealPlannerSearchTrace:
    slot: MealType
    semantic_query: str
    candidate_count: int


@dataclass(frozen=True, slots=True)
class PreparedMealPlannerTurn:
    turn_result: MealConversationTurnResult
    prepared_action_payload: dict[str, Any]
    semantic_queries: list[MealPlannerSearchTrace]


@dataclass(frozen=True, slots=True)
class MealPlannerDraftSaveResult:
    saved_plan: SavedMealPlan
    notification_event: dict[str, Any] | None
    already_saved: bool


class MealConversationService:
    def __init__(
        self,
        *,
        settings: Settings,
        user_repository: UserRepository,
        meal_conversation_repository: MealConversationRepository,
        meal_repository: MealRepository,
        grocery_repository: GroceryRepository,
        saved_meal_plan_repository: SavedMealPlanRepository,
        user_pantry_repository: UserPantryRepository,
        kitchen_service: KitchenService,
        user_meal_usage_service: UserMealUsageService,
    ) -> None:
        self._settings = settings
        self._user_repository = user_repository
        self._meal_conversation_repository = meal_conversation_repository
        self._meal_repository = meal_repository
        self._grocery_repository = grocery_repository
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._user_pantry_repository = user_pantry_repository
        self._kitchen_service = kitchen_service
        self._user_meal_usage_service = user_meal_usage_service

    def start_conversation(
        self,
        *,
        current_user: User,
        opening_message: str | None,
        meal_type: MealType | None,
        country_code: CountryCode | None,
    ) -> CreateConversationResponse:
        user_goal = self._require_user_goal(current_user)
        conversation = self._meal_conversation_repository.find_reusable_conversation(
            user_id=current_user.id,
            user_goal=user_goal,
        )
        if conversation is None:
            conversation = self._meal_conversation_repository.create_conversation(
                user_id=current_user.id,
                user_goal=user_goal,
                agent_type=MEAL_COORDINATOR_AGENT_TYPE,
                status="active",
                current_summary=self._build_summary_payload(
                    user_goal=user_goal,
                    agent_type=MEAL_COORDINATOR_AGENT_TYPE,
                    meal_type=meal_type,
                    country_code=country_code,
                ),
            )
        else:
            current_summary = dict(conversation.get("current_summary") or {})
            conversation = self._meal_conversation_repository.update_conversation_summary(
                conversation_id=str(conversation["_id"]),
                user_goal=user_goal,
                agent_type=MEAL_COORDINATOR_AGENT_TYPE,
                status="active",
                current_summary=self._build_summary_payload(
                    user_goal=user_goal,
                    agent_type=MEAL_COORDINATOR_AGENT_TYPE,
                    meal_type=meal_type,
                    country_code=country_code,
                    selected_meal_id=current_summary.get("selected_meal_id"),
                    selected_meal_name=current_summary.get("selected_meal_name"),
                    meal_source=current_summary.get("meal_source"),
                    planned_meals=list(current_summary.get("planned_meals") or []),
                    requested_culture=current_summary.get("requested_culture"),
                    last_user_intent=current_summary.get("last_user_intent"),
                    last_assistant_preview=current_summary.get("last_assistant_preview"),
                    latest_ui_blocks=list(current_summary.get("latest_ui_blocks") or []),
                    latest_quick_actions=list(current_summary.get("latest_quick_actions") or []),
                    latest_message_id=current_summary.get("latest_message_id"),
                    message_count=int(current_summary.get("message_count") or conversation.get("message_count") or 0),
                    last_message_at=current_summary.get("last_message_at") or conversation.get("last_message_at"),
                ),
            ) or conversation

        assistant_message: dict[str, Any] | None = None
        if opening_message:
            self._meal_conversation_repository.append_message(
                conversation_id=str(conversation["_id"]),
                role="user",
                text=opening_message,
                ui_blocks=[],
                quick_actions=[],
                metadata={"source": "conversation_start"},
            )
            assistant_message, conversation = self._run_assistant_turn(
                current_user=current_user,
                conversation=conversation,
                user_text=opening_message,
                quick_action_type=None,
                action_payload={},
                explicit_meal_type=meal_type,
                explicit_country_code=country_code,
            )

        refreshed_conversation = self._meal_conversation_repository.get_conversation(str(conversation["_id"]))
        return CreateConversationResponse(
            conversation=self._to_conversation_summary(refreshed_conversation or conversation),
            assistant_message=self._to_message_response(assistant_message) if assistant_message is not None else None,
        )

    def accept_message(
        self,
        *,
        current_user: User,
        conversation_id: str,
        payload: SendConversationMessageRequest,
        trace_id: str | None = None,
    ) -> SendConversationMessageAcceptedResponse:
        conversation = self._require_owned_conversation(
            current_user=current_user,
            conversation_id=conversation_id,
        )
        logger.info(
            "planner.service.send_message.start trace_id=%s conversation_id=%s user_id=%s quick_action_type=%s action_payload_keys=%s",
            trace_id or "-",
            conversation_id,
            current_user.id,
            payload.quick_action_type or "-",
            ",".join(sorted(payload.action_payload.keys())) or "-",
        )

        user_message = self._meal_conversation_repository.append_message(
            conversation_id=conversation_id,
            role="user",
            text=(payload.text or "").strip(),
            ui_blocks=[],
            quick_actions=[],
            metadata={
                "quick_action_id": payload.quick_action_id,
                "quick_action_type": payload.quick_action_type,
                "action_payload": payload.action_payload,
                "trace_id": trace_id,
            },
        )
        logger.info(
            "planner.service.send_message.user_appended trace_id=%s conversation_id=%s user_message_id=%s text_len=%s",
            trace_id or "-",
            conversation_id,
            str(user_message.get("_id")),
            len((payload.text or "").strip()),
        )

        refreshed_conversation = self._meal_conversation_repository.get_conversation(conversation_id) or conversation
        return SendConversationMessageAcceptedResponse(
            trace_id=trace_id or "",
            conversation=self._to_conversation_summary(refreshed_conversation),
            user_message=self._to_message_response(user_message),
        )

    def complete_message(
        self,
        *,
        current_user: User,
        conversation_id: str,
        payload: SendConversationMessageRequest,
        trace_id: str | None = None,
    ) -> SendConversationMessageResponse:
        started_at = time.perf_counter()
        conversation = self._require_owned_conversation(
            current_user=current_user,
            conversation_id=conversation_id,
        )
        user_message = self._latest_user_message_for_trace(
            conversation_id=conversation_id,
            trace_id=trace_id,
            fallback_text=(payload.text or "").strip(),
        )

        if payload.quick_action_type == "save_meal_plan":
            assistant_message, updated_conversation = self._save_meal_plan_snapshot(
                conversation=conversation,
                payload=payload,
                trace_id=trace_id,
            )
        else:
            assistant_message, updated_conversation = self._run_assistant_turn(
                current_user=current_user,
                conversation=conversation,
                user_text=(payload.text or "").strip(),
                quick_action_type=payload.quick_action_type,
                action_payload=payload.action_payload,
                explicit_meal_type=None,
                explicit_country_code=None,
                trace_id=trace_id,
            )

        logger.info(
            "planner.service.send_message.completed trace_id=%s conversation_id=%s assistant_message_id=%s duration_ms=%s turn_mode=%s selected_meal_id=%s",
            trace_id or "-",
            conversation_id,
            str(assistant_message.get("_id")),
            int((time.perf_counter() - started_at) * 1000),
            (assistant_message.get("metadata") or {}).get("turn_mode", "-"),
            (assistant_message.get("metadata") or {}).get("selected_meal_id", "-"),
        )
        assistant_metadata = dict(assistant_message.get("metadata") or {})
        llm_metrics = dict(assistant_metadata.get("llm_metrics") or {})
        logger.info(
            "planner.trace.summary trace_id=%s conversation_id=%s user_text=%s turn_mode=%s model=%s tools_used=%s llm_ms=%s total_ms=%s assistant_text=%s",
            trace_id or "-",
            conversation_id,
            self._text_preview((payload.text or "").strip()),
            assistant_metadata.get("turn_mode", "-"),
            llm_metrics.get("model_name") or llm_metrics.get("provider") or "-",
            len(assistant_metadata.get("tool_trace") or []),
            llm_metrics.get("duration_ms", "-"),
            int((time.perf_counter() - started_at) * 1000),
            self._text_preview(str(assistant_message.get("text") or "")),
        )

        return SendConversationMessageResponse(
            conversation=self._to_conversation_summary(updated_conversation),
            user_message=self._to_message_response(user_message),
            assistant_message=self._to_message_response(assistant_message),
        )

    def plan_meals(
        self,
        *,
        current_user: User,
        payload: MealPlannerRequest,
        trace_id: str | None = None,
    ) -> PreparedMealPlannerTurn:
        recorder = self._start_meal_planner_monitoring(
            current_user=current_user,
            payload=payload,
            trace_id=trace_id,
        )
        user_context = self._build_meal_planner_user_context(current_user)
        requested_culture = payload.requested_culture or self._preferred_culture(user_context)
        request_kind = self._planner_request_kind(payload)
        country_code = payload.country_code
        requested_slots = [slot.value for slot in payload.slots]

        logger.info(
            "planner.service.plan_meals.start trace_id=%s user_id=%s request_type=%s requested_slots=%s effective_date=%s selected_dates=%s",
            trace_id or "-",
            current_user.id,
            payload.request_type,
            ",".join(requested_slots) or "-",
            payload.effective_date.isoformat() if payload.effective_date is not None else "-",
            ",".join(item.isoformat() for item in self._selected_plan_dates(payload)) or "-",
        )
        if recorder is not None:
            recorder.log(
                step_key="planner.context.loaded",
                branch_key="context",
                input_data={"requested_slots": requested_slots, "request_kind": request_kind},
                output_data={
                    "has_user_context": bool(user_context),
                    "requested_culture": requested_culture,
                    "country_code": country_code.value if country_code is not None else None,
                },
            )

        try:
            self.assert_plan_generation_allowed(
                current_user=current_user,
                payload=payload,
            )
            if not user_context:
                clarification = self._build_planner_clarification_result(
                    assistant_text=(
                        "I need your meal-planning context first. Please provide your goal, allergies, diet rules, culture preferences, and budget."
                    ),
                    issue="missing_user_context",
                    requested_culture=requested_culture,
                    meal_type=payload.slot,
                    country_code=country_code,
                )
                if recorder is not None:
                    recorder.complete_run(
                        summary={
                            "turn_mode": clarification.turn_mode,
                            "issue": "missing_user_context",
                            "planned_meals": 0,
                        }
                    )
                return PreparedMealPlannerTurn(
                    turn_result=clarification,
                    prepared_action_payload={
                        "user_context": {},
                        "request_kind": request_kind,
                        "requested_culture": requested_culture,
                        "country_code": country_code.value if country_code is not None else None,
                        "effective_date": payload.effective_date.isoformat() if payload.effective_date is not None else None,
                        "selected_dates": [item.isoformat() for item in self._selected_plan_dates(payload)],
                    },
                    semantic_queries=[],
                )

            slot_candidates: dict[str, list[dict[str, Any]]] = {}
            semantic_queries: list[MealPlannerSearchTrace] = []
            search_service = self._meal_semantic_search_service()
            for slot in payload.slots:
                semantic_query = self._build_semantic_query(
                    message=payload.message,
                    request_type=payload.request_type,
                    slot=slot,
                    user_context=user_context,
                    requested_culture=requested_culture,
                    low_budget_mode=payload.low_budget_mode,
                )
                retrieval_step_id = (
                    recorder.start_step(
                        step_key="planner.slot_candidates",
                        parent_step_id=recorder.root_step_id,
                        branch_key=slot.value,
                        step_type="search",
                        input_data={"semantic_query": semantic_query},
                        tags={"slot": slot.value},
                    )
                    if recorder is not None
                    else None
                )
                candidates = self._retrieve_slot_candidates(
                    search_service=search_service,
                    slot=slot,
                    semantic_query=semantic_query,
                    user_context=user_context,
                    requested_culture=requested_culture,
                    country_code=country_code,
                    low_budget_mode=payload.low_budget_mode,
                    limit=payload.candidate_limit_per_slot,
                )
                slot_candidates[slot.value] = candidates
                semantic_queries.append(
                    MealPlannerSearchTrace(
                        slot=slot,
                        semantic_query=semantic_query,
                        candidate_count=len(candidates),
                    )
                )
                if recorder is not None and retrieval_step_id is not None:
                    recorder.complete_step(
                        step_id=retrieval_step_id,
                        step_key="planner.slot_candidates",
                        parent_step_id=recorder.root_step_id,
                        branch_key=slot.value,
                        step_type="search",
                        output_data={
                            "candidate_count": len(candidates),
                            "candidate_ids": [str(item.get("id") or "") for item in candidates],
                        },
                        tags={"slot": slot.value},
                    )
                logger.info(
                    "planner.service.plan_meals.slot_candidates trace_id=%s user_id=%s slot=%s candidate_count=%s",
                    trace_id or "-",
                    current_user.id,
                    slot.value,
                    len(candidates),
                )

            missing_slots = [
                slot.value
                for slot in payload.slots
                if not list(slot_candidates.get(slot.value) or [])
            ]
            available_slots = [
                slot.value
                for slot in payload.slots
                if list(slot_candidates.get(slot.value) or [])
            ]

            if missing_slots:
                logger.warning(
                    "planner.service.plan_meals.partial_slot_coverage trace_id=%s user_id=%s request_type=%s available_slots=%s missing_slots=%s",
                    trace_id or "-",
                    current_user.id,
                    payload.request_type,
                    ",".join(available_slots) or "-",
                    ",".join(missing_slots) or "-",
                )
                if recorder is not None:
                    recorder.log(
                        step_key="planner.partial_slot_coverage",
                        parent_step_id=recorder.root_step_id,
                        branch_key="retrieval",
                        output_data={
                            "available_slots": available_slots,
                            "missing_slots": missing_slots,
                        },
                        status="warning",
                    )

            ranking_step_id = (
                recorder.start_step(
                    step_key="planner.bundle_ranking",
                    parent_step_id=recorder.root_step_id,
                    branch_key="ranking",
                    step_type="optimization",
                    input_data={
                        "slots": requested_slots,
                        "candidate_counts": {
                            slot_name: len(items)
                            for slot_name, items in slot_candidates.items()
                        },
                    },
                )
                if recorder is not None
                else None
            )
            ranking_started_at = time.perf_counter()
            ranked_bundles = self._rank_meal_plan_bundles(
                current_user=current_user,
                slot_candidates=slot_candidates,
                user_context=user_context,
                requested_culture=requested_culture,
                country_code=country_code,
            )
            ranking_duration_ms = int((time.perf_counter() - ranking_started_at) * 1000)
            if recorder is not None and ranking_step_id is not None:
                recorder.complete_step(
                    step_id=ranking_step_id,
                    step_key="planner.bundle_ranking",
                    parent_step_id=recorder.root_step_id,
                    branch_key="ranking",
                    step_type="optimization",
                    output_data={
                        "ranked_bundle_count": len(ranked_bundles),
                        "bundle_ids": [str(item.get("bundle_id") or "") for item in ranked_bundles],
                    },
                    metrics={"duration_ms": ranking_duration_ms},
                )
            logger.info(
                "planner.service.plan_meals.rank_bundles.completed trace_id=%s user_id=%s request_type=%s slots=%s ranked_bundles=%s duration_ms=%s",
                trace_id or "-",
                current_user.id,
                payload.request_type,
                ",".join(requested_slots) or "-",
                len(ranked_bundles),
                ranking_duration_ms,
            )

            prepared_action_payload = self._build_meal_planner_action_payload(
                user_context=user_context,
                request_kind=request_kind,
                requested_culture=requested_culture,
                country_code=country_code,
                low_budget_mode=payload.low_budget_mode,
                allow_custom_meal_creation=payload.allow_custom_meal_creation,
                effective_date=payload.effective_date,
                selected_dates=self._selected_plan_dates(payload),
                requested_slots=requested_slots,
                missing_slots=missing_slots,
                slot_candidates=slot_candidates,
                ranked_bundles=ranked_bundles,
                monitoring_recorder=recorder,
            )
            if not available_slots:
                clarification = self._build_planner_clarification_result(
                    assistant_text=(
                        "I couldn't find good meal candidates for "
                        + ", ".join(slot.value for slot in payload.slots)
                        + ". Please broaden the request or change the slot."
                    ),
                    issue="missing_slot_candidates",
                    requested_culture=requested_culture,
                    meal_type=payload.slot,
                    country_code=country_code,
                )
                if recorder is not None:
                    recorder.complete_run(
                        summary={
                            "turn_mode": clarification.turn_mode,
                            "issue": "missing_slot_candidates",
                            "planned_meals": 0,
                        }
                    )
                return PreparedMealPlannerTurn(
                    turn_result=clarification,
                    prepared_action_payload=prepared_action_payload,
                    semantic_queries=semantic_queries,
                )

            turn_result = self._run_prepared_meal_planner(
                current_user=current_user,
                message=payload.message,
                request_type=payload.request_type,
                action_payload=prepared_action_payload,
                explicit_meal_type=payload.slot,
                explicit_country_code=country_code,
                conversation_id=payload.conversation_id,
                trace_id=trace_id,
                monitoring_recorder=recorder,
            )
            enrich_step_id = (
                recorder.start_step(
                    step_key="planner.summary.enriched",
                    parent_step_id=recorder.root_step_id,
                    branch_key="summary",
                    step_type="summary",
                )
                if recorder is not None
                else None
            )
            turn_result = self._enrich_prepared_meal_planner_turn(
                current_user=current_user,
                action_payload=prepared_action_payload,
                turn_result=turn_result,
            )
            if recorder is not None and enrich_step_id is not None:
                recorder.complete_step(
                    step_id=enrich_step_id,
                    step_key="planner.summary.enriched",
                    parent_step_id=recorder.root_step_id,
                    branch_key="summary",
                    step_type="summary",
                    output_data={
                        "has_bundle_summary": bool((turn_result.metadata or {}).get("bundle_summary")),
                        "has_inventory_summary": bool((turn_result.metadata or {}).get("inventory_summary")),
                        "has_cart_summary": bool((turn_result.metadata or {}).get("cart_summary")),
                    },
                )
            persist_step_id = (
                recorder.start_step(
                    step_key="planner.draft.persisted",
                    parent_step_id=recorder.root_step_id,
                    branch_key="persistence",
                    step_type="persistence",
                )
                if recorder is not None
                else None
            )
            saved_plan = self._persist_generated_meal_plan_draft(
                current_user=current_user,
                turn_result=turn_result,
                source_conversation_id=payload.conversation_id,
            )
            if recorder is not None and persist_step_id is not None:
                recorder.complete_step(
                    step_id=persist_step_id,
                    step_key="planner.draft.persisted",
                    parent_step_id=recorder.root_step_id,
                    branch_key="persistence",
                    step_type="persistence",
                    output_data={
                        "saved_plan_id": saved_plan.id if saved_plan is not None else None,
                        "view_mode": saved_plan.view_mode if saved_plan is not None else None,
                        "status": saved_plan.status if saved_plan is not None else None,
                    },
                )
                recorder.complete_run(
                    summary={
                        "turn_mode": turn_result.turn_mode,
                        "planned_meals": len(turn_result.planned_meals),
                        "ui_blocks": len(turn_result.ui_blocks),
                    }
                )
            return PreparedMealPlannerTurn(
                turn_result=turn_result,
                prepared_action_payload=prepared_action_payload,
                semantic_queries=semantic_queries,
            )
        except Exception as exc:
            if recorder is not None:
                recorder.fail_run(
                    error={
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    }
                )
            raise

    async def generate_weekly_plan_with_progress(
        self,
        *,
        current_user: User,
        payload: MealPlannerRequest,
        trace_id: str | None = None,
    ) -> PreparedMealPlannerTurn:
        if payload.request_type not in {"generate_week_plan", "generate_multi_day_plan"}:
            return self.plan_meals(
                current_user=current_user,
                payload=payload,
                trace_id=trace_id,
            )

        started_at = time.perf_counter()
        job_id = trace_id or uuid4().hex
        recorder = self._start_meal_planner_monitoring(
            current_user=current_user,
            payload=payload,
            trace_id=trace_id,
        )
        user_context = self._build_meal_planner_user_context(current_user)
        requested_culture = payload.requested_culture or self._preferred_culture(user_context)
        request_kind = self._planner_request_kind(payload)
        country_code = payload.country_code
        requested_slots = [slot.value for slot in payload.slots]

        async def publish_progress(*, phase: str, progress: float, message: str, extra: dict[str, Any] | None = None) -> None:
            await realtime_delivery_service.deliver(
                user_id=current_user.id,
                delivery_type="meal_plan_generation",
                location="ios.home",
                payload={
                    "job_id": job_id,
                    "trace_id": trace_id,
                    "phase": phase,
                    "progress": round(progress, 3),
                    "message": message,
                    "request_type": payload.request_type,
                    "view_mode": "week",
                    "effective_date": payload.effective_date.isoformat() if payload.effective_date is not None else None,
                    **(extra or {}),
                },
                trace_id=trace_id,
                status="processing",
                channels=["websocket"],
                metadata={"source": "meal_planner", "job_id": job_id, "phase": phase},
            )

        await publish_progress(
            phase="searching",
            progress=0.05,
            message="Finding meal candidates for your week.",
        )
        if recorder is not None:
            recorder.log(
                step_key="planner.context.loaded",
                branch_key="context",
                input_data={"requested_slots": requested_slots, "request_kind": request_kind},
                output_data={
                    "has_user_context": bool(user_context),
                    "requested_culture": requested_culture,
                    "country_code": country_code.value if country_code is not None else None,
                },
            )

        try:
            self.assert_plan_generation_allowed(
                current_user=current_user,
                payload=payload,
            )
            slot_candidates: dict[str, list[dict[str, Any]]] = {}
            semantic_queries: list[MealPlannerSearchTrace] = []
            search_service = self._meal_semantic_search_service()
            for index, slot in enumerate(payload.slots, start=1):
                semantic_query = self._build_semantic_query(
                    message=payload.message,
                    request_type=payload.request_type,
                    slot=slot,
                    user_context=user_context,
                    requested_culture=requested_culture,
                    low_budget_mode=payload.low_budget_mode,
                )
                retrieval_step_id = (
                    recorder.start_step(
                        step_key="planner.slot_candidates",
                        parent_step_id=recorder.root_step_id,
                        branch_key=slot.value,
                        step_type="search",
                        input_data={"semantic_query": semantic_query},
                        tags={"slot": slot.value},
                    )
                    if recorder is not None
                    else None
                )
                candidates = await asyncio.to_thread(
                    self._retrieve_slot_candidates,
                    search_service=search_service,
                    slot=slot,
                    semantic_query=semantic_query,
                    user_context=user_context,
                    requested_culture=requested_culture,
                    country_code=country_code,
                    low_budget_mode=payload.low_budget_mode,
                    limit=payload.candidate_limit_per_slot,
                )
                slot_candidates[slot.value] = candidates
                semantic_queries.append(
                    MealPlannerSearchTrace(
                        slot=slot,
                        semantic_query=semantic_query,
                        candidate_count=len(candidates),
                    )
                )
                if recorder is not None and retrieval_step_id is not None:
                    recorder.complete_step(
                        step_id=retrieval_step_id,
                        step_key="planner.slot_candidates",
                        parent_step_id=recorder.root_step_id,
                        branch_key=slot.value,
                        step_type="search",
                        output_data={
                            "candidate_count": len(candidates),
                            "candidate_ids": [str(item.get("id") or "") for item in candidates],
                        },
                        tags={"slot": slot.value},
                    )
                await publish_progress(
                    phase="searching",
                    progress=min(0.05 + (index / max(len(payload.slots), 1)) * 0.35, 0.4),
                    message=f"Checked {slot.value} options.",
                    extra={
                        "current_slot": slot.value,
                        "candidate_count": len(candidates),
                        "completed_slots": [trace.slot.value for trace in semantic_queries],
                    },
                )

            missing_slots = [
                slot.value
                for slot in payload.slots
                if not list(slot_candidates.get(slot.value) or [])
            ]
            if missing_slots and len(missing_slots) == len(payload.slots):
                clarification = self._build_planner_clarification_result(
                    assistant_text=(
                        "I couldn't find good meal candidates for "
                        + ", ".join(slot.value for slot in payload.slots)
                        + ". Please broaden the request or change the slot."
                    ),
                    issue="missing_slot_candidates",
                    requested_culture=requested_culture,
                    meal_type=payload.slot,
                    country_code=country_code,
                )
                await publish_progress(
                    phase="failed",
                    progress=1.0,
                    message="No meal candidates were available.",
                    extra={"issue": "missing_slot_candidates"},
                )
                if recorder is not None:
                    recorder.complete_run(
                        summary={
                            "turn_mode": clarification.turn_mode,
                            "issue": "missing_slot_candidates",
                            "planned_meals": 0,
                        }
                    )
                return PreparedMealPlannerTurn(
                    turn_result=clarification,
                    prepared_action_payload={
                        "user_context": user_context,
                        "request_kind": request_kind,
                        "requested_culture": requested_culture,
                        "country_code": country_code.value if country_code is not None else None,
                        "effective_date": payload.effective_date.isoformat() if payload.effective_date is not None else None,
                        "requested_slots": requested_slots,
                        "missing_slots": missing_slots,
                    },
                    semantic_queries=semantic_queries,
                )

            await publish_progress(
                phase="ranking",
                progress=0.45,
                message="Ranking the strongest weekly combinations.",
                extra={"requested_slots": requested_slots, "missing_slots": missing_slots},
            )
            ranking_step_id = (
                recorder.start_step(
                    step_key="planner.bundle_ranking",
                    parent_step_id=recorder.root_step_id,
                    branch_key="ranking",
                    step_type="optimization",
                    input_data={
                        "slots": requested_slots,
                        "candidate_counts": {
                            slot_name: len(items)
                            for slot_name, items in slot_candidates.items()
                        },
                    },
                )
                if recorder is not None
                else None
            )
            ranking_started_at = time.perf_counter()
            ranked_bundles = await asyncio.to_thread(
                self._rank_meal_plan_bundles,
                current_user=current_user,
                slot_candidates=slot_candidates,
                user_context=user_context,
                requested_culture=requested_culture,
                country_code=country_code,
            )
            ranking_duration_ms = int((time.perf_counter() - ranking_started_at) * 1000)
            if recorder is not None and ranking_step_id is not None:
                recorder.complete_step(
                    step_id=ranking_step_id,
                    step_key="planner.bundle_ranking",
                    parent_step_id=recorder.root_step_id,
                    branch_key="ranking",
                    step_type="optimization",
                    output_data={
                        "ranked_bundle_count": len(ranked_bundles),
                        "bundle_ids": [str(item.get("bundle_id") or "") for item in ranked_bundles],
                    },
                    metrics={"duration_ms": ranking_duration_ms},
                )
            await publish_progress(
                phase="ranking",
                progress=0.6,
                message="Bundle ranking finished.",
                extra={"ranked_bundle_count": len(ranked_bundles)},
            )

            prepared_action_payload = self._build_meal_planner_action_payload(
                user_context=user_context,
                request_kind=request_kind,
                requested_culture=requested_culture,
                country_code=country_code,
                low_budget_mode=payload.low_budget_mode,
                allow_custom_meal_creation=payload.allow_custom_meal_creation,
                effective_date=payload.effective_date,
                selected_dates=self._selected_plan_dates(payload),
                requested_slots=requested_slots,
                missing_slots=missing_slots,
                slot_candidates=slot_candidates,
                ranked_bundles=ranked_bundles,
                monitoring_recorder=recorder,
            )

            await publish_progress(
                phase="planning",
                progress=0.72,
                message="Building the weekly plan.",
            )
            turn_result = await asyncio.to_thread(
                self._run_prepared_meal_planner,
                current_user=current_user,
                message=payload.message,
                request_type=payload.request_type,
                action_payload=prepared_action_payload,
                explicit_meal_type=payload.slot,
                explicit_country_code=country_code,
                conversation_id=payload.conversation_id,
                trace_id=trace_id,
                monitoring_recorder=recorder,
            )
            await publish_progress(
                phase="summarizing",
                progress=0.88,
                message="Checking pantry and cost coverage.",
            )
            enrich_step_id = (
                recorder.start_step(
                    step_key="planner.summary.enriched",
                    parent_step_id=recorder.root_step_id,
                    branch_key="summary",
                    step_type="summary",
                )
                if recorder is not None
                else None
            )
            turn_result = await asyncio.to_thread(
                self._enrich_prepared_meal_planner_turn,
                current_user=current_user,
                action_payload=prepared_action_payload,
                turn_result=turn_result,
            )
            if recorder is not None and enrich_step_id is not None:
                recorder.complete_step(
                    step_id=enrich_step_id,
                    step_key="planner.summary.enriched",
                    parent_step_id=recorder.root_step_id,
                    branch_key="summary",
                    step_type="summary",
                    output_data={
                        "has_bundle_summary": bool((turn_result.metadata or {}).get("bundle_summary")),
                        "has_inventory_summary": bool((turn_result.metadata or {}).get("inventory_summary")),
                        "has_cart_summary": bool((turn_result.metadata or {}).get("cart_summary")),
                    },
                )
            persist_step_id = (
                recorder.start_step(
                    step_key="planner.draft.persisted",
                    parent_step_id=recorder.root_step_id,
                    branch_key="persistence",
                    step_type="persistence",
                )
                if recorder is not None
                else None
            )
            saved_plan = self._persist_generated_meal_plan_draft(
                current_user=current_user,
                turn_result=turn_result,
                source_conversation_id=payload.conversation_id,
            )
            if recorder is not None and persist_step_id is not None:
                recorder.complete_step(
                    step_id=persist_step_id,
                    step_key="planner.draft.persisted",
                    parent_step_id=recorder.root_step_id,
                    branch_key="persistence",
                    step_type="persistence",
                    output_data={
                        "saved_plan_id": saved_plan.id if saved_plan is not None else None,
                        "view_mode": saved_plan.view_mode if saved_plan is not None else None,
                        "status": saved_plan.status if saved_plan is not None else None,
                    },
                )

            await realtime_delivery_service.deliver(
                user_id=current_user.id,
                delivery_type="meal_plan_generation",
                location="ios.home",
                payload={
                    "job_id": job_id,
                    "trace_id": trace_id,
                    "phase": "completed",
                    "progress": 1.0,
                    "message": "Your weekly plan is ready.",
                    "request_type": payload.request_type,
                    "view_mode": "week",
                    "effective_date": payload.effective_date.isoformat() if payload.effective_date is not None else None,
                    "assistant_text": turn_result.assistant_text,
                    "turn_mode": turn_result.turn_mode,
                    "ui_block": turn_result.ui_blocks[0] if turn_result.ui_blocks else None,
                    "planned_meals": turn_result.planned_meals,
                    "metadata": turn_result.metadata,
                },
                trace_id=trace_id,
                status="completed",
                channels=["websocket"],
                metadata={"source": "meal_planner", "job_id": job_id, "phase": "completed"},
            )
            if recorder is not None:
                recorder.complete_run(
                    summary={
                        "turn_mode": turn_result.turn_mode,
                        "planned_meals": len(turn_result.planned_meals),
                        "ui_blocks": len(turn_result.ui_blocks),
                    }
                )
            logger.info(
                "planner.service.weekly_async.completed trace_id=%s user_id=%s duration_ms=%s turn_mode=%s planned_meals=%s",
                trace_id or "-",
                current_user.id,
                int((time.perf_counter() - started_at) * 1000),
                turn_result.turn_mode,
                len(turn_result.planned_meals),
            )
            return PreparedMealPlannerTurn(
                turn_result=turn_result,
                prepared_action_payload=prepared_action_payload,
                semantic_queries=semantic_queries,
            )
        except Exception as exc:
            if recorder is not None:
                recorder.fail_run(
                    error={
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    }
                )
            raise

    def assert_plan_generation_allowed(
        self,
        *,
        current_user: User,
        payload: MealPlannerRequest,
    ) -> None:
        request_type = str(payload.request_type or "").strip().lower()
        if request_type not in {"generate_day_plan", "generate_week_plan", "generate_multi_day_plan"}:
            return

        effective_date = payload.effective_date or date.today()

        if request_type == "generate_day_plan":
            if self._has_existing_meal_for_day(
                user_id=current_user.id,
                target_date=effective_date,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"A meal plan already exists for {effective_date.isoformat()}. "
                        "Open or update the existing day plan instead."
                    ),
                )
            return

        conflict_dates: set[date] = set()
        selected_dates = set(self._selected_plan_dates(payload))
        range_start = min(selected_dates) if selected_dates else effective_date
        range_end = max(selected_dates) if selected_dates else effective_date
        for saved_plan in self._saved_meal_plan_repository.list_saved_day_plans_in_range(
            user_id=current_user.id,
            start_date=range_start,
            end_date=range_end,
        ):
            if saved_plan.effective_date is None or not self._saved_plan_has_meals(saved_plan):
                continue
            if selected_dates and saved_plan.effective_date not in selected_dates:
                continue
            conflict_dates.add(saved_plan.effective_date)

        weekly_plans = self._saved_meal_plan_repository.list_saved_weekly_plans_overlapping_range(
            user_id=current_user.id,
            start_date=range_start,
            end_date=range_end,
        )
        for weekly_plan in weekly_plans:
            conflict_dates.update(
                self._weekly_plan_conflict_dates(
                    saved_plan=weekly_plan,
                    start_date=range_start,
                    end_date=range_end,
                    selected_dates=selected_dates or None,
                )
            )

        if conflict_dates:
            ordered_dates = ", ".join(item.isoformat() for item in sorted(conflict_dates))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot create a weekly plan because meals already exist on "
                    f"{ordered_dates}. Open or update the existing plan instead."
                ),
            )

    def _has_existing_meal_for_day(self, *, user_id: str, target_date: date) -> bool:
        saved_day_plan = self._saved_meal_plan_repository.get_saved_day_plan_for_date(
            user_id=user_id,
            effective_date=target_date,
        )
        if self._saved_plan_has_meals(saved_day_plan):
            return True

        week_start, week_end = self._week_bounds(target_date)
        weekly_plan = self._saved_meal_plan_repository.get_saved_weekly_plan_for_week(
            user_id=user_id,
            week_start=week_start,
            week_end=week_end,
        )
        return bool(
            self._weekly_plan_conflict_dates(
                saved_plan=weekly_plan,
                start_date=target_date,
                end_date=target_date,
            )
        )

    def _saved_plan_has_meals(self, saved_plan: SavedMealPlan | None) -> bool:
        if saved_plan is None:
            return False
        if list(saved_plan.planned_meals or []):
            return True
        payload = dict(saved_plan.plan_payload or {})
        if saved_plan.view_mode == "week":
            return bool(
                self._weekly_plan_conflict_dates(
                    saved_plan=saved_plan,
                    start_date=saved_plan.week_start or saved_plan.effective_date or date.today(),
                    end_date=saved_plan.week_end or saved_plan.effective_date or date.today(),
                )
            )
        return self._sections_have_meals(list(payload.get("sections") or []))

    def _weekly_plan_conflict_dates(
        self,
        *,
        saved_plan: SavedMealPlan | None,
        start_date: date,
        end_date: date,
        selected_dates: set[date] | None = None,
    ) -> set[date]:
        if saved_plan is None:
            return set()

        conflict_dates: set[date] = set()
        payload = dict(saved_plan.plan_payload or {})
        for day_payload in list(payload.get("days") or []):
            if not isinstance(day_payload, dict):
                continue
            day_date = self._parse_effective_date(
                day_payload.get("date") or day_payload.get("effective_date")
            )
            if day_date is None or day_date < start_date or day_date > end_date:
                continue
            if selected_dates and day_date not in selected_dates:
                continue
            if self._sections_have_meals(list(day_payload.get("sections") or [])):
                conflict_dates.add(day_date)

        if conflict_dates:
            return conflict_dates

        if (
            start_date <= (saved_plan.effective_date or start_date) <= end_date
            and (
                not selected_dates
                or (saved_plan.effective_date or start_date) in selected_dates
            )
            and self._sections_have_meals(list(payload.get("sections") or []))
        ):
            conflict_dates.add(saved_plan.effective_date or start_date)
        return conflict_dates

    @staticmethod
    def _sections_have_meals(sections: list[dict[str, Any]]) -> bool:
        for section in sections:
            if not isinstance(section, dict):
                continue
            if list(section.get("items") or []):
                return True
        return False

    @staticmethod
    def _week_bounds(value: date) -> tuple[date, date]:
        week_start = value - timedelta(days=value.weekday())
        return week_start, week_start + timedelta(days=6)

    def get_conversation(
        self,
        *,
        current_user: User,
        conversation_id: str,
    ) -> ConversationSummaryResponse:
        conversation = self._require_owned_conversation(
            current_user=current_user,
            conversation_id=conversation_id,
        )
        return self._to_conversation_summary(conversation)

    def save_meal_planner_draft(
        self,
        *,
        current_user: User,
        payload: MealPlannerDraftSaveRequest,
    ) -> SavedMealPlan:
        return self.save_meal_planner_draft_result(
            current_user=current_user,
            payload=payload,
        ).saved_plan

    def save_meal_planner_draft_result(
        self,
        *,
        current_user: User,
        payload: MealPlannerDraftSaveRequest,
    ) -> MealPlannerDraftSaveResult:
        block = {
            "id": payload.ui_block.id,
            "block_type": payload.ui_block.block_type,
            "title": payload.ui_block.title,
            "payload": dict(payload.ui_block.payload),
        }
        user_goal = str((current_user.user_configuration or {}).get("goal") or "").strip() or None
        country_code_value = payload.country_code.value if payload.country_code is not None else None
        block["payload"], has_missing_groceries = self._refresh_plan_grocery_summaries(
            user_id=current_user.id,
            payload_data=dict(block.get("payload") or {}),
            country_code=country_code_value,
        )
        try:
            saved_plan, updated_payload, already_saved = self._persist_saved_plan_from_block(
                user_id=current_user.id,
                block=block,
                planned_meals=list(payload.planned_meals),
                meal_type=payload.meal_type.value if payload.meal_type is not None else None,
                country_code=country_code_value,
                requested_culture=payload.requested_culture,
                user_goal=user_goal,
                source_conversation_id="direct-planner",
                agent_type=payload.agent_type or "meal_planner_agent",
                plan_status="missing_groceries" if has_missing_groceries else "saved",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        notification_event = None
        if not already_saved and saved_plan.status == "saved":
            notification_event = {
                "type": "meal_plan_approved",
                "saved_plan_id": saved_plan.id,
                "snapshot_id": str(updated_payload.get("snapshot_id") or block.get("id") or ""),
                "view_mode": str(updated_payload.get("view_mode") or "day"),
                "period_label": str(updated_payload.get("period_label") or updated_payload.get("effective_date") or "").strip() or None,
                "conversation_id": str(saved_plan.source_conversation_id or "direct-planner"),
                "ui_block_id": str(block.get("id") or ""),
            }
        return MealPlannerDraftSaveResult(
            saved_plan=replace(saved_plan, plan_payload=dict(updated_payload)),
            notification_event=notification_event,
            already_saved=already_saved,
        )

    def get_current_conversation(
        self,
        *,
        current_user: User,
    ) -> CurrentConversationResponse:
        user_goal = self._require_user_goal(current_user)
        conversation = self._meal_conversation_repository.get_current_conversation(
            user_id=current_user.id,
            user_goal=user_goal,
        )
        return CurrentConversationResponse(
            conversation=self._to_conversation_summary(conversation) if conversation is not None else None
        )

    def list_messages(
        self,
        *,
        current_user: User,
        conversation_id: str,
        before: str | None,
        limit: int,
    ) -> ConversationMessagesResponse:
        self._require_owned_conversation(
            current_user=current_user,
            conversation_id=conversation_id,
        )
        messages, next_cursor = self._meal_conversation_repository.list_messages_page(
            conversation_id,
            before=before,
            limit=limit,
        )
        return ConversationMessagesResponse(
            items=[self._to_message_response(message) for message in messages],
            next_cursor=next_cursor,
        )

    def _run_assistant_turn(
        self,
        *,
        current_user: User,
        conversation: dict[str, Any],
        user_text: str,
        quick_action_type: str | None,
        action_payload: dict[str, Any],
        explicit_meal_type: MealType | None,
        explicit_country_code: CountryCode | None,
        trace_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started_at = time.perf_counter()
        runtime = self._build_runtime()
        graph = MealConversationGraph(runtime=runtime)
        turn_result = graph.run_turn(
            current_user=current_user,
            conversation_id=str(conversation["_id"]),
            conversation_history=self._meal_conversation_repository.list_recent_messages(
                str(conversation["_id"]),
                limit=self._settings.meal_conversation_history_window_messages,
            ),
            user_text=user_text,
            quick_action_type=quick_action_type,
            action_payload=action_payload,
            explicit_meal_type=explicit_meal_type,
            explicit_country_code=explicit_country_code,
            trace_id=trace_id,
        )
        logger.info(
            "planner.service.assistant_turn.completed trace_id=%s conversation_id=%s duration_ms=%s turn_mode=%s ui_blocks=%s quick_actions=%s planned_meals=%s",
            trace_id or "-",
            str(conversation["_id"]),
            int((time.perf_counter() - started_at) * 1000),
            turn_result.turn_mode,
            len(turn_result.ui_blocks),
            len(turn_result.quick_actions),
            len(turn_result.planned_meals),
        )
        if self._should_surface_turn_as_error(turn_result):
            raise MealConversationTurnDeliveryError(
                turn_result.assistant_text,
                issue=str(turn_result.metadata.get("issue") or "").strip() or None,
            )

        assistant_message = self._meal_conversation_repository.append_message(
            conversation_id=str(conversation["_id"]),
            role="assistant",
            text=turn_result.assistant_text,
            ui_blocks=turn_result.ui_blocks,
            quick_actions=turn_result.quick_actions,
            metadata={
                "agent_type": turn_result.agent_type,
                "target_domain": turn_result.target_domain,
                "request_kind": turn_result.metadata.get("request_kind"),
                "turn_mode": turn_result.turn_mode,
                "selected_meal_id": turn_result.selected_meal_id,
                "meal_source": turn_result.meal_source,
                "planned_meals": turn_result.planned_meals,
                "source": "conversation_turn",
                "trace_id": trace_id,
                **turn_result.metadata,
            },
        )
        updated_conversation = self._store_summary_for_assistant_message(
            conversation_id=str(conversation["_id"]),
            assistant_message=assistant_message,
            user_goal=str(conversation.get("user_goal") or "") or None,
            agent_type=turn_result.agent_type,
            meal_type=turn_result.meal_type,
            country_code=turn_result.country_code,
            selected_meal_id=turn_result.selected_meal_id,
            selected_meal_name=turn_result.selected_meal_name,
            meal_source=turn_result.meal_source,
            requested_culture=turn_result.requested_culture,
            last_user_intent=turn_result.last_user_intent or (user_text[:80] if user_text else "message"),
        )
        if updated_conversation is None:
            raise MealConversationNotFoundError
        return assistant_message, updated_conversation

    def _run_prepared_meal_planner(
        self,
        *,
        current_user: User,
        message: str,
        request_type: str,
        action_payload: dict[str, Any],
        explicit_meal_type: MealType | None,
        explicit_country_code: CountryCode | None,
        conversation_id: str | None,
        trace_id: str | None,
        monitoring_recorder: MealPlannerMonitoringRecorder | None = None,
    ) -> MealConversationTurnResult:
        runtime = self._build_runtime()
        planner = MealPlannerGraph(runtime=runtime)
        resolved_conversation_id = conversation_id or f"direct-planner-{uuid4().hex}"
        started_at = time.perf_counter()
        logger.info(
            "planner.service.prepared_turn.start trace_id=%s conversation_id=%s request_type=%s slots=%s",
            trace_id or "-",
            resolved_conversation_id,
            request_type,
            ",".join(sorted(k for k in action_payload.keys() if k.endswith("_slots"))) or "-",
        )
        turn_result = planner.run_turn(
            current_user=current_user,
            conversation_id=resolved_conversation_id,
            conversation_history=[],
            user_text=message,
            quick_action_type=request_type,
            action_payload=action_payload,
            explicit_meal_type=explicit_meal_type,
            explicit_country_code=explicit_country_code,
            trace_id=trace_id,
            monitoring_recorder=monitoring_recorder,
        )
        logger.info(
            "planner.service.prepared_turn.completed trace_id=%s conversation_id=%s request_type=%s turn_mode=%s planned_meals=%s duration_ms=%s",
            trace_id or "-",
            resolved_conversation_id,
            request_type,
            turn_result.turn_mode,
            len(turn_result.planned_meals),
            int((time.perf_counter() - started_at) * 1000),
        )
        return turn_result

    def _build_runtime(self) -> MealConversationRuntime:
        return MealConversationRuntime(
            user_repository=self._user_repository,
            meal_repository=self._meal_repository,
            grocery_repository=self._grocery_repository,
            meal_conversation_repository=self._meal_conversation_repository,
            saved_meal_plan_repository=self._saved_meal_plan_repository,
            openai_api_key=(
                self._settings.openai_api_key.get_secret_value()
                if self._settings.openai_api_key is not None
                else None
            ),
            model_name=self._settings.openai_meal_conversation_model,
            timeout_seconds=self._settings.openai_meal_conversation_timeout_seconds,
            embedding_model_name=self._settings.openai_meal_search_embedding_model,
            embedding_timeout_seconds=self._settings.openai_meal_search_embedding_timeout_seconds,
            semantic_candidate_pool_limit=self._settings.meal_semantic_search_candidate_pool_limit,
            semantic_embedding_batch_size=self._settings.meal_semantic_search_embedding_batch_size,
        )

    def _meal_semantic_search_service(self) -> MealSemanticSearchService:
        return MealSemanticSearchService(
            self._meal_repository,
            MealSearchEmbeddingService(
                api_key=(
                    self._settings.openai_api_key.get_secret_value()
                    if self._settings.openai_api_key is not None
                    else None
                ),
                model_name=self._settings.openai_meal_search_embedding_model,
                timeout_seconds=self._settings.openai_meal_search_embedding_timeout_seconds,
            ),
            candidate_pool_limit=self._settings.meal_semantic_search_candidate_pool_limit,
            embedding_batch_size=self._settings.meal_semantic_search_embedding_batch_size,
        )

    @staticmethod
    def _build_meal_planner_user_context(current_user: User) -> dict[str, Any]:
        configuration = dict(current_user.user_configuration or {})
        context = {
            "goal": (str(configuration.get("goal") or "").strip() or None),
            "weekly_budget": MealConversationService._normalized_positive_int(configuration.get("weekly_budget")),
            "household_size": MealConversationService._normalized_positive_int(configuration.get("household_size")),
            "culture_preferences": MealConversationService._normalized_string_list(configuration.get("culture_preferences")),
            "diet_rules": MealConversationService._normalized_string_list(configuration.get("diet_rules")),
            "allergies": MealConversationService._normalized_string_list(configuration.get("allergies")),
            "selected_plan_types": MealConversationService._normalized_string_list(configuration.get("selected_plan_types")),
        }
        if any(
            value
            for value in (
                context["goal"],
                context["weekly_budget"],
                context["culture_preferences"],
                context["diet_rules"],
                context["allergies"],
            )
        ):
            return context
        return {}

    @staticmethod
    def _preferred_culture(user_context: dict[str, Any]) -> str | None:
        preferences = list(user_context.get("culture_preferences") or [])
        return preferences[0] if preferences else None

    @staticmethod
    def _planner_view_mode(request_type: str) -> str:
        return "week" if request_type in {"generate_week_plan", "generate_multi_day_plan"} else "day"

    def _start_meal_planner_monitoring(
        self,
        *,
        current_user: User,
        payload: MealPlannerRequest,
        trace_id: str | None,
    ) -> MealPlannerMonitoringRecorder | None:
        requested_slots = [slot.value for slot in payload.slots]
        return meal_planner_monitoring_service.start_run(
            user_id=current_user.id,
            trace_id=trace_id,
            request_type=payload.request_type,
            view_mode=self._planner_view_mode(payload.request_type),
            effective_date=payload.effective_date,
            metadata={
                "requested_slots": requested_slots,
                "candidate_limit_per_slot": payload.candidate_limit_per_slot,
                "requested_culture": payload.requested_culture,
                "country_code": payload.country_code.value if payload.country_code is not None else None,
                "low_budget_mode": payload.low_budget_mode,
                "allow_custom_meal_creation": payload.allow_custom_meal_creation,
            },
        )

    @staticmethod
    def _planner_request_kind(payload: MealPlannerRequest) -> str:
        if payload.request_type == "generate_week_plan":
            return "week_plan_request"
        if payload.request_type == "generate_multi_day_plan":
            return "multi_day_plan_request"
        if len(payload.slots) > 1:
            return "day_plan_request"
        if payload.request_type in {"swap_meal", "make_cheaper", "more_protein", "filter_culture"}:
            return "meal_slot_request"
        return "meal_slot_request"

    def _build_semantic_query(
        self,
        *,
        message: str,
        request_type: str,
        slot: MealType,
        user_context: dict[str, Any],
        requested_culture: str | None,
        low_budget_mode: bool,
    ) -> str:
        type_hints = {
            "make_cheaper": "budget friendly affordable lower cost",
            "more_protein": "high protein protein rich",
            "filter_culture": f"{requested_culture or ''} cuisine".strip(),
            "swap_meal": "good replacement option",
            "generate_day_plan": "balanced meal plan option",
            "generate_week_plan": "balanced weekly meal plan with ingredient reuse and low waste",
            "generate_multi_day_plan": "balanced multi day meal plan across the selected dates with ingredient reuse and low waste",
        }
        parts = [
            f"{slot.value} meal",
            message.strip(),
            type_hints.get(request_type, ""),
            f"goal {user_context.get('goal')}" if user_context.get("goal") else "",
            f"cuisine {requested_culture}" if requested_culture else "",
            "budget friendly affordable lower cost" if low_budget_mode else "",
        ]
        return ". ".join(part for part in parts if part)

    def _retrieve_slot_candidates(
        self,
        *,
        search_service: MealSemanticSearchService,
        slot: MealType,
        semantic_query: str,
        user_context: dict[str, Any],
        requested_culture: str | None,
        country_code: CountryCode | None,
        low_budget_mode: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        items = search_service.search(
            semantic_query=semantic_query,
            meal_type=slot.value,
            requested_culture=requested_culture,
            diet_rules=list(user_context.get("diet_rules") or []),
            allergies=list(user_context.get("allergies") or []),
            country_code=country_code.value if country_code is not None else None,
            low_budget_mode=low_budget_mode,
            goal=user_context.get("goal"),
            limit=limit,
        )
        return [self._meal_planner_candidate_payload(item) for item in items]

    @staticmethod
    def _meal_planner_candidate_payload(item: MealSemanticSearchItem) -> dict[str, Any]:
        meal = item.meal
        return {
            "id": meal.id,
            "name": meal.name,
            "meal_type": meal.meal_type.value,
            "hero_image_url": meal.hero_image_url,
            "servings": meal.servings,
            "prep_time_minutes": meal.prep_time_minutes,
            "cook_time_minutes": meal.cook_time_minutes,
            "culture_tags": list(meal.culture_tags),
            "description": meal.description,
            "diet_rules_supported": list(meal.diet_rules_supported),
            "allergy_exclusions": list(meal.allergy_exclusions),
            "estimated_costs": [
                {
                    "country_code": cost.country_code.value,
                    "currency_code": cost.currency_code.value,
                    "amount": cost.amount,
                }
                for cost in meal.estimated_costs
            ],
            "ingredient_items": [
                {
                    "id": ingredient.id,
                    "name": ingredient.name,
                    "quantity": ingredient.quantity,
                    "unit": ingredient.unit,
                    "optional": ingredient.optional,
                    "linked_product_ids": list(ingredient.linked_product_ids),
                }
                for ingredient in meal.ingredient_items
            ],
            "linked_product_ids": list(meal.linked_product_ids),
            "difficulty": meal.difficulty.value,
            "nutrition_summary": {
                "calories": meal.nutrition_summary.calories,
                "protein_g": meal.nutrition_summary.protein_g,
                "carbs_g": meal.nutrition_summary.carbs_g,
                "fat_g": meal.nutrition_summary.fat_g,
            },
            "recipe_steps": list(meal.recipe_steps),
        }

    def _enrich_prepared_meal_planner_turn(
        self,
        *,
        current_user: User,
        action_payload: dict[str, Any],
        turn_result: MealConversationTurnResult,
    ) -> MealConversationTurnResult:
        planned_meals = list(turn_result.planned_meals or [])
        if not planned_meals:
            return turn_result

        user_context = dict(action_payload.get("user_context") or {})
        household_size = self._normalized_positive_int(user_context.get("household_size")) or 1
        ui_blocks = list(turn_result.ui_blocks or [])
        weekly_summary_source = self._weekly_summary_source_from_ui_blocks(ui_blocks=ui_blocks)
        meals_by_slot = self._selected_meals_from_payload(
            action_payload=action_payload,
            planned_meals=planned_meals,
        )
        if weekly_summary_source is None and not meals_by_slot:
            return turn_result

        costing_service = MealPlanCostingService(self._grocery_repository)
        inventory_service = MealInventoryReconciliationService()
        cart_service = MealPlanCartService()
        summary_meals = (
            weekly_summary_source["meals_by_key"]
            if weekly_summary_source is not None
            else meals_by_slot
        )
        period_days = 7 if weekly_summary_source is not None else 1
        weekly_budget = self._normalized_positive_int(user_context.get("weekly_budget"))
        period_budget = (
            weekly_budget * (period_days / 7.0)
            if weekly_budget is not None and weekly_budget > 0
            else None
        )
        demand_summary = costing_service.build_product_demands(
            meals_by_slot=summary_meals,
            household_size=household_size,
        )
        pantry_items = self._kitchen_service.list_planning_items(user_id=current_user.id)
        inventory_summary = inventory_service.reconcile(
            product_demands=list(demand_summary.get("product_demands") or []),
            pantry_items=pantry_items,
        )
        country_code = (
            turn_result.country_code.value
            if turn_result.country_code is not None
            else str(action_payload.get("country_code") or "").strip() or None
        )
        cart_summary = costing_service.summarize_cart(
            shortages=list(inventory_summary.get("shortages") or []),
            products_by_id=dict(demand_summary.get("products_by_id") or {}),
            country_code=country_code,
            target_budget=period_budget,
        )
        bundle_summary = cart_service.build_bundle_summary(
            planned_meals=planned_meals,
            household_size=household_size,
            weekly_budget=weekly_budget,
            shared_product_count=int(demand_summary.get("shared_product_count") or 0),
            cart_summary=cart_summary,
            meal_count=weekly_summary_source["meal_count"] if weekly_summary_source is not None else None,
            period_days=period_days,
        )

        updated_ui_blocks = self._attach_plan_summaries_to_ui_blocks(
            ui_blocks=ui_blocks,
            bundle_summary=bundle_summary,
            inventory_summary=inventory_summary,
            cart_summary=cart_summary,
        )
        updated_metadata = dict(turn_result.metadata or {})
        updated_metadata["bundle_summary"] = bundle_summary
        updated_metadata["inventory_summary"] = inventory_summary
        updated_metadata["cart_summary"] = cart_summary
        return replace(
            turn_result,
            ui_blocks=updated_ui_blocks,
            metadata=updated_metadata,
        )

    def _weekly_summary_source_from_ui_blocks(
        self,
        *,
        ui_blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for block in ui_blocks:
            if str(block.get("block_type") or "") != "meal_plan_week":
                continue
            payload = dict(block.get("payload") or {})
            days = list(payload.get("days") or [])
            if not days:
                return None

            meals_by_key: dict[str, dict[str, Any]] = {}
            meal_count = 0
            for day_index, day in enumerate(days):
                day_date = str(day.get("date") or payload.get("effective_date") or f"day-{day_index}").strip()
                for section_index, section in enumerate(list(day.get("sections") or []), start=1):
                    slot = str(section.get("slot") or "").strip().lower()
                    if not slot:
                        continue
                    for item_index, item in enumerate(list(section.get("items") or []), start=1):
                        if not isinstance(item, dict):
                            continue
                        meal_count += 1
                        if str(item.get("source_type") or "").strip().lower() == "leftover":
                            continue
                        synthetic_meal = self._weekly_fresh_meal_payload_from_item(
                            slot=slot,
                            item=item,
                            date_key=day_date,
                            section_index=section_index,
                            item_index=item_index,
                        )
                        if synthetic_meal is None:
                            continue
                        meals_by_key[f"{day_date}:{slot}:{section_index}:{item_index}"] = synthetic_meal

            if not meals_by_key:
                return None
            return {
                "meals_by_key": meals_by_key,
                "meal_count": meal_count,
            }
        return None

    def _weekly_fresh_meal_payload_from_item(
        self,
        *,
        slot: str,
        item: dict[str, Any],
        date_key: str,
        section_index: int,
        item_index: int,
    ) -> dict[str, Any] | None:
        meal_detail = dict(item.get("meal_detail") or {})
        raw_ingredients = list(meal_detail.get("ingredients") or [])
        ingredient_items: list[dict[str, Any]] = []
        for ingredient in raw_ingredients:
            if not isinstance(ingredient, dict):
                continue
            ingredient_items.append(
                {
                    "id": ingredient.get("id") or f"ingredient-{item_index}",
                    "name": str(ingredient.get("name") or "").strip(),
                    "quantity": ingredient.get("quantity"),
                    "unit": str(ingredient.get("unit") or "").strip(),
                    "optional": bool(ingredient.get("optional", False)),
                    "linked_product_ids": list(ingredient.get("linked_product_ids") or []),
                }
            )
        if not ingredient_items:
            return None

        planned_servings = self._normalized_float(
            item.get("yield_servings")
            or meal_detail.get("yield_servings")
            or item.get("planned_servings")
            or meal_detail.get("planned_servings")
        )
        servings = self._normalized_float(meal_detail.get("servings") or item.get("servings")) or 1.0
        return {
            "id": item.get("meal_id") or f"{date_key}:{slot}:{section_index}:{item_index}",
            "name": str(item.get("name") or meal_detail.get("name") or "Planned meal").strip(),
            "servings": servings,
            "planned_servings": planned_servings,
            "ingredient_items": ingredient_items,
        }

    def _selected_meals_from_payload(
        self,
        *,
        action_payload: dict[str, Any],
        planned_meals: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        meals_by_slot: dict[str, dict[str, Any]] = {}
        for item in planned_meals:
            slot = str(item.get("slot") or "").strip().lower()
            if not slot:
                continue
            selected_id = str(item.get("meal_id") or "").strip()
            selected_name = str(item.get("meal_name") or "").strip().lower()
            candidates = list(action_payload.get(f"{slot}_slots") or [])
            for candidate in candidates:
                candidate_id = str(candidate.get("id") or "").strip()
                candidate_name = str(candidate.get("name") or "").strip().lower()
                if (selected_id and candidate_id == selected_id) or (selected_name and candidate_name == selected_name):
                    meals_by_slot[slot] = dict(candidate)
                    break
        return meals_by_slot

    @staticmethod
    def _attach_plan_summaries_to_ui_blocks(
        *,
        ui_blocks: list[dict[str, Any]],
        bundle_summary: dict[str, Any],
        inventory_summary: dict[str, Any],
        cart_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        updated_blocks: list[dict[str, Any]] = []
        for block in ui_blocks:
            updated_block = dict(block)
            if updated_block.get("block_type") in {"meal_plan_draft", "meal_plan_week"}:
                payload = dict(updated_block.get("payload") or {})
                payload["bundle_summary"] = bundle_summary
                payload["inventory_summary"] = inventory_summary
                payload["cart_summary"] = cart_summary
                payload["week_summary"] = MealConversationService._build_week_summary_payload(
                    payload=payload,
                    bundle_summary=bundle_summary,
                    inventory_summary=inventory_summary,
                    cart_summary=cart_summary,
                )
                payload["day_briefs"] = MealConversationService._build_day_briefs_payload(
                    payload=payload,
                )
                updated_block["payload"] = payload
            updated_blocks.append(updated_block)
        return updated_blocks

    @staticmethod
    def _build_week_summary_payload(
        *,
        payload: dict[str, Any],
        bundle_summary: dict[str, Any],
        inventory_summary: dict[str, Any],
        cart_summary: dict[str, Any],
    ) -> dict[str, Any]:
        days = list(payload.get("days") or [])
        daily_snapshots = list(payload.get("daily_snapshots") or [])
        meal_count = 0
        for day in days:
            if not isinstance(day, dict):
                continue
            for section in list(day.get("sections") or []):
                if not isinstance(section, dict):
                    continue
                meal_count += len([item for item in list(section.get("items") or []) if isinstance(item, dict)])
        day_count = len(days) or len(daily_snapshots)
        used_items_count = int(inventory_summary.get("used_items_count") or 0)
        shared_product_count = int(bundle_summary.get("shared_product_count") or 0)
        items_to_buy_count = int(cart_summary.get("items_to_buy_count") or 0)
        estimated_total_cost = cart_summary.get("estimated_total_cost")
        formatted_estimated_total_cost = (
            cart_summary.get("formatted_estimated_total_cost")
            or bundle_summary.get("formatted_estimated_total_cost")
        )
        budget_status = str(bundle_summary.get("budget_status") or "unknown")
        reuse_score = min(shared_product_count * 20 + used_items_count * 8, 100)
        pantry_coverage_label = (
            f"{used_items_count} pantry match{'es' if used_items_count != 1 else ''}"
            if used_items_count > 0
            else "No pantry matches yet"
        )
        waste_label = (
            "Leftovers are planned into the week"
            if any(
                str(item.get("source_type") or "").lower() == "leftover"
                for day in days
                if isinstance(day, dict)
                for section in list(day.get("sections") or [])
                if isinstance(section, dict)
                for item in list(section.get("items") or [])
                if isinstance(item, dict)
            )
            else "Fresh meals only"
        )
        return {
            "day_count": day_count,
            "meal_count": meal_count,
            "budget_status": budget_status,
            "estimated_total_cost": estimated_total_cost,
            "formatted_estimated_total_cost": formatted_estimated_total_cost,
            "items_to_buy_count": items_to_buy_count,
            "shared_product_count": shared_product_count,
            "used_items_count": used_items_count,
            "depleted_items_count": int(inventory_summary.get("depleted_items_count") or 0),
            "reuse_score": reuse_score,
            "pantry_coverage_label": pantry_coverage_label,
            "waste_label": waste_label,
        }

    @staticmethod
    def _build_day_briefs_payload(*, payload: dict[str, Any]) -> list[dict[str, Any]]:
        daily_snapshots = list(payload.get("daily_snapshots") or [])
        snapshot_by_day_id = {
            str(snapshot.get("parent_day_id") or ""): dict(snapshot)
            for snapshot in daily_snapshots
            if str(snapshot.get("parent_day_id") or "").strip()
        }
        day_briefs: list[dict[str, Any]] = []
        for day in list(payload.get("days") or []):
            if not isinstance(day, dict):
                continue
            sections = [
                section for section in list(day.get("sections") or []) if isinstance(section, dict)
            ]
            meal_names: list[str] = []
            source_types: list[str] = []
            for section in sections:
                for item in list(section.get("items") or []):
                    if not isinstance(item, dict):
                        continue
                    meal_name = str(item.get("name") or "").strip()
                    if meal_name and meal_name not in meal_names:
                        meal_names.append(meal_name)
                    source_type = str(item.get("source_type") or "").strip()
                    if source_type and source_type not in source_types:
                        source_types.append(source_type)

            snapshot = snapshot_by_day_id.get(str(day.get("id") or ""))
            day_briefs.append(
                {
                    "id": day.get("id"),
                    "date": day.get("date"),
                    "accent_label": day.get("accent_label"),
                    "full_label": day.get("full_label"),
                    "calories": day.get("calories"),
                    "tracked_text": day.get("tracked_text"),
                    "item_count": sum(len(list(section.get("items") or [])) for section in sections),
                    "meal_names": meal_names[:3],
                    "source_types": source_types[:3],
                    "has_details": bool(snapshot and list(snapshot.get("sections") or [])),
                    "snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
                }
            )
        return day_briefs

    @staticmethod
    def _build_meal_planner_action_payload(
        *,
        user_context: dict[str, Any],
        request_kind: str,
        requested_culture: str | None,
        country_code: CountryCode | None,
        low_budget_mode: bool,
        allow_custom_meal_creation: bool,
        effective_date: date | None,
        selected_dates: list[date],
        requested_slots: list[str],
        missing_slots: list[str],
        slot_candidates: dict[str, list[dict[str, Any]]],
        ranked_bundles: list[dict[str, Any]],
        monitoring_recorder: MealPlannerMonitoringRecorder | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_context": user_context,
            "request_kind": request_kind,
            "requested_culture": requested_culture,
            "country_code": country_code.value if country_code is not None else None,
            "low_budget_mode": low_budget_mode,
            "allow_custom_meal_creation": allow_custom_meal_creation,
            "effective_date": effective_date.isoformat() if effective_date is not None else None,
            "selected_dates": [item.isoformat() for item in selected_dates],
            "requested_slots": list(requested_slots),
            "missing_slots": list(missing_slots),
            "ranked_bundles": ranked_bundles,
        }
        if monitoring_recorder is not None:
            payload["monitoring"] = {
                "run_id": monitoring_recorder.run_id,
                "trace_id": monitoring_recorder.trace_id,
                "root_step_id": monitoring_recorder.root_step_id,
            }
        for slot_name, candidates in slot_candidates.items():
            payload[f"{slot_name}_slots"] = list(candidates)
        return payload

    def _selected_plan_dates(self, payload: MealPlannerRequest) -> list[date]:
        effective_date = payload.effective_date or date.today()
        normalized = sorted({item for item in payload.selected_dates if item >= effective_date})
        if normalized:
            return normalized
        if payload.request_type == "generate_week_plan":
            _, week_end = self._week_bounds(effective_date)
            return [
                effective_date + timedelta(days=offset)
                for offset in range((week_end - effective_date).days + 1)
            ]
        return [effective_date]

    def _rank_meal_plan_bundles(
        self,
        *,
        current_user: User,
        slot_candidates: dict[str, list[dict[str, Any]]],
        user_context: dict[str, Any],
        requested_culture: str | None,
        country_code: CountryCode | None,
    ) -> list[dict[str, Any]]:
        optimization_service = MealPlanOptimizationService(
            costing_service=MealPlanCostingService(self._grocery_repository),
            inventory_service=MealInventoryReconciliationService(),
            cart_service=MealPlanCartService(),
        )
        pantry_items = self._kitchen_service.list_planning_items(user_id=current_user.id)
        return optimization_service.rank_bundles(
            slot_candidates=slot_candidates,
            user_context=user_context,
            pantry_items=pantry_items,
            country_code=country_code.value if country_code is not None else None,
            requested_culture=requested_culture,
        )

    @staticmethod
    def _build_planner_clarification_result(
        *,
        assistant_text: str,
        issue: str,
        requested_culture: str | None,
        meal_type: MealType | None,
        country_code: CountryCode | None,
    ) -> MealConversationTurnResult:
        return MealConversationTurnResult(
            assistant_text=assistant_text,
            turn_mode="clarification_request",
            agent_type="meal_planner_agent",
            target_domain="meal_planning",
            meal_type=meal_type,
            country_code=country_code,
            requested_culture=requested_culture,
            metadata={"issue": issue},
        )

    @staticmethod
    def _should_surface_turn_as_error(turn_result: Any) -> bool:
        metadata = dict(getattr(turn_result, "metadata", {}) or {})
        issue = str(metadata.get("issue") or "").strip()
        if not issue:
            return False
        planned_meals = list(getattr(turn_result, "planned_meals", []) or [])
        ui_blocks = list(getattr(turn_result, "ui_blocks", []) or [])
        turn_mode = str(getattr(turn_result, "turn_mode", "") or "")
        return (
            turn_mode == "conversation_reply"
            and not planned_meals
            and not ui_blocks
        )

    def _latest_user_message_for_trace(
        self,
        *,
        conversation_id: str,
        trace_id: str | None,
        fallback_text: str,
    ) -> dict[str, Any]:
        recent_messages = self._meal_conversation_repository.list_recent_messages(conversation_id, limit=10)
        for message in reversed(recent_messages):
            if message.get("role") != "user":
                continue
            metadata = dict(message.get("metadata") or {})
            if trace_id and metadata.get("trace_id") == trace_id:
                return message
        for message in reversed(recent_messages):
            if message.get("role") == "user" and str(message.get("text") or "").strip() == fallback_text:
                return message
        raise MealConversationNotFoundError

    def _require_owned_conversation(
        self,
        *,
        current_user: User,
        conversation_id: str,
    ) -> dict[str, Any]:
        conversation = self._meal_conversation_repository.get_conversation(conversation_id)
        if conversation is None:
            raise MealConversationNotFoundError
        if str(conversation["user_id"]) != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
        return conversation

    @staticmethod
    def _require_user_goal(current_user: User) -> str:
        configuration = dict(current_user.user_configuration or {})
        goal = str(configuration.get("goal") or "").strip()
        if not goal:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User goal is required to start or resume a meal planning conversation.",
            )
        return goal

    @staticmethod
    def _text_preview(text: str, limit: int = 120) -> str:
        normalized = text.replace("\n", " ").strip()
        if not normalized:
            return "-"
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + "..."

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
    def _normalized_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_summary_payload(
        *,
        user_goal: str | None,
        agent_type: str,
        meal_type: MealType | None,
        country_code: CountryCode | None,
        selected_meal_id: str | None = None,
        selected_meal_name: str | None = None,
        meal_source: str | None = None,
        planned_meals: list[dict[str, Any]] | None = None,
        requested_culture: str | None = None,
        last_user_intent: str | None = None,
        last_assistant_preview: str | None = None,
        latest_ui_blocks: list[dict[str, Any]] | None = None,
        latest_quick_actions: list[dict[str, Any]] | None = None,
        latest_message_id: str | None = None,
        message_count: int | None = None,
        last_message_at: Any | None = None,
    ) -> dict[str, Any]:
        payload = {
            "user_goal": user_goal,
            "agent_type": agent_type,
            "meal_type": meal_type.value if meal_type is not None else None,
            "country_code": country_code.value if country_code is not None else None,
            "planned_meals": planned_meals or [],
            "selected_meal_id": selected_meal_id,
            "selected_meal_name": selected_meal_name,
            "meal_source": meal_source,
            "requested_culture": requested_culture,
            "last_user_intent": last_user_intent,
            "last_assistant_preview": last_assistant_preview,
            "latest_ui_blocks": latest_ui_blocks or [],
            "latest_message_id": latest_message_id,
            "message_count": message_count or 0,
            "last_message_at": last_message_at,
        }
        if latest_quick_actions:
            payload["latest_quick_actions"] = latest_quick_actions
        return payload

    @staticmethod
    def _to_message_response(document: dict[str, Any]) -> ConversationMessageResponse:
        return ConversationMessageResponse(
            id=str(document["_id"]),
            conversation_id=str(document["conversation_id"]),
            role=str(document["role"]),
            text=str(document.get("text", "")),
            ui_blocks=[
                ConversationUIBlockResponse.model_validate(block)
                for block in document.get("ui_blocks", [])
            ],
            quick_actions=[
                ConversationQuickActionResponse.model_validate(action)
                for action in document.get("quick_actions", [])
            ],
            metadata=dict(document.get("metadata", {})),
            created_at=document["created_at"],
        )

    @staticmethod
    def _to_conversation_summary(document: dict[str, Any]) -> ConversationSummaryResponse:
        summary = dict(document.get("current_summary") or {})
        meal_type = summary.get("meal_type")
        country_code = summary.get("country_code")
        return ConversationSummaryResponse(
            conversation_id=str(document["_id"]),
            agent_type=str(document.get("agent_type", summary.get("agent_type", MEAL_COORDINATOR_AGENT_TYPE))),
            status=str(document.get("status", "active")),
            meal_type=MealType(str(meal_type)) if meal_type else None,
            planned_meals=list(summary.get("planned_meals", [])),
            selected_meal_id=summary.get("selected_meal_id"),
            selected_meal_name=summary.get("selected_meal_name"),
            meal_source=summary.get("meal_source"),
            last_user_intent=summary.get("last_user_intent"),
            last_assistant_preview=summary.get("last_assistant_preview"),
            latest_ui_blocks=[
                ConversationUIBlockResponse.model_validate(block)
                for block in summary.get("latest_ui_blocks", [])
            ],
            latest_quick_actions=[
                ConversationQuickActionResponse.model_validate(action)
                for action in summary.get("latest_quick_actions", [])
            ],
            latest_message_id=summary.get("latest_message_id") or document.get("latest_message_id"),
            message_count=int(summary.get("message_count") or document.get("message_count") or 0),
            country_code=CountryCode(str(country_code)) if country_code else None,
            requested_culture=summary.get("requested_culture"),
            last_message_at=document.get("last_message_at") or summary.get("last_message_at"),
            updated_at=document["updated_at"],
            created_at=document["created_at"],
        )

    def _store_summary_for_assistant_message(
        self,
        *,
        conversation_id: str,
        assistant_message: dict[str, Any],
        user_goal: str | None,
        agent_type: str,
        meal_type: MealType | None,
        country_code: CountryCode | None,
        selected_meal_id: str | None,
        selected_meal_name: str | None,
        meal_source: str | None,
        requested_culture: str | None,
        last_user_intent: str | None,
    ) -> dict[str, Any] | None:
        conversation = self._meal_conversation_repository.get_conversation(conversation_id)
        planned_meals = list((assistant_message.get("metadata") or {}).get("planned_meals", []))
        return self._meal_conversation_repository.store_turn_result(
            conversation_id=conversation_id,
            user_goal=user_goal,
            agent_type=agent_type,
            status="active",
            current_summary=self._build_summary_payload(
                user_goal=user_goal,
                agent_type=agent_type,
                meal_type=meal_type,
                country_code=country_code,
                planned_meals=planned_meals,
                selected_meal_id=selected_meal_id,
                selected_meal_name=selected_meal_name,
                meal_source=meal_source,
                requested_culture=requested_culture,
                last_user_intent=last_user_intent,
                last_assistant_preview=str(assistant_message.get("text", ""))[:240] or None,
                latest_ui_blocks=list(assistant_message.get("ui_blocks", [])),
                latest_quick_actions=list(assistant_message.get("quick_actions", [])),
                latest_message_id=str(assistant_message["_id"]),
                message_count=int(conversation.get("message_count") or 0) if conversation else 0,
                last_message_at=(conversation or {}).get("last_message_at") or assistant_message.get("created_at"),
            ),
        )

    def _save_meal_plan_snapshot(
        self,
        *,
        conversation: dict[str, Any],
        payload: SendConversationMessageRequest,
        trace_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        summary = dict(conversation.get("current_summary") or {})
        planned_meals = list(summary.get("planned_meals") or [])
        latest_ui_blocks = list(summary.get("latest_ui_blocks") or [])
        requested_snapshot_id = str(payload.action_payload.get("snapshot_id") or "").strip()

        matched_block = False
        already_saved = False
        saved_plan_id: str | None = None
        effective_date: date | None = None
        notification_event: dict[str, Any] | None = None
        updated_blocks: list[dict[str, Any]] = []
        for block in latest_ui_blocks:
            updated_block = dict(block)
            if (
                updated_block.get("block_type") in {"meal_plan_draft", "meal_plan_week"}
                and (
                    not requested_snapshot_id
                    or requested_snapshot_id == str((updated_block.get("payload") or {}).get("snapshot_id") or updated_block.get("id") or "")
                )
            ):
                matched_block = True
                saved_plan, payload_data, already_saved = self._persist_saved_plan_from_block(
                    user_id=str(conversation["user_id"]),
                    block=updated_block,
                    planned_meals=planned_meals,
                    meal_type=summary.get("meal_type"),
                    country_code=summary.get("country_code"),
                    requested_culture=summary.get("requested_culture"),
                    user_goal=str(conversation.get("user_goal") or "") or None,
                    source_conversation_id=str(conversation["_id"]),
                    agent_type=str(conversation.get("agent_type") or MEAL_COORDINATOR_AGENT_TYPE),
                )
                saved_plan_id = saved_plan.id
                effective_date = self._parse_effective_date(payload_data.get("effective_date"))
                if not already_saved:
                    notification_event = {
                        "type": "meal_plan_approved",
                        "saved_plan_id": saved_plan.id,
                        "snapshot_id": str(payload_data.get("snapshot_id") or updated_block.get("id") or ""),
                        "view_mode": str(payload_data.get("view_mode") or "day"),
                        "period_label": str(payload_data.get("period_label") or payload_data.get("effective_date") or "").strip() or None,
                        "conversation_id": str(conversation["_id"]),
                        "ui_block_id": str(updated_block.get("id") or ""),
                    }
                updated_block["payload"] = payload_data
            updated_blocks.append(updated_block)

        if not matched_block:
            assistant_text = "I could not find that draft anymore. Ask me to generate the latest plan again."
            assistant_ui_blocks: list[dict[str, Any]] = []
            turn_mode = "conversation_reply"
        else:
            saved_view_mode = str((updated_blocks[0].get("payload") or {}).get("view_mode") or "day") if updated_blocks else "day"
            if already_saved:
                assistant_text = "This weekly plan is already saved." if saved_view_mode == "week" else "This meal is already saved."
            else:
                assistant_text = "Weekly plan saved." if saved_view_mode == "week" else "Meal saved."
            assistant_ui_blocks = updated_blocks
            turn_mode = "day_plan_updated"

        assistant_message = self._meal_conversation_repository.append_message(
            conversation_id=str(conversation["_id"]),
            role="assistant",
            text=assistant_text,
            ui_blocks=assistant_ui_blocks,
            quick_actions=[],
            metadata={
                "agent_type": str(conversation.get("agent_type") or MEAL_COORDINATOR_AGENT_TYPE),
                "target_domain": "meal_planning",
                "request_kind": "save_meal_plan",
                "turn_mode": turn_mode,
                "selected_meal_id": summary.get("selected_meal_id"),
                "meal_source": summary.get("meal_source"),
                "saved_plan_id": saved_plan_id,
                "planned_meals": planned_meals,
                "source": "conversation_turn",
                "trace_id": trace_id,
                "notification_event": notification_event,
            },
        )
        updated_conversation = self._store_summary_for_assistant_message(
            conversation_id=str(conversation["_id"]),
            assistant_message=assistant_message,
            user_goal=str(conversation.get("user_goal") or "") or None,
            agent_type=str(conversation.get("agent_type") or MEAL_COORDINATOR_AGENT_TYPE),
            meal_type=MealType(str(summary["meal_type"])) if summary.get("meal_type") else None,
            country_code=CountryCode(str(summary["country_code"])) if summary.get("country_code") else None,
            selected_meal_id=summary.get("selected_meal_id"),
            selected_meal_name=summary.get("selected_meal_name"),
            meal_source=summary.get("meal_source"),
            requested_culture=summary.get("requested_culture"),
            last_user_intent="save_meal_plan",
        )
        if updated_conversation is None:
            raise MealConversationNotFoundError
        return assistant_message, updated_conversation

    def _persist_saved_plan_from_block(
        self,
        *,
        user_id: str,
        block: dict[str, Any],
        planned_meals: list[dict[str, Any]],
        meal_type: str | None,
        country_code: str | None,
        requested_culture: str | None,
        user_goal: str | None,
        source_conversation_id: str,
        agent_type: str,
        plan_status: str = "saved",
    ) -> tuple[SavedMealPlan, dict[str, Any], bool]:
        payload_data = dict(block.get("payload") or {})
        normalized_planned_meals = list(planned_meals or self._build_planned_meals_from_sections(payload_data.get("sections") or []))
        if str(block.get("block_type") or "") not in {"meal_plan_draft", "meal_plan_week"}:
            raise ValueError("Unsupported meal plan draft block type.")
        snapshot_id = str(payload_data.get("snapshot_id") or block.get("id") or "").strip()
        if not snapshot_id:
            raise ValueError("Meal plan draft is missing snapshot_id.")
        existing_saved_plan = self._saved_meal_plan_repository.get_by_user_snapshot(
            user_id=user_id,
            source_snapshot_id=snapshot_id,
        )
        requested_status = str(plan_status or "saved").lower()
        if requested_status not in {"saved", "draft", "missing_groceries"}:
            requested_status = "draft"
        normalized_status = requested_status
        if existing_saved_plan is not None and existing_saved_plan.status == "saved":
            payload_data["state"] = "saved"
            payload_data["primary_action"] = None
            payload_data["saved_plan_id"] = existing_saved_plan.id
            payload_data["saved_at"] = existing_saved_plan.updated_at.isoformat()
            if existing_saved_plan.linked_day_plan_ids:
                payload_data["linked_day_plan_ids"] = list(existing_saved_plan.linked_day_plan_ids)
            return existing_saved_plan, payload_data, True

        already_saved = False
        payload_data["state"] = normalized_status
        effective_date = self._parse_effective_date(payload_data.get("effective_date"))
        view_mode = str(payload_data.get("view_mode") or "day")
        if normalized_status != "draft":
            payload_data["primary_action"] = None
        else:
            payload_data["primary_action"] = self._start_plan_action(
                snapshot_id=snapshot_id,
            )
        saved_plan = self._saved_meal_plan_repository.upsert_saved_plan(
            user_id=user_id,
            title=str(payload_data.get("title") or block.get("title") or "Meal Plan"),
            view_mode=view_mode,
            effective_date=effective_date,
            meal_type=meal_type,
            country_code=country_code,
            planned_meals=normalized_planned_meals,
            plan_payload=payload_data,
            requested_culture=requested_culture,
            user_goal=user_goal,
            source_snapshot_id=snapshot_id,
            source_conversation_id=source_conversation_id,
            agent_type=agent_type,
            status=normalized_status,
            plan_scope="weekly_parent" if view_mode == "week" else "standalone_day",
            week_start=self._parse_effective_date(payload_data.get("week_start")),
            week_end=self._parse_effective_date(payload_data.get("week_end")),
        )
        payload_data["saved_plan_id"] = saved_plan.id
        if normalized_status == "saved":
            payload_data["saved_at"] = saved_plan.updated_at.isoformat()
        if view_mode == "week" and normalized_status == "saved":
            linked_day_plans = self._upsert_weekly_child_day_plans_for_saved_plan(
                user_id=user_id,
                meal_type=meal_type,
                country_code=country_code,
                requested_culture=requested_culture,
                user_goal=user_goal,
                source_conversation_id=source_conversation_id,
                agent_type=agent_type,
                parent_saved_plan=saved_plan,
                parent_payload=payload_data,
            )
            linked_day_plan_ids = [plan.id for plan in linked_day_plans]
            payload_data["linked_day_plan_ids"] = linked_day_plan_ids
            saved_plan = self._saved_meal_plan_repository.upsert_saved_plan(
                user_id=user_id,
                title=str(payload_data.get("title") or block.get("title") or "Meal Plan"),
                view_mode="week",
                effective_date=effective_date,
                meal_type=meal_type,
                country_code=country_code,
                planned_meals=normalized_planned_meals,
                plan_payload=payload_data,
                requested_culture=requested_culture,
                user_goal=user_goal,
                source_snapshot_id=snapshot_id,
                source_conversation_id=source_conversation_id,
                agent_type=agent_type,
                plan_scope="weekly_parent",
                week_start=self._parse_effective_date(payload_data.get("week_start")),
                week_end=self._parse_effective_date(payload_data.get("week_end")),
                linked_day_plan_ids=linked_day_plan_ids,
                status="saved",
            )
            payload_data["saved_plan_id"] = saved_plan.id
            payload_data["saved_at"] = saved_plan.updated_at.isoformat()
        elif normalized_status == "saved":
            self._user_meal_usage_service.sync_saved_day_plan(saved_plan=saved_plan)
        if normalized_status == "saved":
            self._sync_kitchen_allocations_for_saved_plan(saved_plan=saved_plan)
        return saved_plan, payload_data, already_saved

    def _refresh_plan_grocery_summaries(
        self,
        *,
        user_id: str,
        payload_data: dict[str, Any],
        country_code: str | None,
    ) -> tuple[dict[str, Any], bool]:
        meals_by_key = self._presentation_meals_by_key_from_payload(payload_data)
        if not meals_by_key:
            return payload_data, False

        household_size = max(int((payload_data.get("bundle_summary") or {}).get("household_size") or 1), 1)
        costing_service = MealPlanCostingService(self._grocery_repository)
        inventory_service = MealInventoryReconciliationService()
        demand_summary = costing_service.build_product_demands(
            meals_by_slot=meals_by_key,
            household_size=household_size,
        )
        pantry_items = self._kitchen_service.list_planning_items(user_id=user_id)
        inventory_summary = inventory_service.reconcile(
            product_demands=list(demand_summary.get("product_demands") or []),
            pantry_items=pantry_items,
        )
        cart_summary = costing_service.summarize_cart(
            shortages=list(inventory_summary.get("shortages") or []),
            products_by_id=dict(demand_summary.get("products_by_id") or {}),
            country_code=country_code,
        )

        updated_payload = dict(payload_data)
        updated_payload["inventory_summary"] = inventory_summary
        updated_payload["cart_summary"] = cart_summary
        if str(updated_payload.get("view_mode") or "").lower() == "week":
            updated_payload["week_summary"] = self._build_week_summary_payload(
                payload=updated_payload,
                bundle_summary=dict(updated_payload.get("bundle_summary") or {}),
                inventory_summary=inventory_summary,
                cart_summary=cart_summary,
            )
            updated_payload["day_briefs"] = self._build_day_briefs_payload(
                payload=updated_payload,
            )
        return updated_payload, bool(list(inventory_summary.get("shortages") or []))

    def _sync_kitchen_allocations_for_saved_plan(self, *, saved_plan: SavedMealPlan) -> None:
        if str(saved_plan.plan_scope or "") not in {"standalone_day", "weekly_parent"}:
            return
        payload_data = dict(saved_plan.plan_payload or {})
        meals_by_key = self._presentation_meals_by_key_from_payload(payload_data)
        if not meals_by_key:
            self._kitchen_service.release_saved_plan_allocations(
                user_id=saved_plan.user_id,
                saved_plan_id=saved_plan.id,
            )
            return
        household_size = max(int((payload_data.get("bundle_summary") or {}).get("household_size") or 1), 1)
        demand_summary = MealPlanCostingService(self._grocery_repository).build_product_demands(
            meals_by_slot=meals_by_key,
            household_size=household_size,
        )
        self._kitchen_service.sync_saved_plan_allocations(
            user_id=saved_plan.user_id,
            saved_plan_id=saved_plan.id,
            product_demands=list(demand_summary.get("product_demands") or []),
            effective_date=saved_plan.effective_date if saved_plan.view_mode == "day" else None,
            replace_existing=True,
        )

    def _persist_generated_meal_plan_draft(
        self,
        *,
        current_user: User,
        turn_result: MealConversationTurnResult,
        source_conversation_id: str | None,
    ) -> SavedMealPlan | None:
        if not turn_result.ui_blocks:
            return None

        block = dict(turn_result.ui_blocks[0] or {})
        if str(block.get("block_type") or "") not in {"meal_plan_draft", "meal_plan_week"}:
            return None

        payload_data = dict(block.get("payload") or {})
        snapshot_id = str(payload_data.get("snapshot_id") or block.get("id") or "").strip()
        if not snapshot_id:
            return None

        saved_plan, _, _ = self._persist_saved_plan_from_block(
            user_id=current_user.id,
            block=block,
            planned_meals=list(turn_result.planned_meals),
            meal_type=turn_result.meal_type.value if turn_result.meal_type is not None else None,
            country_code=turn_result.country_code.value if turn_result.country_code is not None else None,
            requested_culture=turn_result.requested_culture,
            user_goal=str((current_user.user_configuration or {}).get("goal") or "").strip() or None,
            source_conversation_id=str(source_conversation_id or "direct-planner").strip() or "direct-planner",
            agent_type=turn_result.agent_type,
            plan_status="draft",
        )
        return saved_plan

    @staticmethod
    def _parse_effective_date(raw_value: Any) -> date | None:
        if raw_value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(raw_value))
        except ValueError:
            return None

    def _upsert_weekly_child_day_plans(
        self,
        *,
        conversation: dict[str, Any],
        summary: dict[str, Any],
        parent_saved_plan: Any,
        parent_payload: dict[str, Any],
    ) -> list[Any]:
        return self._upsert_weekly_child_day_plans_for_saved_plan(
            user_id=str(conversation["user_id"]),
            meal_type=summary.get("meal_type"),
            country_code=summary.get("country_code"),
            requested_culture=summary.get("requested_culture"),
            user_goal=str(conversation.get("user_goal") or "") or None,
            source_conversation_id=str(conversation["_id"]),
            agent_type=str(conversation.get("agent_type") or MEAL_COORDINATOR_AGENT_TYPE),
            parent_saved_plan=parent_saved_plan,
            parent_payload=parent_payload,
        )

    def _upsert_weekly_child_day_plans_for_saved_plan(
        self,
        *,
        user_id: str,
        meal_type: str | None,
        country_code: str | None,
        requested_culture: str | None,
        user_goal: str | None,
        source_conversation_id: str,
        agent_type: str,
        parent_saved_plan: Any,
        parent_payload: dict[str, Any],
    ) -> list[Any]:
        child_saved_plans: list[Any] = []
        daily_snapshots = list(parent_payload.get("daily_snapshots") or [])
        for index, snapshot in enumerate(daily_snapshots):
            day_payload = self._build_child_day_payload_from_weekly_snapshot(
                parent_payload=parent_payload,
                day_snapshot=dict(snapshot),
                parent_saved_plan_id=parent_saved_plan.id,
                parent_snapshot_id=parent_saved_plan.source_snapshot_id,
                day_index=index,
            )
            effective_date = self._parse_effective_date(day_payload.get("effective_date"))
            if effective_date is None:
                continue
            child_snapshot_id = f"{parent_saved_plan.source_snapshot_id}:day:{index}:{effective_date.isoformat()}"
            day_payload["snapshot_id"] = child_snapshot_id
            child_saved_plan = self._saved_meal_plan_repository.upsert_saved_plan(
                user_id=user_id,
                title=str(day_payload.get("title") or "Meal Plan"),
                view_mode="day",
                effective_date=effective_date,
                meal_type=meal_type,
                country_code=country_code,
                planned_meals=list(day_payload.get("planned_meals") or self._build_planned_meals_from_sections(day_payload.get("sections") or [])),
                plan_payload=day_payload,
                requested_culture=requested_culture,
                user_goal=user_goal,
                source_snapshot_id=child_snapshot_id,
                source_conversation_id=source_conversation_id,
                agent_type=agent_type,
                plan_scope="weekly_child",
                week_start=self._parse_effective_date(parent_payload.get("week_start")),
                week_end=self._parse_effective_date(parent_payload.get("week_end")),
                day_index=index,
                parent_saved_plan_id=parent_saved_plan.id,
                status="saved",
            )
            self._user_meal_usage_service.sync_saved_day_plan(saved_plan=child_saved_plan)
            child_saved_plans.append(child_saved_plan)
        return child_saved_plans

    def _build_child_day_payload_from_weekly_snapshot(
        self,
        *,
        parent_payload: dict[str, Any],
        day_snapshot: dict[str, Any],
        parent_saved_plan_id: str,
        parent_snapshot_id: str,
        day_index: int,
    ) -> dict[str, Any]:
        sections = list(day_snapshot.get("sections") or [])
        effective_date = day_snapshot.get("effective_date") or day_snapshot.get("date")
        return {
            "snapshot_id": f"{parent_snapshot_id}:day:{day_index}:{effective_date}",
            "title": str(day_snapshot.get("title") or parent_payload.get("title") or "Meal Plan"),
            "view_mode": "day",
            "state": "saved",
            "effective_date": effective_date,
            "tracked_text": str(day_snapshot.get("tracked_text") or f"Tracked 0/{len(sections)} meals"),
            "totals": dict(day_snapshot.get("totals") or {}),
            "sections": sections,
            "days": [],
            "primary_action": None,
            "overflow_actions": [],
            "planned_meals": list(day_snapshot.get("planned_meals") or self._build_planned_meals_from_sections(sections)),
            "parent_weekly_plan_id": parent_saved_plan_id,
            "parent_weekly_snapshot_id": parent_snapshot_id,
            "week_start": parent_payload.get("week_start"),
            "week_end": parent_payload.get("week_end"),
            "day_index": day_index,
            "source": "weekly_plan_child",
        }

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
                        "created_meal_draft": (
                            dict(item.get("meal_detail") or {})
                            if str(item.get("meal_source") or "") == "created"
                            else None
                        ),
                        "source_type": item.get("source_type"),
                        "batch_id": item.get("batch_id"),
                        "origin_batch_id": item.get("origin_batch_id"),
                    }
                )
        return planned_meals

    def _presentation_meals_by_key_from_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        normalized_view_mode = str(payload.get("view_mode") or "day").strip().lower()
        meals_by_key: dict[str, dict[str, Any]] = {}

        if normalized_view_mode == "week":
            for day_index, day in enumerate(list(payload.get("days") or []), start=1):
                if not isinstance(day, dict):
                    continue
                date_key = str(day.get("date") or payload.get("effective_date") or f"day-{day_index}").strip()
                for section_index, section in enumerate(list(day.get("sections") or []), start=1):
                    if not isinstance(section, dict):
                        continue
                    slot = str(section.get("slot") or "").strip().lower()
                    if not slot:
                        continue
                    for item_index, item in enumerate(list(section.get("items") or []), start=1):
                        if not isinstance(item, dict):
                            continue
                        synthetic_meal = self._presentation_meal_payload_from_item(
                            slot=slot,
                            item=item,
                            key_prefix=f"{date_key}:{section_index}:{item_index}",
                        )
                        if synthetic_meal is None:
                            continue
                        meals_by_key[f"{date_key}:{slot}:{section_index}:{item_index}"] = synthetic_meal
            return meals_by_key

        for section_index, section in enumerate(list(payload.get("sections") or []), start=1):
            if not isinstance(section, dict):
                continue
            slot = str(section.get("slot") or "").strip().lower()
            if not slot:
                continue
            for item_index, item in enumerate(list(section.get("items") or []), start=1):
                if not isinstance(item, dict):
                    continue
                synthetic_meal = self._presentation_meal_payload_from_item(
                    slot=slot,
                    item=item,
                    key_prefix=f"{slot}:{section_index}:{item_index}",
                )
                if synthetic_meal is None:
                    continue
                meals_by_key[f"{slot}:{section_index}:{item_index}"] = synthetic_meal
        return meals_by_key

    def _presentation_meal_payload_from_item(
        self,
        *,
        slot: str,
        item: dict[str, Any],
        key_prefix: str,
    ) -> dict[str, Any] | None:
        meal_detail = dict(item.get("meal_detail") or {})
        raw_ingredients = list(meal_detail.get("ingredients") or [])
        ingredient_items: list[dict[str, Any]] = []
        for ingredient_index, ingredient in enumerate(raw_ingredients, start=1):
            if not isinstance(ingredient, dict):
                continue
            ingredient_items.append(
                {
                    "id": ingredient.get("id") or f"{key_prefix}:ingredient:{ingredient_index}",
                    "name": str(ingredient.get("name") or "").strip(),
                    "quantity": ingredient.get("quantity"),
                    "unit": str(ingredient.get("unit") or "").strip(),
                    "optional": bool(ingredient.get("optional", False)),
                    "linked_product_ids": list(ingredient.get("linked_product_ids") or []),
                }
            )
        if not ingredient_items:
            return None

        planned_servings = self._normalized_float(
            item.get("yield_servings")
            or meal_detail.get("yield_servings")
            or item.get("planned_servings")
            or meal_detail.get("planned_servings")
        )
        servings = self._normalized_float(meal_detail.get("servings") or item.get("servings")) or 1.0
        return {
            "id": item.get("meal_id") or f"{key_prefix}:{slot}",
            "name": str(item.get("name") or meal_detail.get("name") or "Planned meal").strip(),
            "servings": servings,
            "planned_servings": planned_servings,
            "ingredient_items": ingredient_items,
        }

    @staticmethod
    def _start_plan_action(*, snapshot_id: str) -> dict[str, Any]:
        return {
            "id": f"save-{snapshot_id}",
            "label": "Start Plan",
            "action_type": "save_meal_plan",
            "message": "Start Plan",
            "payload": {
                "snapshot_id": snapshot_id,
            },
        }
