from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.models.billing import (
    ChargeType,
    CheckoutRoute,
    SubscriptionAccount,
    SubscriptionPlanCode,
    SubscriptionStatus,
    WalletAccount,
    WalletFundingMethod,
    WalletLedgerDirection,
    WalletLedgerEntry,
    WalletLedgerEntryType,
)
from app.models.user import User
from app.repositories.subscription_account_repository import SubscriptionAccountRepository
from app.repositories.wallet_account_repository import WalletAccountRepository
from app.repositories.wallet_ledger_repository import WalletLedgerRepository
from app.schemas.billing import (
    BillingOverviewResponse,
    CheckoutEvaluationResponse,
    PaymentMethodsListResponse,
    PaymentMethodSummaryResponse,
    SubscriptionSnapshotResponse,
    WalletSnapshotResponse,
    WalletTopupResponse,
    WalletTransactionResponse,
    WalletTransactionsListResponse,
)
from app.services.subscription_communication_service import SubscriptionCommunicationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckoutEvaluationInput:
    charge_type: ChargeType
    amount_minor: int
    currency: str
    reference_type: str
    reference_id: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WalletTopupConfirmationInput:
    amount_minor: int
    currency: str
    funding_method: WalletFundingMethod
    provider: str
    provider_reference_id: str
    idempotency_key: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SubscriptionSyncInput:
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


