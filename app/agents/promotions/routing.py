from __future__ import annotations

from typing import Any

PROMOTION_AGENT_TYPE = "promotion_agent"
PROMOTION_DOMAIN = "promotion"
MEAL_PLANNER_DOMAIN = "meal_planner"
CHEF_DOMAIN = "chef"
ORDER_DOMAIN = "order"


def infer_supporting_domains(
    *,
    campaign: dict[str, Any],
    user_context: dict[str, Any],
) -> list[str]:
    promotion_type = str(campaign.get("promotion_type") or "").strip().lower()
    delivery_type = str(campaign.get("delivery_type") or "").strip().lower()
    target_location = str(campaign.get("target_location") or "").strip().lower()
    admin_instruction = str(campaign.get("admin_instruction") or "").strip().lower()
    conversation_summary = str(user_context.get("conversation_summary") or "").strip().lower()
    latest_plan_summary = str(user_context.get("latest_plan_summary") or "").strip().lower()
    recent_messages = " ".join(
        str(message.get("text") or "").strip().lower()
        for message in list(user_context.get("recent_messages_summary") or [])
    )
    combined_text = " ".join(
        part for part in [
            promotion_type,
            delivery_type,
            target_location,
            admin_instruction,
            conversation_summary,
            latest_plan_summary,
            recent_messages,
        ]
        if part
    )
    constraints = dict(campaign.get("constraints") or {})

    domains: list[str] = []

    meal_signals = {
        "meal",
        "breakfast",
        "lunch",
        "dinner",
        "snack",
        "day plan",
        "weekly plan",
        "plan",
    }
    if latest_plan_summary or any(signal in combined_text for signal in meal_signals):
        domains.append(MEAL_PLANNER_DOMAIN)

    chef_signals = {
        "recipe",
        "cook",
        "cooking",
        "ingredients",
        "chef",
        "prep",
        "preparation",
        "substitute",
        "swap",
    }
    if any(signal in combined_text for signal in chef_signals):
        domains.append(CHEF_DOMAIN)

    order_signals = {
        "grocery",
        "shop",
        "basket",
        "cart",
        "order",
        "delivery",
        "shipping",
        "reorder",
    }
    if (
        any(signal in combined_text for signal in order_signals)
        or any(key in constraints for key in {"budget", "country_code", "grocery_focus", "delivery_window"})
    ):
        domains.append(ORDER_DOMAIN)

    normalized: list[str] = []
    for domain in domains:
        if domain not in normalized:
            normalized.append(domain)
    return normalized
