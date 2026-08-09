from __future__ import annotations

from datetime import datetime
import random
from dataclasses import dataclass
from enum import StrEnum
from string import Template
from typing import Any, Callable


class NotificationCopyKey(StrEnum):
    UNSAVED_MEAL_PLAN_REMINDER = "unsaved_meal_plan_reminder"
    MEAL_PLAN_APPROVED = "meal_plan_approved"
    MEAL_SLOT_REMINDER = "meal_slot_reminder"
    ORDER_ASSIGNED_TO_WORKER = "order_assigned_to_worker"
    ORDER_DECLINED_BY_WORKER = "order_declined_by_worker"
    SUBSCRIPTION_STARTED = "subscription_started"
    SUBSCRIPTION_CANCELED = "subscription_canceled"


@dataclass(frozen=True, slots=True)
class NotificationCopy:
    title: str
    message: str


@dataclass(frozen=True, slots=True)
class NotificationCopyTemplate:
    title: str
    message: str


class NotificationCopyService:
    def __init__(
        self,
        *,
        chooser: Callable[[tuple[NotificationCopyTemplate, ...]], NotificationCopyTemplate] | None = None,
    ) -> None:
        self._chooser = chooser or random.choice

    def for_unsaved_meal_plan_reminder(
        self,
        *,
        period_label: str | None = None,
        view_mode: str | None = None,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.UNSAVED_MEAL_PLAN_REMINDER,
            period_label=period_label,
            view_mode=view_mode,
        )

    def for_meal_plan_approved(
        self,
        *,
        period_label: str | None = None,
        view_mode: str | None = None,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.MEAL_PLAN_APPROVED,
            period_label=period_label,
            view_mode=view_mode,
        )

    def for_meal_slot_reminder(
        self,
        *,
        meal_name: str,
        meal_slot: str,
        time_label: str,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.MEAL_SLOT_REMINDER,
            meal_name=meal_name,
            meal_slot=meal_slot,
            time_label=time_label,
        )

    def for_order_assigned_to_worker(
        self,
        *,
        order_number: str,
        track_label: str,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.ORDER_ASSIGNED_TO_WORKER,
            order_number=order_number,
            track_label=track_label,
        )

    def for_subscription_started(
        self,
        *,
        plan_name: str,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.SUBSCRIPTION_STARTED,
            plan_name=plan_name,
        )

    def for_subscription_canceled(
        self,
        *,
        plan_name: str,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.SUBSCRIPTION_CANCELED,
            plan_name=plan_name,
        )

    def for_order_declined_by_worker(
        self,
        *,
        order_number: str,
        track_label: str,
    ) -> NotificationCopy:
        return self.render(
            NotificationCopyKey.ORDER_DECLINED_BY_WORKER,
            order_number=order_number,
            track_label=track_label,
        )

    def render(self, key: NotificationCopyKey, **context: Any) -> NotificationCopy:
        templates = _COPY_REGISTRY[key]
        selected = self._chooser(templates)
        normalized = _notification_context(**context)
        return NotificationCopy(
            title=Template(selected.title).safe_substitute(normalized),
            message=Template(selected.message).safe_substitute(normalized),
        )


