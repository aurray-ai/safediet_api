from __future__ import annotations

MEAL_COORDINATOR_AGENT_TYPE = "meal_coordinator"
MEAL_PLANNING_DOMAIN = "meal_planning"
ORDER_DOMAIN = "order"
CHEF_DOMAIN = "chef"


def infer_target_domain(
    *,
    user_message: str | None,
    quick_action_type: str | None,
    action_payload: dict[str, object] | None,
) -> str:
    payload = dict(action_payload or {})
    normalized_action = str(quick_action_type or "").strip().lower()
    normalized_message = str(user_message or "").strip().lower()

    order_actions = {
        "shipping_help",
        "track_order",
        "track_delivery",
        "delivery_status",
        "order_help",
        "order_status",
    }
    if normalized_action in order_actions:
        return ORDER_DOMAIN

    if payload.get("order_id") or payload.get("tracking_id") or payload.get("delivery_id"):
        return ORDER_DOMAIN

    order_signals = {
        "shipping",
        "delivery",
        "track order",
        "tracking",
        "courier",
        "where is my order",
        "where is my delivery",
        "package",
        "dispatch",
    }
    if any(signal in normalized_message for signal in order_signals):
        return ORDER_DOMAIN

    if "order" in normalized_message and any(
        token in normalized_message for token in {"track", "tracking", "delivery", "shipping", "dispatch"}
    ):
        return ORDER_DOMAIN

    chef_actions = {
        "chef_help",
        "recipe_help",
        "cooking_help",
        "ingredient_substitution",
    }
    if normalized_action in chef_actions:
        return CHEF_DOMAIN

    chef_signals = {
        "how do i cook",
        "cooking steps",
        "recipe steps",
        "substitute",
        "ingredient swap",
        "what can i use instead",
        "chef",
    }
    if any(signal in normalized_message for signal in chef_signals):
        return CHEF_DOMAIN

    return MEAL_PLANNING_DOMAIN
