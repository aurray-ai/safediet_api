from __future__ import annotations

import hashlib
import json


def planner_conversation(conversation_id: str) -> str:
    return f"planner:conversation:{conversation_id}"


def planner_current_conversation(user_id: str, user_goal: str | None = None) -> str:
    resolved_goal = user_goal or "any-goal"
    return f"planner:user:{user_id}:current:{resolved_goal}"


def planner_recent_messages(conversation_id: str) -> str:
    return f"planner:conversation:{conversation_id}:recent_messages"


def meal(meal_id: str, *, include_inactive: bool) -> str:
    suffix = "all" if include_inactive else "active"
    return f"meal:{meal_id}:{suffix}"


def meal_category(category_id: str) -> str:
    return f"meal:category:{category_id}"


def meal_categories() -> str:
    return "meal:categories"


def meal_query_version() -> str:
    return "meal:query:version"


def meal_list_query(filters: dict[str, object], *, version: int) -> str:
    payload = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"meal:list:{version}:{digest}"


def grocery_query_version() -> str:
    return "grocery:query:version"


def grocery_list_query(filters: dict[str, object], *, version: int) -> str:
    payload = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"grocery:list:{version}:{digest}"


def grocery_product(product_id: str, *, include_inactive: bool) -> str:
    suffix = "all" if include_inactive else "active"
    return f"grocery:product:{product_id}:{suffix}"


def grocery_category(category_id: str) -> str:
    return f"grocery:category:{category_id}"


def grocery_categories(*, include_inactive: bool) -> str:
    suffix = "all" if include_inactive else "active"
    return f"grocery:categories:{suffix}"
