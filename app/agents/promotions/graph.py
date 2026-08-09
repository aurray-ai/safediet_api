from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any, Protocol, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional runtime dependency
    END = None
    StateGraph = None

from app.agents.promotions.routing import (
    CHEF_DOMAIN,
    MEAL_PLANNER_DOMAIN,
    ORDER_DOMAIN,
    PROMOTION_AGENT_TYPE,
    infer_supporting_domains,
)
from app.agents.promotions.runtime import PromotionGenerationRuntime
from app.agents.promotions.subagents import (
    ChefPromotionSubagentGraph,
    MealPlannerPromotionSubagentGraph,
    OrderPromotionSubagentGraph,
)
from app.agents.promotions.types import (
    PromotionAgentGenerationResult,
    PromotionSubagentEnrichment,
)
from app.models.user import User
from app.schemas.admin_promotion import PromotionContentPayload

logger = logging.getLogger(__name__)


class PromotionGraphState(TypedDict, total=False):
    campaign: dict[str, Any]
    current_user: User
    user_context: dict[str, Any]
    selected_domains: list[str]
    selected_subagents: list[str]
    subagent_enrichments: list[PromotionSubagentEnrichment]
    final_result: PromotionAgentGenerationResult


class PromotionSubagent(Protocol):
    def run_enrichment(
        self,
        *,
        campaign: dict[str, Any],
        current_user: User,
        user_context: dict[str, Any],
    ) -> PromotionSubagentEnrichment: ...