class BillingService:
    def __init__(
        self,
        *,
        subscription_repository: SubscriptionAccountRepository,
        wallet_account_repository: WalletAccountRepository,
        wallet_ledger_repository: WalletLedgerRepository,
        subscription_communication_service: SubscriptionCommunicationService | None = None,
    ) -> None:
        self._subscription_repository = subscription_repository
        self._wallet_account_repository = wallet_account_repository
        self._wallet_ledger_repository = wallet_ledger_repository
        self._subscription_communication_service = subscription_communication_service

    def get_overview(self, *, current_user: User) -> BillingOverviewResponse:
        subscription = self._ensure_subscription_for_user_id(user_id=current_user.id)
        wallet = self._ensure_wallet_for_user_id(user_id=current_user.id)
        recent_transactions, _ = self._wallet_ledger_repository.list_for_user(
            user_id=current_user.id,
            before=None,
            limit=5,
        )
        return BillingOverviewResponse(
            subscription=self._to_subscription_response(subscription),
            wallet=self._to_wallet_response(wallet),
            recent_transactions=[self._to_transaction_response(item) for item in recent_transactions],
        )

    def get_subscription(self, *, current_user: User) -> SubscriptionSnapshotResponse:
        subscription = self._ensure_subscription_for_user_id(user_id=current_user.id)
        return self._to_subscription_response(subscription)

    def list_payment_methods(self, *, current_user: User, stripe_gateway) -> PaymentMethodsListResponse:
        subscription = self._ensure_subscription_for_user_id(user_id=current_user.id)
        provider_payload = dict(subscription.provider_payload or {})
        payment_method_id = str(provider_payload.get("stripe_payment_method_id") or "").strip()
        if not payment_method_id:
            return PaymentMethodsListResponse(items=[])

        customer_id = str(provider_payload.get("stripe_customer_id") or "").strip() or None
        details = None
        try:
            details = stripe_gateway.retrieve_payment_method(
                payment_method_id=payment_method_id,
                customer_id=customer_id,
            )
        except RuntimeError:
            details = None

        brand = None
        last4 = None
        exp_month = None
        exp_year = None
        payment_method_type = "card"
        if details is not None:
            brand = details.brand
            last4 = details.last4
            exp_month = details.exp_month
            exp_year = details.exp_year
            payment_method_type = details.payment_method_type
        else:
            brand = str(provider_payload.get("stripe_payment_method_brand") or "").strip() or None
            last4 = str(provider_payload.get("stripe_payment_method_last4") or "").strip() or None
            if provider_payload.get("stripe_payment_method_exp_month") is not None:
                exp_month = int(provider_payload.get("stripe_payment_method_exp_month") or 0) or None
            if provider_payload.get("stripe_payment_method_exp_year") is not None:
                exp_year = int(provider_payload.get("stripe_payment_method_exp_year") or 0) or None
            payment_method_type = str(provider_payload.get("stripe_payment_method_type") or "card")

        return PaymentMethodsListResponse(
            items=[
                PaymentMethodSummaryResponse(
                    id=payment_method_id,
                    provider="stripe",
                    type=payment_method_type,
                    brand=brand,
                    last4=last4,
                    exp_month=exp_month,
                    exp_year=exp_year,
                    display_label=self._payment_method_label(
                        brand=brand,
                        last4=last4,
                        payment_method_type=payment_method_type,
                    ),
                    is_default=True,
                )
            ]
        )

    def get_wallet(self, *, current_user: User) -> WalletSnapshotResponse:
        wallet = self._ensure_wallet_for_user_id(user_id=current_user.id)
        return self._to_wallet_response(wallet)

    def list_wallet_transactions(
        self,
        *,
        current_user: User,
        before: str | None,
        limit: int,
    ) -> WalletTransactionsListResponse:
        self._ensure_wallet_for_user_id(user_id=current_user.id)
        items, next_cursor = self._wallet_ledger_repository.list_for_user(
            user_id=current_user.id,
            before=before,
            limit=limit,
        )
        return WalletTransactionsListResponse(
            items=[self._to_transaction_response(item) for item in items],
            next_cursor=next_cursor,
        )

    def topup_wallet(
        self,
        *,
        current_user: User,
        amount_minor: int,
        currency: str,
        funding_method: WalletFundingMethod,
        idempotency_key: str,
    ) -> WalletTopupResponse:
        return self.confirm_wallet_topup_for_user_id(
            user_id=current_user.id,
            payload=WalletTopupConfirmationInput(
                amount_minor=amount_minor,
                currency=currency,
                funding_method=funding_method,
                provider="sandbox",
                provider_reference_id=uuid4().hex,
                idempotency_key=idempotency_key,
                metadata={"provider_mode": "sandbox"},
            ),
        )

    def confirm_wallet_topup(
        self,
        *,
        current_user: User,
        payload: WalletTopupConfirmationInput,
    ) -> WalletTopupResponse:
        return self.confirm_wallet_topup_for_user_id(user_id=current_user.id, payload=payload)

    def confirm_wallet_topup_for_user_id(
        self,
        *,
        user_id: str,
        payload: WalletTopupConfirmationInput,
    ) -> WalletTopupResponse:
        wallet = self._ensure_wallet_for_user_id(user_id=user_id, currency=payload.currency)
        if wallet.currency != payload.currency:
            raise ValueError("Wallet currency mismatch.")
        normalized_provider = str(payload.provider).strip()
        if len(normalized_provider) < 1:
            raise ValueError("A valid provider name is required.")
        normalized_provider_reference_id = str(payload.provider_reference_id).strip()
        if len(normalized_provider_reference_id) < 8:
            raise ValueError("A valid provider reference is required.")
        normalized_idempotency_key = (
            str(payload.idempotency_key).strip()
            if payload.idempotency_key is not None
            else normalized_provider_reference_id
        )
        if len(normalized_idempotency_key) < 8:
            raise ValueError("A valid idempotency key is required.")

        existing_transaction = self._wallet_ledger_repository.get_by_idempotency_key(
            idempotency_key=normalized_idempotency_key,
        )
        if existing_transaction is None:
            existing_transaction = self._wallet_ledger_repository.get_by_reference_id(
                reference_type="wallet_topup",
                reference_id=normalized_provider_reference_id,
            )
        if existing_transaction is not None:
            if existing_transaction.user_id != user_id:
                raise ValueError("Payment reference does not belong to the current user.")
            if (
                existing_transaction.currency != payload.currency
                or existing_transaction.amount_minor != payload.amount_minor
            ):
                raise ValueError("Payment reference is already used for a different wallet top-up.")
            return WalletTopupResponse(
                wallet=self._to_wallet_response(wallet),
                transaction=self._to_transaction_response(existing_transaction),
                message="Wallet top-up already processed.",
            )

        transaction = self._wallet_ledger_repository.create_entry(
            wallet_account_id=wallet.id,
            user_id=user_id,
            entry_type=WalletLedgerEntryType.TOPUP_CREDIT,
            direction=WalletLedgerDirection.CREDIT,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            reference_type="wallet_topup",
            reference_id=normalized_provider_reference_id,
            funding_method=payload.funding_method,
            idempotency_key=normalized_idempotency_key,
            metadata={
                **dict(payload.metadata or {}),
                "provider": normalized_provider,
                "provider_mode": "external" if normalized_provider != "sandbox" else "sandbox",
            },
        )
        updated_wallet = self._wallet_account_repository.apply_balance_delta(
            wallet_account_id=wallet.id,
            available_delta_minor=payload.amount_minor,
            credited_delta_minor=payload.amount_minor,
        )
        message = (
            "Wallet funded successfully."
            if normalized_provider != "sandbox"
            else "Wallet funded successfully in sandbox mode."
        )
        return WalletTopupResponse(
            wallet=self._to_wallet_response(updated_wallet),
            transaction=self._to_transaction_response(transaction),
            message=message,
        )

    def sync_subscription(
        self,
        *,
        current_user: User,
        payload: SubscriptionSyncInput,
    ) -> SubscriptionSnapshotResponse:
        return self.sync_subscription_for_user_id(user_id=current_user.id, payload=payload)

    def sync_subscription_for_user_id(
        self,
        *,
        user_id: str,
        payload: SubscriptionSyncInput,
    ) -> SubscriptionSnapshotResponse:
        previous = self._subscription_repository.get_by_user_id(user_id=user_id)
        was_premium = previous.is_premium if previous is not None else False

        subscription = self._subscription_repository.upsert_subscription(
            user_id=user_id,
            plan_code=payload.plan_code,
            status=payload.status,
            provider=payload.provider,
            price_minor=payload.price_minor,
            currency=payload.currency,
            is_premium=payload.is_premium,
            started_at=payload.started_at,
            expires_at=payload.expires_at,
            renewal_at=payload.renewal_at,
            original_transaction_id=payload.original_transaction_id,
            latest_transaction_id=payload.latest_transaction_id,
            provider_payload=payload.provider_payload,
        )

        try:
            self._notify_subscription_transition(user_id=user_id, was_premium=was_premium, subscription=subscription)
        except Exception:
            logger.exception("billing.sync_subscription.notification_failed user_id=%s", user_id)

        return self._to_subscription_response(subscription)

    def _notify_subscription_transition(
        self,
        *,
        user_id: str,
        was_premium: bool,
        subscription: SubscriptionAccount,
    ) -> None:
        if self._subscription_communication_service is None:
            return

        transaction_reference = subscription.latest_transaction_id or subscription.original_transaction_id or ""

        if not was_premium and subscription.is_premium:
            self._subscription_communication_service.notify_subscription_started(
                user_id=user_id,
                plan_name="Premium",
                idempotency_key=f"subscription_started:{user_id}:{transaction_reference}",
            )
        elif was_premium and not subscription.is_premium:
            self._subscription_communication_service.notify_subscription_canceled(
                user_id=user_id,
                plan_name="Premium",
                idempotency_key=f"subscription_canceled:{user_id}:{transaction_reference}",
            )

    def evaluate_checkout(
        self,
        *,
        current_user: User,
        payload: CheckoutEvaluationInput,
    ) -> CheckoutEvaluationResponse:
        wallet = self._ensure_wallet(current_user=current_user, currency=payload.currency)
        available_minor = wallet.available_balance_minor if wallet.currency == payload.currency else 0

        if payload.charge_type == ChargeType.SUBSCRIPTION:
            return CheckoutEvaluationResponse(
                route=CheckoutRoute.STRIPE_SUBSCRIPTION_CHECKOUT,
                wallet_available_minor=available_minor,
                wallet_shortfall_minor=max(payload.amount_minor - available_minor, 0),
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                wallet_eligible=False,
                allowed_funding_methods=[],
                message="Premium uses Stripe subscription billing.",
            )

        if payload.amount_minor == 0:
            return CheckoutEvaluationResponse(
                route=CheckoutRoute.WALLET_ONLY,
                wallet_available_minor=available_minor,
                wallet_shortfall_minor=0,
                amount_minor=0,
                currency=payload.currency,
                wallet_eligible=True,
                allowed_funding_methods=[],
                message="No payment is required for this action.",
            )

        shortfall = max(payload.amount_minor - available_minor, 0)
        if shortfall == 0:
            return CheckoutEvaluationResponse(
                route=CheckoutRoute.WALLET_ONLY,
                wallet_available_minor=available_minor,
                wallet_shortfall_minor=0,
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                wallet_eligible=True,
                allowed_funding_methods=[
                    WalletFundingMethod.APPLE_PAY,
                    WalletFundingMethod.CARD,
                ],
                message="Your wallet can cover this payment.",
            )

        if available_minor > 0:
            return CheckoutEvaluationResponse(
                route=CheckoutRoute.WALLET_THEN_DIRECT_PAY,
                wallet_available_minor=available_minor,
                wallet_shortfall_minor=shortfall,
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                wallet_eligible=True,
                allowed_funding_methods=[
                    WalletFundingMethod.APPLE_PAY,
                    WalletFundingMethod.CARD,
                ],
                message=f"Your wallet will cover part of the payment and {self._format_money(shortfall, payload.currency)} will be charged by card.",
            )

        return CheckoutEvaluationResponse(
            route=CheckoutRoute.DIRECT_PAY,
            wallet_available_minor=available_minor,
            wallet_shortfall_minor=shortfall,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            wallet_eligible=True,
            allowed_funding_methods=[
                WalletFundingMethod.APPLE_PAY,
                WalletFundingMethod.CARD,
            ],
            message=f"Card payment is required for {self._format_money(shortfall, payload.currency)}.",
        )

    def place_wallet_hold(
        self,
        *,
        user_id: str,
        amount_minor: int,
        currency: str,
        reference_type: str,
        reference_id: str,
        metadata: dict[str, Any],
    ) -> WalletTransactionResponse:
        wallet = self._ensure_wallet_for_user_id(user_id=user_id, currency=currency)
        if amount_minor <= 0:
            raise ValueError("Wallet hold amount must be greater than zero.")
        if wallet.available_balance_minor < amount_minor:
            raise ValueError("Wallet balance is insufficient for the requested hold.")
        hold_reference_type = f"{reference_type}_hold"
        existing = self._wallet_ledger_repository.get_by_reference_id(
            reference_type=hold_reference_type,
            reference_id=reference_id,
        )
        if existing is not None:
            return self._to_transaction_response(existing)
        transaction = self._wallet_ledger_repository.create_entry(
            wallet_account_id=wallet.id,
            user_id=user_id,
            entry_type=WalletLedgerEntryType.PURCHASE_HOLD,
            direction=WalletLedgerDirection.DEBIT,
            amount_minor=amount_minor,
            currency=currency,
            reference_type=hold_reference_type,
            reference_id=reference_id,
            funding_method=None,
            idempotency_key=f"{hold_reference_type}:{reference_id}",
            metadata=metadata,
        )
        self._wallet_account_repository.apply_balance_delta(
            wallet_account_id=wallet.id,
            available_delta_minor=-amount_minor,
            held_delta_minor=amount_minor,
        )
        return self._to_transaction_response(transaction)

    def release_wallet_hold(
        self,
        *,
        user_id: str,
        amount_minor: int,
        currency: str,
        reference_type: str,
        reference_id: str,
        metadata: dict[str, Any],
    ) -> WalletTransactionResponse:
        wallet = self._ensure_wallet_for_user_id(user_id=user_id, currency=currency)
        release_reference_type = f"{reference_type}_hold_release"
        existing = self._wallet_ledger_repository.get_by_reference_id(
            reference_type=release_reference_type,
            reference_id=reference_id,
        )
        if existing is not None:
            return self._to_transaction_response(existing)
        transaction = self._wallet_ledger_repository.create_entry(
            wallet_account_id=wallet.id,
            user_id=user_id,
            entry_type=WalletLedgerEntryType.PURCHASE_HOLD_RELEASE,
            direction=WalletLedgerDirection.CREDIT,
            amount_minor=amount_minor,
            currency=currency,
            reference_type=release_reference_type,
            reference_id=reference_id,
            funding_method=None,
            idempotency_key=f"{release_reference_type}:{reference_id}",
            metadata=metadata,
        )
        self._wallet_account_repository.apply_balance_delta(
            wallet_account_id=wallet.id,
            available_delta_minor=amount_minor,
            held_delta_minor=-amount_minor,
        )
        return self._to_transaction_response(transaction)

    def capture_wallet_hold(
        self,
        *,
        user_id: str,
        amount_minor: int,
        currency: str,
        reference_type: str,
        reference_id: str,
        metadata: dict[str, Any],
    ) -> WalletTransactionResponse:
        wallet = self._ensure_wallet_for_user_id(user_id=user_id, currency=currency)
        existing = self._wallet_ledger_repository.get_by_reference_id(
            reference_type=reference_type,
            reference_id=reference_id,
        )
        if existing is not None and existing.entry_type == WalletLedgerEntryType.PURCHASE_CAPTURE:
            return self._to_transaction_response(existing)
        transaction = self._wallet_ledger_repository.create_entry(
            wallet_account_id=wallet.id,
            user_id=user_id,
            entry_type=WalletLedgerEntryType.PURCHASE_CAPTURE,
            direction=WalletLedgerDirection.DEBIT,
            amount_minor=amount_minor,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id,
            funding_method=None,
            idempotency_key=f"{reference_type}:{reference_id}:capture",
            metadata=metadata,
        )
        self._wallet_account_repository.apply_balance_delta(
            wallet_account_id=wallet.id,
            held_delta_minor=-amount_minor,
            debited_delta_minor=amount_minor,
        )
        return self._to_transaction_response(transaction)

    def refund_to_wallet(
        self,
        *,
        user_id: str,
        amount_minor: int,
        currency: str,
        reference_type: str,
        reference_id: str,
        metadata: dict[str, Any],
    ) -> WalletTransactionResponse:
        wallet = self._ensure_wallet_for_user_id(user_id=user_id, currency=currency)
        refund_reference_type = f"{reference_type}_credit"
        transaction = self._wallet_ledger_repository.create_entry(
            wallet_account_id=wallet.id,
            user_id=user_id,
            entry_type=WalletLedgerEntryType.REFUND_CREDIT,
            direction=WalletLedgerDirection.CREDIT,
            amount_minor=amount_minor,
            currency=currency,
            reference_type=refund_reference_type,
            reference_id=reference_id,
            funding_method=None,
            idempotency_key=f"{refund_reference_type}:{reference_id}:{amount_minor}",
            metadata=metadata,
        )
        self._wallet_account_repository.apply_balance_delta(
            wallet_account_id=wallet.id,
            available_delta_minor=amount_minor,
            credited_delta_minor=amount_minor,
        )
        return self._to_transaction_response(transaction)

    def _ensure_subscription(
        self,
        *,
        current_user: User,
        currency: str = "GBP",
    ) -> SubscriptionAccount:
        return self._ensure_subscription_for_user_id(user_id=current_user.id, currency=currency)

    def _ensure_subscription_for_user_id(
        self,
        *,
        user_id: str,
        currency: str = "GBP",
    ) -> SubscriptionAccount:
        return self._subscription_repository.ensure_default_for_user(
            user_id=user_id,
            currency=currency,
        )

    def _ensure_wallet(
        self,
        *,
        current_user: User,
        currency: str = "GBP",
    ) -> WalletAccount:
        return self._ensure_wallet_for_user_id(user_id=current_user.id, currency=currency)

    def _ensure_wallet_for_user_id(
        self,
        *,
        user_id: str,
        currency: str = "GBP",
    ) -> WalletAccount:
        return self._wallet_account_repository.ensure_default_for_user(
            user_id=user_id,
            currency=currency,
        )

    @staticmethod
    def _to_subscription_response(item: SubscriptionAccount) -> SubscriptionSnapshotResponse:
        plan_name = (
            "Safediet Premium"
            if item.plan_code == SubscriptionPlanCode.PREMIUM_MONTHLY
            else "Safediet Free"
        )
        # A canceled/expired status unambiguously means the account is not premium,
        # regardless of what is_premium was last persisted as. This guards against
        # is_premium going stale when the source that's supposed to flip it (a Stripe
        # webhook, or the client's App Store entitlement sync) never fires.
        is_premium = item.is_premium and item.status not in (
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
        )
        return SubscriptionSnapshotResponse(
            plan_code=item.plan_code,
            plan_name=plan_name,
            status=item.status,
            provider=item.provider,
            price_minor=item.price_minor,
            currency=item.currency,
            is_premium=is_premium,
            started_at=item.started_at,
            expires_at=item.expires_at,
            renewal_at=item.renewal_at,
        )

    @staticmethod
    def _to_wallet_response(item: WalletAccount) -> WalletSnapshotResponse:
        return WalletSnapshotResponse(
            currency=item.currency,
            status=item.status,
            available_balance_minor=item.available_balance_minor,
            held_balance_minor=item.held_balance_minor,
            lifetime_credited_minor=item.lifetime_credited_minor,
            lifetime_debited_minor=item.lifetime_debited_minor,
        )

    @staticmethod
    def _to_transaction_response(item: WalletLedgerEntry) -> WalletTransactionResponse:
        return WalletTransactionResponse(
            id=item.id,
            entry_type=item.entry_type,
            direction=item.direction,
            amount_minor=item.amount_minor,
            currency=item.currency,
            reference_type=item.reference_type,
            reference_id=item.reference_id,
            funding_method=item.funding_method,
            metadata=item.metadata,
            created_at=item.created_at,
        )

    @staticmethod
    def _format_money(amount_minor: int, currency: str) -> str:
        major = amount_minor / 100
        symbol = "£" if currency.upper() == "GBP" else "$" if currency.upper() == "USD" else f"{currency.upper()} "
        return f"{symbol}{major:,.2f}"

    @staticmethod
    def _payment_method_label(*, brand: str | None, last4: str | None, payment_method_type: str) -> str:
        normalized_brand = (brand or "").strip().title()
        suffix = f" •••• {last4}" if last4 else ""
        if normalized_brand:
            return f"{normalized_brand}{suffix}"
        normalized_type = (payment_method_type or "card").strip().replace("_", " ").title()
        return f"{normalized_type}{suffix}".strip()
