from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.billing import (
    ChargeType,
    CheckoutRoute,
    SubscriptionAccount,
    SubscriptionPlanCode,
    SubscriptionStatus,
    WalletAccount,
    WalletAccountStatus,
    WalletFundingMethod,
    WalletLedgerDirection,
    WalletLedgerEntry,
    WalletLedgerEntryType,
)
from app.models.user import User, UserType
from app.services.billing_service import (
    BillingService,
    CheckoutEvaluationInput,
    SubscriptionSyncInput,
    WalletTopupConfirmationInput,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeSubscriptionRepository:
    def __init__(self) -> None:
        self.items: dict[str, SubscriptionAccount] = {}

    def get_by_user_id(self, *, user_id: str) -> SubscriptionAccount | None:
        return self.items.get(user_id)

    def ensure_default_for_user(self, *, user_id: str, currency: str = "GBP") -> SubscriptionAccount:
        existing = self.items.get(user_id)
        if existing is not None:
            return existing
        item = SubscriptionAccount(
            id=f"sub-{user_id}",
            user_id=user_id,
            plan_code=SubscriptionPlanCode.FREE,
            status=SubscriptionStatus.INACTIVE,
            provider="stripe",
            price_minor=900,
            currency=currency,
            is_premium=False,
            started_at=None,
            expires_at=None,
            renewal_at=None,
            original_transaction_id=None,
            latest_transaction_id=None,
            provider_payload={},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[user_id] = item
        return item

    def upsert_subscription(
        self,
        *,
        user_id: str,
        plan_code: SubscriptionPlanCode,
        status: SubscriptionStatus,
        provider: str,
        price_minor: int,
        currency: str,
        is_premium: bool,
        started_at: datetime | None,
        expires_at: datetime | None,
        renewal_at: datetime | None,
        original_transaction_id: str | None,
        latest_transaction_id: str | None,
        provider_payload: dict,
    ) -> SubscriptionAccount:
        item = SubscriptionAccount(
            id=f"sub-{user_id}",
            user_id=user_id,
            plan_code=plan_code,
            status=status,
            provider=provider,
            price_minor=price_minor,
            currency=currency,
            is_premium=is_premium,
            started_at=started_at,
            expires_at=expires_at,
            renewal_at=renewal_at,
            original_transaction_id=original_transaction_id,
            latest_transaction_id=latest_transaction_id,
            provider_payload=dict(provider_payload),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[user_id] = item
        return item


class FakeWalletAccountRepository:
    def __init__(self) -> None:
        self.items: dict[str, WalletAccount] = {}

    def get_by_user_id(self, *, user_id: str) -> WalletAccount | None:
        return self.items.get(user_id)

    def ensure_default_for_user(self, *, user_id: str, currency: str = "GBP") -> WalletAccount:
        existing = self.items.get(user_id)
        if existing is not None:
            return existing
        item = WalletAccount(
            id=f"wallet-{user_id}",
            user_id=user_id,
            currency=currency,
            status=WalletAccountStatus.ACTIVE,
            available_balance_minor=0,
            held_balance_minor=0,
            lifetime_credited_minor=0,
            lifetime_debited_minor=0,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[user_id] = item
        return item

    def apply_balance_delta(
        self,
        *,
        wallet_account_id: str,
        available_delta_minor: int = 0,
        held_delta_minor: int = 0,
        credited_delta_minor: int = 0,
        debited_delta_minor: int = 0,
    ) -> WalletAccount:
        user_id = wallet_account_id.removeprefix("wallet-")
        current = self.items[user_id]
        updated = WalletAccount(
            id=current.id,
            user_id=current.user_id,
            currency=current.currency,
            status=current.status,
            available_balance_minor=current.available_balance_minor + available_delta_minor,
            held_balance_minor=current.held_balance_minor + held_delta_minor,
            lifetime_credited_minor=current.lifetime_credited_minor + credited_delta_minor,
            lifetime_debited_minor=current.lifetime_debited_minor + debited_delta_minor,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[user_id] = updated
        return updated


class FakeWalletLedgerRepository:
    def __init__(self) -> None:
        self.items: list[WalletLedgerEntry] = []

    def create_entry(
        self,
        *,
        wallet_account_id: str,
        user_id: str,
        entry_type: WalletLedgerEntryType,
        direction: WalletLedgerDirection,
        amount_minor: int,
        currency: str,
        reference_type: str,
        reference_id: str,
        funding_method: WalletFundingMethod | None,
        idempotency_key: str | None,
        metadata: dict,
    ) -> WalletLedgerEntry:
        entry = WalletLedgerEntry(
            id=f"entry-{len(self.items) + 1}",
            wallet_account_id=wallet_account_id,
            user_id=user_id,
            entry_type=entry_type,
            direction=direction,
            amount_minor=amount_minor,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id,
            funding_method=funding_method,
            idempotency_key=idempotency_key,
            metadata=dict(metadata),
            created_at=utc_now(),
        )
        self.items.append(entry)
        return entry

    def get_by_idempotency_key(self, *, idempotency_key: str) -> WalletLedgerEntry | None:
        for item in self.items:
            if item.idempotency_key == idempotency_key:
                return item
        return None

    def get_by_reference_id(
        self,
        *,
        reference_type: str,
        reference_id: str,
    ) -> WalletLedgerEntry | None:
        for item in self.items:
            if item.reference_type == reference_type and item.reference_id == reference_id:
                return item
        return None

    def list_for_user(self, *, user_id: str, before: str | None, limit: int) -> tuple[list[WalletLedgerEntry], str | None]:
        items = [item for item in self.items if item.user_id == user_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit], None


class FakeSubscriptionCommunicationService:
    def __init__(self) -> None:
        self.started_calls: list[dict] = []
        self.canceled_calls: list[dict] = []

    def notify_subscription_started(self, *, user_id: str, plan_name: str, idempotency_key: str) -> None:
        self.started_calls.append(
            {"user_id": user_id, "plan_name": plan_name, "idempotency_key": idempotency_key}
        )

    def notify_subscription_canceled(self, *, user_id: str, plan_name: str, idempotency_key: str) -> None:
        self.canceled_calls.append(
            {"user_id": user_id, "plan_name": plan_name, "idempotency_key": idempotency_key}
        )


class FakeStripeGateway:
    def retrieve_payment_method(self, *, payment_method_id: str, customer_id: str | None = None):
        return type(
            "FakeStripePaymentMethodDetails",
            (),
            {
                "payment_method_id": payment_method_id,
                "payment_method_type": "card",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 12,
                "exp_year": 2030,
            },
        )()


class BillingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.subscription_repo = FakeSubscriptionRepository()
        self.wallet_repo = FakeWalletAccountRepository()
        self.ledger_repo = FakeWalletLedgerRepository()
        self.stripe_gateway = FakeStripeGateway()
        self.communication_service = FakeSubscriptionCommunicationService()
        self.service = BillingService(
            subscription_repository=self.subscription_repo,
            wallet_account_repository=self.wallet_repo,
            wallet_ledger_repository=self.ledger_repo,
            subscription_communication_service=self.communication_service,
        )
        self.user = User(
            id="user-1",
            name="Favour",
            email="favour@example.com",
            password_hash="hash",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )

    def test_overview_lazy_provisions_wallet_and_subscription(self) -> None:
        response = self.service.get_overview(current_user=self.user)

        self.assertEqual(response.subscription.plan_code, SubscriptionPlanCode.FREE)
        self.assertEqual(response.wallet.available_balance_minor, 0)
        self.assertEqual(response.recent_transactions, [])

    def test_overview_reports_not_premium_for_stale_canceled_subscription(self) -> None:
        # Simulates the flag going stale: is_premium is still True from before
        # cancellation, but status has already moved to CANCELED. The response
        # must not let the account keep member pricing off a stale flag.
        self.subscription_repo.items[self.user.id] = SubscriptionAccount(
            id=f"sub-{self.user.id}",
            user_id=self.user.id,
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD,
            status=SubscriptionStatus.CANCELED,
            provider="stripe",
            price_minor=900,
            currency="GBP",
            is_premium=True,
            started_at=utc_now(),
            expires_at=utc_now(),
            renewal_at=None,
            original_transaction_id="orig-1",
            latest_transaction_id="latest-1",
            provider_payload={},
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        response = self.service.get_overview(current_user=self.user)

        self.assertFalse(response.subscription.is_premium)

    def test_topup_creates_ledger_credit_and_updates_wallet(self) -> None:
        response = self.service.topup_wallet(
            current_user=self.user,
            amount_minor=2500,
            currency="GBP",
            funding_method=WalletFundingMethod.APPLE_PAY,
            idempotency_key="topup-user-1-2500-1",
        )

        self.assertEqual(response.wallet.available_balance_minor, 2500)
        self.assertEqual(response.transaction.entry_type, WalletLedgerEntryType.TOPUP_CREDIT)
        self.assertEqual(response.transaction.funding_method, WalletFundingMethod.APPLE_PAY)
        self.assertEqual(len(self.ledger_repo.items), 1)

    def test_confirm_wallet_topup_uses_provider_reference(self) -> None:
        response = self.service.confirm_wallet_topup(
            current_user=self.user,
            payload=WalletTopupConfirmationInput(
                amount_minor=1500,
                currency="GBP",
                funding_method=WalletFundingMethod.CARD,
                provider="stripe",
                provider_reference_id="pi_1234567890",
                idempotency_key="wallet-topup-user-1-1500-1",
                metadata={"source": "payment_sheet"},
            ),
        )

        self.assertEqual(response.wallet.available_balance_minor, 1500)
        self.assertEqual(response.transaction.reference_id, "pi_1234567890")
        self.assertEqual(response.transaction.metadata["provider"], "stripe")

    def test_sync_subscription_updates_snapshot(self) -> None:
        response = self.service.sync_subscription(
            current_user=self.user,
            payload=SubscriptionSyncInput(
                plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD,
                status=SubscriptionStatus.ACTIVE,
                provider="stripe",
                price_minor=900,
                currency="GBP",
                is_premium=True,
                started_at=utc_now(),
                expires_at=None,
                renewal_at=None,
                original_transaction_id="orig-1",
                latest_transaction_id="latest-1",
                provider_payload={"environment": "sandbox"},
            ),
        )

        self.assertEqual(response.plan_code, SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD)
        self.assertTrue(response.is_premium)
        self.assertEqual(self.subscription_repo.items[self.user.id].latest_transaction_id, "latest-1")
        self.assertEqual(len(self.communication_service.started_calls), 1)
        self.assertEqual(self.communication_service.started_calls[0]["user_id"], self.user.id)
        self.assertEqual(self.communication_service.canceled_calls, [])

    def test_sync_subscription_does_not_renotify_on_repeated_active_sync(self) -> None:
        payload = SubscriptionSyncInput(
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD,
            status=SubscriptionStatus.ACTIVE,
            provider="stripe",
            price_minor=900,
            currency="GBP",
            is_premium=True,
            started_at=utc_now(),
            expires_at=None,
            renewal_at=None,
            original_transaction_id="orig-1",
            latest_transaction_id="latest-1",
            provider_payload={"environment": "sandbox"},
        )

        self.service.sync_subscription(current_user=self.user, payload=payload)
        self.service.sync_subscription(current_user=self.user, payload=payload)

        self.assertEqual(len(self.communication_service.started_calls), 1)

    def test_sync_subscription_notifies_on_cancellation(self) -> None:
        self.service.sync_subscription(
            current_user=self.user,
            payload=SubscriptionSyncInput(
                plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD,
                status=SubscriptionStatus.ACTIVE,
                provider="stripe",
                price_minor=900,
                currency="GBP",
                is_premium=True,
                started_at=utc_now(),
                expires_at=None,
                renewal_at=None,
                original_transaction_id="orig-1",
                latest_transaction_id="latest-1",
                provider_payload={},
            ),
        )
        self.communication_service.started_calls.clear()

        self.service.sync_subscription(
            current_user=self.user,
            payload=SubscriptionSyncInput(
                plan_code=SubscriptionPlanCode.FREE,
                status=SubscriptionStatus.CANCELED,
                provider="stripe",
                price_minor=0,
                currency="GBP",
                is_premium=False,
                started_at=None,
                expires_at=utc_now(),
                renewal_at=None,
                original_transaction_id="orig-1",
                latest_transaction_id="latest-1",
                provider_payload={},
            ),
        )

        self.assertEqual(self.communication_service.started_calls, [])
        self.assertEqual(len(self.communication_service.canceled_calls), 1)
        self.assertEqual(self.communication_service.canceled_calls[0]["user_id"], self.user.id)

    def test_checkout_uses_wallet_when_balance_is_enough(self) -> None:
        self.service.topup_wallet(
            current_user=self.user,
            amount_minor=3000,
            currency="GBP",
            funding_method=WalletFundingMethod.SANDBOX,
            idempotency_key="topup-user-1-3000-1",
        )

        response = self.service.evaluate_checkout(
            current_user=self.user,
            payload=CheckoutEvaluationInput(
                charge_type=ChargeType.GROCERY_ORDER,
                amount_minor=1800,
                currency="GBP",
                reference_type="grocery_basket",
                reference_id="basket-1",
                metadata={},
            ),
        )

        self.assertEqual(response.route, CheckoutRoute.WALLET_ONLY)
        self.assertEqual(response.wallet_shortfall_minor, 0)

    def test_checkout_routes_subscription_to_stripe_checkout(self) -> None:
        response = self.service.evaluate_checkout(
            current_user=self.user,
            payload=CheckoutEvaluationInput(
                charge_type=ChargeType.SUBSCRIPTION,
                amount_minor=900,
                currency="USD",
                reference_type="premium_plan",
                reference_id="premium-monthly",
                metadata={},
            ),
        )

        self.assertEqual(response.route, CheckoutRoute.STRIPE_SUBSCRIPTION_CHECKOUT)
        self.assertFalse(response.wallet_eligible)

    def test_topup_is_idempotent_for_repeated_key(self) -> None:
        first = self.service.topup_wallet(
            current_user=self.user,
            amount_minor=2500,
            currency="GBP",
            funding_method=WalletFundingMethod.SANDBOX,
            idempotency_key="topup-user-1-2500-repeat",
        )
        second = self.service.topup_wallet(
            current_user=self.user,
            amount_minor=2500,
            currency="GBP",
            funding_method=WalletFundingMethod.SANDBOX,
            idempotency_key="topup-user-1-2500-repeat",
        )

        self.assertEqual(first.transaction.id, second.transaction.id)
        self.assertEqual(second.wallet.available_balance_minor, 2500)
        self.assertEqual(len(self.ledger_repo.items), 1)

    def test_list_payment_methods_returns_saved_stripe_card(self) -> None:
        self.subscription_repo.upsert_subscription(
            user_id=self.user.id,
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD,
            status=SubscriptionStatus.ACTIVE,
            provider="stripe",
            price_minor=900,
            currency="GBP",
            is_premium=True,
            started_at=utc_now(),
            expires_at=None,
            renewal_at=None,
            original_transaction_id="orig-1",
            latest_transaction_id="latest-1",
            provider_payload={
                "stripe_customer_id": "cus_123",
                "stripe_payment_method_id": "pm_123",
            },
        )

        response = self.service.list_payment_methods(
            current_user=self.user,
            stripe_gateway=self.stripe_gateway,
        )

        self.assertEqual(len(response.items), 1)
        self.assertEqual(response.items[0].display_label, "Visa •••• 4242")
        self.assertTrue(response.items[0].is_default)


if __name__ == "__main__":
    unittest.main()
