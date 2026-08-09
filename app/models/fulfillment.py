from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ChefFulfillmentStatus(StrEnum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    PREPARING = "preparing"
    READY_FOR_DELIVERY = "ready_for_delivery"


class ShopperFulfillmentStatus(StrEnum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    SHOPPING = "shopping"
    PACKED = "packed"


@dataclass(frozen=True, slots=True)
class AssignmentHistoryEntry:
    action: str
    worker_id: str | None
    actor_user_id: str | None
    note: str
    created_at: datetime
