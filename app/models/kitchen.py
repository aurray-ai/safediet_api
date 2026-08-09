from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.models.grocery import CountryCode


class KitchenStockSourceType(StrEnum):
    MANUAL = "manual"
    ORDER = "order"
    ADJUSTMENT = "adjustment"


class KitchenMovementType(StrEnum):
    STOCK_IN = "stock_in"
    MANUAL_ADD = "manual_add"
    MANUAL_SUBTRACT = "manual_subtract"
    RESERVE_FOR_PLAN = "reserve_for_plan"
    RELEASE_RESERVATION = "release_reservation"
    CONSUME_FOR_MEAL = "consume_for_meal"
    DELIVERY_IMPORT = "delivery_import"
    DELIVERY_REVERSAL = "delivery_reversal"


class KitchenAllocationStatus(StrEnum):
    RESERVED = "reserved"
    RELEASED = "released"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class KitchenStockLot:
    id: str
    user_id: str
    product_id: str
    product_name: str
    source_type: KitchenStockSourceType
    source_id: str | None
    country_code: CountryCode | None
    unit: str
    base_unit: str
    quantity_on_hand: float
    quantity_reserved: float
    quantity_consumed: float
    base_quantity_on_hand: float
    base_quantity_reserved: float
    base_quantity_consumed: float
    delivered_at: datetime | None
    expires_at: datetime | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KitchenMovement:
    id: str
    user_id: str
    product_id: str
    product_name: str
    stock_lot_id: str | None
    movement_type: KitchenMovementType
    quantity: float
    base_quantity: float
    unit: str
    base_unit: str
    reference_type: str | None
    reference_id: str | None
    note: str
    metadata: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MealPlanInventoryAllocation:
    id: str
    user_id: str
    saved_plan_id: str
    effective_date: date | None
    slot: str
    meal_id: str
    product_id: str
    product_name: str
    stock_lot_id: str
    required_quantity: float
    reserved_quantity: float
    consumed_quantity: float
    unit: str
    base_unit: str
    base_required_quantity: float
    base_reserved_quantity: float
    base_consumed_quantity: float
    status: KitchenAllocationStatus
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime
