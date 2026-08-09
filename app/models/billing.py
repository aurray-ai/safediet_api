from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class SubscriptionPlanCode(StrEnum):
    FREE = "free"
    PREMIUM_MONTHLY = "premium_monthly"


class SubscriptionStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    GRACE_PERIOD = "grace_period"
    PAST_DUE = "past_due"
    EXPIRED = "expired"
    CANCELED = "canceled"


class WalletAccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class WalletLedgerEntryType(StrEnum):
    TOPUP_CREDIT = "topup_credit"
    REWARD_CREDIT = "reward_credit"
    ADJUSTMENT_CREDIT = "adjustment_credit"
    ADJUSTMENT_DEBIT = "adjustment_debit"
    PURCHASE_HOLD = "purchase_hold"
    PURCHASE_HOLD_RELEASE = "purchase_hold_release"
    PURCHASE_CAPTURE = "purchase_capture"
    REFUND_CREDIT = "refund_credit"


class WalletLedgerDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class WalletFundingMethod(StrEnum):
    APPLE_PAY = "apple_pay"
    CARD = "card"
    SANDBOX = "sandbox"


class ChargeType(StrEnum):
    SUBSCRIPTION = "subscription"
    GROCERY_ORDER = "grocery_order"
    MEAL_ORDER = "meal_order"
    CHEF_REQUEST = "chef_request"
    SERVICE_FEE = "service_fee"


class CheckoutRoute(StrEnum):
    STRIPE_SUBSCRIPTION_CHECKOUT = "stripe_subscription_checkout"
    WALLET_ONLY = "wallet_only"
    DIRECT_PAY = "direct_pay"
    WALLET_THEN_DIRECT_PAY = "wallet_then_direct_pay"
    FUND_WALLET_FIRST = "fund_wallet_first"
    BLOCKED = "blocked"


class CheckoutPaymentMethod(StrEnum):
    CARD = "card"
    WALLET = "wallet"
    PAYPAL = "paypal"
    KLARNA = "klarna"


@dataclass(frozen=True, slots=True)
class SubscriptionAccount:
    id: str
    user_id: str
    plan_code: SubscriptionPlanCode
    status: SubscriptionStatus
    provider: str
    price_minor: int
    currency: str
    is_premium: bool
    started_at: datetime | None
    expires_at: datetime | None
    renewal_at: datetime | None
    original_transaction_id: str | None
    latest_transaction_id: str | None
    provider_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WalletAccount:
    id: str
    user_id: str
    currency: str
    status: WalletAccountStatus
    available_balance_minor: int
    held_balance_minor: int
    lifetime_credited_minor: int
    lifetime_debited_minor: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WalletLedgerEntry:
    id: str
    wallet_account_id: str
    user_id: str
    entry_type: WalletLedgerEntryType
    direction: WalletLedgerDirection
    amount_minor: int
    currency: str
    reference_type: str
    reference_id: str
    funding_method: WalletFundingMethod | None
    idempotency_key: str | None
    metadata: dict[str, Any]
    created_at: datetime
