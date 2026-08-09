from __future__ import annotations

import json
import logging
import time
from typing import Any

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional runtime dependency
    HumanMessage = None
    SystemMessage = None
    ChatOpenAI = None

from app.agents.promotions.prompting import (
    build_promotion_system_prompt,
    build_promotion_user_prompt,
)
from app.schemas.admin_promotion import PromotionContentPayload

logger = logging.getLogger(__name__)


class PromotionGenerationRuntime:
    def __init__(
        self,
        *,
        openai_api_key: str | None,
        model_name: str,
        timeout_seconds: float,
    ) -> None:
        self._openai_api_key = openai_api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model_name

    def supports_llm(self) -> bool:
        return bool(
            self._openai_api_key
            and ChatOpenAI is not None
            and HumanMessage is not None
            and SystemMessage is not None
        )

    def generate_payload(
        self,
        *,
        campaign: dict[str, Any],
        user_context: dict[str, Any],
    ) -> tuple[PromotionContentPayload, dict[str, Any]]:
        if not self.supports_llm():
            raise RuntimeError("LLM runtime unavailable.")

        llm = ChatOpenAI(
            model=self._model_name,
            api_key=self._openai_api_key,
            timeout=self._timeout_seconds,
            temperature=0,
        )
        messages = [
            SystemMessage(content=build_promotion_system_prompt()),
            HumanMessage(
                content=build_promotion_user_prompt(
                    campaign=campaign,
                    user_context=user_context,
                )
            ),
        ]
        started_at = time.perf_counter()
        response = llm.invoke(messages)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        raw_text = self._extract_text_content(response)
        parsed = self._parse_json_object(raw_text)
        payload = PromotionContentPayload.model_validate(parsed)
        metrics = {
            "provider": "openai",
            "model_name": self._model_name,
            "duration_ms": duration_ms,
        }
        return payload, {"llm_raw": raw_text, "llm_metrics": metrics}

    @staticmethod
    def _extract_text_content(response: Any) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        chunks.append(str(text))
                else:
                    text = getattr(item, "text", None)
                    if text:
                        chunks.append(str(text))
            return "\n".join(chunks).strip()
        return str(content)

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict[str, Any]:
        candidate = raw_text.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                logger.error("Promotion LLM returned non-JSON output: %s", candidate)
                raise
            return json.loads(candidate[start : end + 1])