def _notification_context(
    *,
    period_label: str | None = None,
    view_mode: str | None = None,
    meal_name: str | None = None,
    meal_slot: str | None = None,
    time_label: str | None = None,
    order_number: str | None = None,
    track_label: str | None = None,
    plan_name: str | None = None,
) -> dict[str, str]:
    cleaned_period_label = (period_label or "").strip()
    plan_kind = "weekly plan" if str(view_mode or "").lower() == "week" else "meal plan"
    formatted_period_label = _format_period_label(cleaned_period_label)
    if formatted_period_label:
        plan_reference = f"your {formatted_period_label} {plan_kind}"
    else:
        plan_reference = f"your {plan_kind}"
    accepted_plan_reference = (
        f"your meal slot for {formatted_period_label} meal plan"
        if formatted_period_label and plan_kind == "meal plan"
        else plan_reference
    )
    reminder_plan_reference = (
        f"your meal slot for {formatted_period_label} meal plan"
        if formatted_period_label and plan_kind == "meal plan"
        else plan_reference
    )
    return {
        "period_label": cleaned_period_label,
        "formatted_period_label": formatted_period_label,
        "plan_kind": plan_kind,
        "plan_reference": plan_reference,
        "plan_reference_capitalized": plan_reference[:1].upper() + plan_reference[1:],
        "accepted_plan_reference": accepted_plan_reference,
        "accepted_plan_reference_capitalized": accepted_plan_reference[:1].upper() + accepted_plan_reference[1:],
        "reminder_plan_reference": reminder_plan_reference,
        "reminder_plan_reference_capitalized": reminder_plan_reference[:1].upper() + reminder_plan_reference[1:],
        "meal_name": (meal_name or "").strip() or "Your meal",
        "meal_slot": (meal_slot or "").strip().lower() or "meal",
        "meal_slot_title": ((meal_slot or "").strip().lower() or "meal").capitalize(),
        "time_label": (time_label or "").strip() or "today",
        "order_number": (order_number or "").strip() or "your order",
        "track_label": (track_label or "").strip() or "order",
        "plan_name": (plan_name or "").strip() or "Premium",
    }


def _format_period_label(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError:
        return normalized
    day = parsed.day
    return f"{parsed.strftime('%A')} {day}{_ordinal_suffix(day)} of {parsed.strftime('%B')}"


def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


_COPY_REGISTRY: dict[NotificationCopyKey, tuple[NotificationCopyTemplate, ...]] = {
    NotificationCopyKey.UNSAVED_MEAL_PLAN_REMINDER: (
        NotificationCopyTemplate(
            title="Your draft ${plan_kind} is waiting",
            message="Just a gentle reminder to review and save ${reminder_plan_reference} when you have a moment.",
        ),
    ),
    NotificationCopyKey.MEAL_PLAN_APPROVED: (
        NotificationCopyTemplate(
            title="Your ${plan_kind} has been accepted",
            message="${accepted_plan_reference_capitalized} is now accepted and ready to start.",
        ),
    ),
    NotificationCopyKey.MEAL_SLOT_REMINDER: (
        NotificationCopyTemplate(
            title="${meal_name}",
            message="Your ${meal_name} is what you have planned for ${time_label} ${meal_slot}.",
        ),
        NotificationCopyTemplate(
            title="Time for ${meal_slot}",
            message="${meal_name} is on your plan for ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="A quick meal reminder",
            message="${meal_name} is your planned ${meal_slot} for ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="${meal_slot_title} is already sorted",
            message="${meal_name} is lined up for ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="Don’t miss your planned ${meal_slot}",
            message="${meal_name} is what you’re having for ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="${meal_name} is coming up",
            message="Just a heads-up, ${meal_name} is your ${meal_slot} for ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="Your ${meal_slot} plan is ready",
            message="${meal_name} is waiting for you ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="Meal check-in",
            message="You planned ${meal_name} for ${time_label} ${meal_slot}.",
        ),
        NotificationCopyTemplate(
            title="${meal_name} is on today’s plan",
            message="That’s your scheduled ${meal_slot} for ${time_label}.",
        ),
        NotificationCopyTemplate(
            title="Stay on track with ${meal_name}",
            message="You’ve got ${meal_name} planned for ${time_label}.",
        ),
    ),
    NotificationCopyKey.ORDER_ASSIGNED_TO_WORKER: (
        NotificationCopyTemplate(
            title="New ${track_label} assigned",
            message="${order_number} has been assigned to you. Open it to see the full details.",
        ),
    ),
    NotificationCopyKey.ORDER_DECLINED_BY_WORKER: (
        NotificationCopyTemplate(
            title="${track_label} needs reassignment",
            message="${order_number} was declined and is back in the queue awaiting a new assignment.",
        ),
    ),
    NotificationCopyKey.SUBSCRIPTION_STARTED: (
        NotificationCopyTemplate(
            title="Welcome to ${plan_name}",
            message="Your ${plan_name} subscription is active. Enjoy member pricing and full access.",
        ),
    ),
    NotificationCopyKey.SUBSCRIPTION_CANCELED: (
        NotificationCopyTemplate(
            title="Your subscription has ended",
            message="Your ${plan_name} subscription is no longer active. You can resubscribe anytime.",
        ),
    ),
}