class PromotionAgentGraph:
    def __init__(self, runtime: PromotionGenerationRuntime) -> None:
        self.runtime = runtime
        self._subagents: dict[str, PromotionSubagent] = {
            MEAL_PLANNER_DOMAIN: MealPlannerPromotionSubagentGraph(),
            CHEF_DOMAIN: ChefPromotionSubagentGraph(),
            ORDER_DOMAIN: OrderPromotionSubagentGraph(),
        }
        self._compiled_graph = self._compile_graph()

    def run_generation(
        self,
        *,
        campaign: dict[str, Any],
        current_user: User,
        user_context: dict[str, Any],
    ) -> PromotionAgentGenerationResult:
        initial_state: PromotionGraphState = {
            "campaign": dict(campaign or {}),
            "current_user": current_user,
            "user_context": dict(user_context or {}),
        }
        if self._compiled_graph is None:
            state = dict(initial_state)
            state.update(self._route_request(state))
            state.update(self._invoke_subagents(state))
            state.update(self._generate_payload(state))
        else:
            state = self._compiled_graph.invoke(initial_state)
        return state["final_result"]

    def _compile_graph(self):
        if StateGraph is None or END is None:
            return None
        workflow = StateGraph(PromotionGraphState)
        workflow.add_node("route_request", self._route_request)
        workflow.add_node("invoke_subagents", self._invoke_subagents)
        workflow.add_node("generate_payload", self._generate_payload)
        workflow.set_entry_point("route_request")
        workflow.add_edge("route_request", "invoke_subagents")
        workflow.add_edge("invoke_subagents", "generate_payload")
        workflow.add_edge("generate_payload", END)
        return workflow.compile()

    def _route_request(self, state: PromotionGraphState) -> dict[str, Any]:
        selected_domains = infer_supporting_domains(
            campaign=dict(state.get("campaign") or {}),
            user_context=dict(state.get("user_context") or {}),
        )
        return {
            "selected_domains": selected_domains,
            "selected_subagents": [self._selected_subagent_name(domain) for domain in selected_domains],
        }

    def _invoke_subagents(self, state: PromotionGraphState) -> dict[str, Any]:
        campaign = dict(state.get("campaign") or {})
        current_user = state["current_user"]
        user_context = dict(state.get("user_context") or {})
        enrichments: list[PromotionSubagentEnrichment] = []

        for domain in list(state.get("selected_domains") or []):
            subagent = self._subagents.get(domain)
            if subagent is None:
                continue
            enrichments.append(
                subagent.run_enrichment(
                    campaign=campaign,
                    current_user=current_user,
                    user_context=user_context,
                )
            )
        return {"subagent_enrichments": enrichments}

    def _generate_payload(self, state: PromotionGraphState) -> dict[str, Any]:
        campaign = dict(state.get("campaign") or {})
        current_user = state["current_user"]
        user_context = dict(state.get("user_context") or {})
        enrichments = list(state.get("subagent_enrichments") or [])
        serialized_enrichments = [self._serialize_enrichment(item) for item in enrichments]
        selected_domains = list(state.get("selected_domains") or [])
        selected_subagents = list(state.get("selected_subagents") or [])

        enriched_context = {
            **user_context,
            "agent_enrichments": serialized_enrichments,
        }

        payload: PromotionContentPayload | None = None
        generation_source = "fallback"
        generation_model = self.runtime.model_name
        llm_metadata: dict[str, Any] = {}

        if self.runtime.supports_llm():
            try:
                payload, llm_metadata = self.runtime.generate_payload(
                    campaign=campaign,
                    user_context=enriched_context,
                )
                generation_source = "llm"
                generation_model = str((llm_metadata.get("llm_metrics") or {}).get("model_name") or self.runtime.model_name)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Promotion agent generation failed campaign_id=%s user_id=%s",
                    str(campaign.get("_id") or ""),
                    current_user.id,
                )

        if payload is None:
            payload = self._build_fallback_payload(
                campaign=campaign,
                current_user=current_user,
                user_context=user_context,
                enrichments=enrichments,
            )

        payload.metadata = {
            **dict(payload.metadata or {}),
            "agent_type": PROMOTION_AGENT_TYPE,
            "generation_source": generation_source,
            "generation_model": generation_model,
            "selected_domains": selected_domains,
            "selected_subagents": selected_subagents,
        }
        result_metadata = {
            "agent_type": PROMOTION_AGENT_TYPE,
            "selected_domains": selected_domains,
            "selected_subagents": selected_subagents,
            "subagent_enrichments": serialized_enrichments,
            **llm_metadata,
        }
        return {
            "final_result": PromotionAgentGenerationResult(
                payload=payload,
                agent_type=PROMOTION_AGENT_TYPE,
                selected_domains=selected_domains,
                selected_subagents=selected_subagents,
                subagent_enrichments=enrichments,
                metadata=result_metadata,
            )
        }

    def _build_fallback_payload(
        self,
        *,
        campaign: dict[str, Any],
        current_user: User,
        user_context: dict[str, Any],
        enrichments: list[PromotionSubagentEnrichment],
    ) -> PromotionContentPayload:
        promotion_type = str(campaign.get("promotion_type") or "promotion")
        delivery_type = str(campaign.get("delivery_type") or "notification")
        location = str(campaign.get("target_location") or "ios.home")
        conversation_summary = str(user_context.get("conversation_summary") or "").strip()
        latest_plan_summary = str(user_context.get("latest_plan_summary") or "").strip()
        preferences = dict(user_context.get("preference_snapshot") or {})
        goal = str(preferences.get("goal") or "").replace("_", " ").strip()
        culture_preferences = [
            str(item).replace("_", " ").title()
            for item in list(preferences.get("culture_preferences") or [])
            if str(item).strip()
        ]
        selected_domains = [item.domain for item in enrichments]

        title = self._build_title(
            promotion_type=promotion_type,
            latest_plan_summary=latest_plan_summary,
            selected_domains=selected_domains,
        )
        short_message = self._build_short_message(
            promotion_type=promotion_type,
            latest_plan_summary=latest_plan_summary,
            conversation_summary=conversation_summary,
            selected_domains=selected_domains,
        )
        full_message = self._build_full_message(
            user_name=current_user.name,
            short_message=short_message,
            goal=goal,
            culture_preferences=culture_preferences,
            enrichments=enrichments,
        )
        highlights = self._dedupe_strings(
            [
                latest_plan_summary,
                *(highlight for enrichment in enrichments for highlight in enrichment.highlights),
                goal and f"Supports your {goal} goal.",
            ]
        )[:3]
        specs = self._merge_specs(
            [{"label": "Delivery", "value": delivery_type}],
            *(enrichment.specs for enrichment in enrichments),
        )[:4]
        meal_data = {
            "goal": goal or None,
            "latest_plan_summary": latest_plan_summary or None,
        }
        grocery_data: dict[str, Any] = {}
        for enrichment in enrichments:
            meal_data.update({key: value for key, value in enrichment.meal_data.items() if value not in (None, "", [], {})})
            grocery_data.update({key: value for key, value in enrichment.grocery_data.items() if value not in (None, "", [], {})})

        return PromotionContentPayload(
            title=title[:160],
            short_message=short_message[:400],
            full_message=full_message[:4000],
            summary=(latest_plan_summary or conversation_summary or short_message)[:600],
            highlights=highlights,
            cta_primary=self._default_cta(location=location),
            cta_secondary="View details",
            delivery_type=delivery_type,
            location=location,
            specs=specs,
            image_urls=[],
            meal_data=meal_data,
            grocery_data=grocery_data,
            metadata={
                "promotion_type": promotion_type,
                "source": "admin_promotions",
                "user_id": current_user.id,
            },
        )

    @staticmethod
    def _build_title(
        *,
        promotion_type: str,
        latest_plan_summary: str,
        selected_domains: list[str],
    ) -> str:
        normalized_type = promotion_type.replace("_", " ").strip().title()
        if MEAL_PLANNER_DOMAIN in selected_domains and latest_plan_summary:
            return "A meal update is ready"
        if ORDER_DOMAIN in selected_domains or "grocery" in promotion_type:
            return "A grocery update is ready"
        if CHEF_DOMAIN in selected_domains:
            return "A recipe-led update is ready"
        return f"{normalized_type or 'Promotion'} ready"

    @staticmethod
    def _build_short_message(
        *,
        promotion_type: str,
        latest_plan_summary: str,
        conversation_summary: str,
        selected_domains: list[str],
    ) -> str:
        if latest_plan_summary:
            return latest_plan_summary
        if conversation_summary:
            return conversation_summary
        if ORDER_DOMAIN in selected_domains or "grocery" in promotion_type:
            return "A grocery-friendly update is ready for you."
        if CHEF_DOMAIN in selected_domains:
            return "A recipe-led idea is ready for you."
        if MEAL_PLANNER_DOMAIN in selected_domains or "meal" in promotion_type:
            return "A meal idea that fits your current plan is ready."
        return f"A new {promotion_type.replace('_', ' ')} is ready for you."

    @staticmethod
    def _build_full_message(
        *,
        user_name: str,
        short_message: str,
        goal: str,
        culture_preferences: list[str],
        enrichments: list[PromotionSubagentEnrichment],
    ) -> str:
        parts = [f"{user_name}, {short_message}" if user_name else short_message]
        if goal:
            parts.append(f"It stays aligned with your current goal: {goal}.")
        if culture_preferences:
            parts.append(f"It also respects preferences like {', '.join(culture_preferences[:2])}.")
        guidance = PromotionAgentGraph._dedupe_strings(
            [guidance for enrichment in enrichments for guidance in enrichment.message_guidance]
        )
        if guidance:
            parts.append(guidance[0])
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _default_cta(*, location: str) -> str:
        if location.endswith(".conversations"):
            return "Open chat"
        if location.endswith(".grocery"):
            return "Open grocery"
        return "Open app"

    @staticmethod
    def _dedupe_strings(values: list[Any]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            cleaned = str(value or "").strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def _merge_specs(*spec_groups: list[dict[str, str]]) -> list[dict[str, str]]:
        merged: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for group in spec_groups:
            for spec in group:
                label = str(spec.get("label") or "").strip()
                value = str(spec.get("value") or "").strip()
                if not label or not value:
                    continue
                key = (label.lower(), value.lower())
                if key in seen:
                    continue
                seen.add(key)
                merged.append({"label": label[:40], "value": value[:80]})
        return merged

    @staticmethod
    def _serialize_enrichment(enrichment: PromotionSubagentEnrichment) -> dict[str, Any]:
        return asdict(enrichment)

    @staticmethod
    def _selected_subagent_name(domain: str) -> str:
        if domain == ORDER_DOMAIN:
            return "order_agent"
        if domain == CHEF_DOMAIN:
            return "chef_agent"
        if domain == MEAL_PLANNER_DOMAIN:
            return "meal_planner_agent"
        return PROMOTION_AGENT_TYPE
