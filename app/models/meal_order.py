from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from app.models.fulfillment import AssignmentHistoryEntry, ChefFulfillmentStatus
from app.models.order import OrderStatus


class MealDeliveryType(StrEnum):
    STANDARD = "standard"
    EXPRESS = "express"


@dataclass(frozen=True, slots=True)
class MealOrderItemSnapshot:
    id: str
    meal_id: str
    meal_name: str
    img_url: str
    servings: int
    unit_price_minor: int
    line_total_minor: int
    currency: str
    delivery_date: date | None = None
    slot: str = ""


@dataclass(frozen=True, slots=True)
class MealOrderPricingSummary:
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int


@dataclass(frozen=True, slots=True)
class MealOrderPaymentSummary:
    currency: str
    wallet_amount_minor: int
    card_amount_minor: int
    total_paid_minor: int
    provider: str | None
    provider_payment_intent_id: str | None


@dataclass(frozen=True, slots=True)
class MealOrderStatusHistoryEntry:
    status: OrderStatus
    note: str
    actor_user_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MealOrder:
    id: str
    order_number: str
    user_id: str
    status: OrderStatus
    currency: str
    delivery_type: MealDeliveryType
    items: list[MealOrderItemSnapshot]
    pricing_summary: MealOrderPricingSummary
    address_snapshot: dict[str, object]
    payment_summary: MealOrderPaymentSummary
    cancellation_window_expires_at: datetime | None
    status_history: list[MealOrderStatusHistoryEntry]
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    fulfillment_status: ChefFulfillmentStatus = ChefFulfillmentStatus.UNASSIGNED
    assigned_worker_id: str | None = None
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    assignment_history: list[AssignmentHistoryEntry] = field(default_factory=list)
