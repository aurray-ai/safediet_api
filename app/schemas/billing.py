from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.billing import (
    ChargeType,
    CheckoutRoute,
    SubscriptionPlanCode,
    SubscriptionStatus,
    WalletAccountStatus,
    WalletFundingMethod,
    WalletLedgerDirection,
    WalletLedgerEntryType,
)


class SubscriptionSnapshotResponse(BaseModel):
    plan_code: SubscriptionPlanCode
    plan_name: str
    status: SubscriptionStatus
    provider: str
    price_minor: int = Field(ge=0)
    currency: str
    is_premium: bool = False
    started_at: datetime | None = None
    expires_at: datetime | None = None
    renewal_at: datetime | None = None


class WalletSnapshotResponse(BaseModel):
    currency: str
    status: WalletAccountStatus
    available_balance_minor: int = Field(ge=0)
    held_balance_minor: int = Field(ge=0)
    lifetime_credited_minor: int = Field(ge=0)
    lifetime_debited_minor: int = Field(ge=0)


class WalletTransactionResponse(BaseModel):
    id: str
    entry_type: WalletLedgerEntryType
    direction: WalletLedgerDirection
    amount_minor: int = Field(ge=0)
    currency: str
    reference_type: str
    reference_id: str
    funding_method: WalletFundingMethod | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WalletTransactionsListResponse(BaseModel):
    items: list[WalletTransactionResponse]
    next_cursor: str | None = None


class BillingOverviewResponse(BaseModel):
    subscription: SubscriptionSnapshotResponse
    wallet: WalletSnapshotResponse
    recent_transactions: list[WalletTransactionResponse] = Field(default_factory=list)


class PaymentMethodSummaryResponse(BaseModel):
    id: str
    provider: str
    type: str
    brand: str | None = None
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    display_label: str
    is_default: bool = False


class PaymentMethodsListResponse(BaseModel):
    items: list[PaymentMethodSummaryResponse] = Field(default_factory=list)


class WalletTopupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int = Field(ge=100, le=500_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    funding_method: WalletFundingMethod = WalletFundingMethod.SANDBOX
    idempotency_key: str = Field(min_length=8, max_length=200)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class WalletTopupResponse(BaseModel):
    wallet: WalletSnapshotResponse
    transaction: WalletTransactionResponse
    message: str


class StripeWalletTopupIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int = Field(ge=100, le=500_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    funding_method: WalletFundingMethod
    idempotency_key: str = Field(min_length=8, max_length=200)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class StripeWalletTopupIntentResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
    amount_minor: int
    currency: str
    publishable_key: str | None = None
    message: str


class StripeSubscriptionSetupIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: SubscriptionPlanCode = SubscriptionPlanCode.PREMIUM_MONTHLY
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    idempotency_key: str = Field(min_length=8, max_length=200)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class StripeSubscriptionSetupIntentResponse(BaseModel):
    setup_intent_id: str
    setup_intent_client_secret: str
    customer_id: str
    currency: str
    publishable_key: str | None = None
    message: str


class WalletTopupConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int = Field(ge=100, le=500_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    funding_method: WalletFundingMethod
    provider: str = Field(min_length=1, max_length=80)
    provider_reference_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class SubscriptionSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: SubscriptionPlanCode
    status: SubscriptionStatus
    provider: str = Field(min_length=1, max_length=80)
    price_minor: int = Field(ge=0, le=5_000_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    is_premium: bool
    started_at: datetime | None = None
    expires_at: datetime | None = None
    renewal_at: datetime | None = None
    original_transaction_id: str | None = Field(default=None, max_length=200)
    latest_transaction_id: str | None = Field(default=None, max_length=200)
    provider_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class StripeWebhookResponse(BaseModel):
    received: bool = True


class CheckoutEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charge_type: ChargeType
    amount_minor: int = Field(ge=0, le=5_000_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    reference_type: str = Field(min_length=1, max_length=120)
    reference_id: str = Field(min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_checkout_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class CheckoutEvaluationResponse(BaseModel):
    route: CheckoutRoute
    wallet_available_minor: int = Field(ge=0)
    wallet_shortfall_minor: int = Field(ge=0)
    amount_minor: int = Field(ge=0)
    currency: str
    wallet_eligible: bool
    allowed_funding_methods: list[WalletFundingMethod] = Field(default_factory=list)
    message: str
