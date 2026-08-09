from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.admin_promotion import PromotionContentPayload


@dataclass(frozen=True, slots=True)
class PromotionSubagentEnrichment:
    domain: str
    agent_type: str
    highlights: list[str] = field(default_factory=list)
    specs: list[dict[str, str]] = field(default_factory=list)
    message_guidance: list[str] = field(default_factory=list)
    meal_data: dict[str, Any] = field(default_factory=dict)
    grocery_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PromotionAgentGenerationResult:
    payload: PromotionContentPayload
    agent_type: str
    selected_domains: list[str] = field(default_factory=list)
    selected_subagents: list[str] = field(default_factory=list)
    subagent_enrichments: list[PromotionSubagentEnrichment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
