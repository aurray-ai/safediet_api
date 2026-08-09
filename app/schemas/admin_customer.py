from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.order import OrderStatus
from app.schemas.billing import SubscriptionSnapshotResponse, WalletSnapshotResponse


class AdminCustomerSummaryResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime


class AdminCustomerListResponse(BaseModel):
    items: list[AdminCustomerSummaryResponse]
    total: int
    page: int
    page_size: int


class AdminCustomerOrderSummaryResponse(BaseModel):
    id: str
    order_number: str
    kind: Literal["grocery", "meal"]
    status: OrderStatus
    total_minor: int
    currency: str
    created_at: datetime


class AdminCustomerDetailResponse(BaseModel):
    id: str
    name: str
    email: str
    user_types: list[str]
    created_at: datetime
    subscription: SubscriptionSnapshotResponse
    wallet: WalletSnapshotResponse
    recent_orders: list[AdminCustomerOrderSummaryResponse]


class CancelCustomerSubscriptionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AdminCustomerAuditEntryResponse(BaseModel):
    action: str
    details: dict
    actor_user_id: str
    created_at: datetime


class AdminCustomerAuditListResponse(BaseModel):
    items: list[AdminCustomerAuditEntryResponse]
