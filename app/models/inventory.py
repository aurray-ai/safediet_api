from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class InventoryAdjustmentType(StrEnum):
    MANUAL_SET = "manual_set"
    MANUAL_INCREMENT = "manual_increment"
    MANUAL_DECREMENT = "manual_decrement"
    ORDER_CAPTURE = "order_capture"
    ORDER_RESTOCK = "order_restock"


@dataclass(frozen=True, slots=True)
class InventoryItem:
    id: str
    store_id: str
    product_id: str
    sku: str
    is_active: bool
    available_quantity: int
    reserved_quantity: int
    unit_label: str
    unit_weight_grams: int
    max_per_order: int
    allow_substitutions: bool
    substitution_group: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryAdjustment:
    id: str
    inventory_item_id: str
    product_id: str
    store_id: str
    adjustment_type: InventoryAdjustmentType
    delta_quantity: int
    reason: str
    actor_user_id: str | None
    reference_type: str | None
    reference_id: str | None
    metadata: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryFeeRule:
    id: str
    store_id: str
    currency: str
    min_weight_grams: int
    max_weight_grams: int
    fee_minor: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
