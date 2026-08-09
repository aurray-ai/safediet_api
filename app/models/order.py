from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.models.fulfillment import AssignmentHistoryEntry, ShopperFulfillmentStatus


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAYMENT_PROCESSING = "payment_processing"
    CONFIRMED = "confirmed"
    PICKING = "picking"
    PACKED = "packed"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    CANCELED = "canceled"
    PAYMENT_FAILED = "payment_failed"


class PaymentAttemptStatus(StrEnum):
    PENDING = "pending"
    REQUIRES_ACTION = "requires_action"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RefundStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SubstitutionResolution(StrEnum):
    NONE = "none"
    USER_APPROVED = "user_approved"
    ADMIN_REPLACED = "admin_replaced"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class OrderItemSnapshot:
    id: str
    product_id: str
    category_id: str
    product_name: str
    img_url: str
    quantity: int
    unit_label: str
    unit_weight_grams: int
    unit_price_minor: int
    line_total_minor: int
    currency: str
    allow_substitutions: bool
    substitution_resolution: SubstitutionResolution
    substituted_product_id: str | None
    source_meal_id: str | None = None
    base_price_minor: int = 0
    discount_percent_applied: float = 0.0


@dataclass(frozen=True, slots=True)
class OrderPricingSummary:
    currency: str
    subtotal_minor: int
    delivery_fee_minor: int
    service_fee_minor: int
    total_minor: int
    total_weight_grams: int


@dataclass(frozen=True, slots=True)
class OrderPaymentSummary:
    currency: str
    wallet_amount_minor: int
    card_amount_minor: int
    total_paid_minor: int
    provider: str | None
    provider_payment_intent_id: str | None


@dataclass(frozen=True, slots=True)
class OrderStatusHistoryEntry:
    status: OrderStatus
    note: str
    actor_user_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    order_number: str
    user_id: str
    store_id: str
    status: OrderStatus
    currency: str
    items: list[OrderItemSnapshot]
    pricing_summary: OrderPricingSummary
    address_snapshot: dict[str, object]
    substitution_policy: dict[str, object]
    payment_summary: OrderPaymentSummary
    cancellation_window_expires_at: datetime | None
    status_history: list[OrderStatusHistoryEntry]
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
    fulfillment_status: ShopperFulfillmentStatus = ShopperFulfillmentStatus.UNASSIGNED
    assigned_worker_id: str | None = None
    assigned_by: str | None = None
    assigned_at: datetime | None = None
    assignment_history: list[AssignmentHistoryEntry] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PaymentAttempt:
    id: str
    order_id: str
    user_id: str
    quote_id: str
    status: PaymentAttemptStatus
    currency: str
    wallet_hold_amount_minor: int
    wallet_capture_amount_minor: int
    card_amount_minor: int
    provider: str
    provider_payment_intent_id: str | None
    client_secret: str | None
    idempotency_key: str
    provider_payload: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Refund:
    id: str
    order_id: str
    user_id: str
    status: RefundStatus
    currency: str
    refund_type: str
    reason: str
    wallet_refund_minor: int
    card_refund_minor: int
    line_items: list[dict[str, object]]
    provider: str | None
    provider_refund_id: str | None
    idempotency_key: str
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
