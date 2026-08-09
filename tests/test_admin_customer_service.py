from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.billing import (
    SubscriptionAccount,
    SubscriptionPlanCode,
    SubscriptionStatus,
    WalletAccount,
    WalletAccountStatus,
)
from app.models.user import User, UserType
from app.services.admin_customer_service import (
    AdminCustomerService,
    CustomerNotFoundError,
    CustomerSubscriptionCancelFailedError,
    CustomerSubscriptionNotActiveError,
)
from app.services.billing_service import BillingService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user(*, user_id: str = "cust-1", name: str = "Ada", email: str = "ada@example.com") -> User:
    return User(
        id=user_id,
        name=name,
        email=email,
        password_hash="hash",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


class FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self._users = {user.id: user for user in users}

    def find_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def list_users(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        user_type: UserType | None = None,
    ) -> tuple[list[User], int]:
        items = list(self._users.values())
        if user_type is not None:
            items = [user for user in items if user_type in user.user_types]
        return items[(page - 1) * page_size : page * page_size], len(items)


class FakeSubscriptionRepository:
    def __init__(self) -> None:
        self.items: dict[str, SubscriptionAccount] = {}

    def get_by_user_id(self, *, user_id: str) -> SubscriptionAccount | None:
        return self.items.get(user_id)

    def ensure_default_for_user(self, *, user_id: str, currency: str = "GBP") -> SubscriptionAccount:
        existing = self.items.get(user_id)
        if existing is not None:
            return existing
        return self.upsert_subscription(
            user_id=user_id,
            plan_code=SubscriptionPlanCode.FREE,
            status=SubscriptionStatus.INACTIVE,
            provider="stripe",
            price_minor=0,
            currency=currency,
            is_premium=False,
            started_at=None,
            expires_at=None,
            renewal_at=None,
            original_transaction_id=None,
            latest_transaction_id=None,
            provider_payload={},
        )

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


class FakeWalletLedgerRepository:
    def list_for_user(self, *, user_id: str, before: str | None, limit: int):
        return [], None


class FakeOrderRepository:
    def __init__(self, orders: list | None = None) -> None:
        self._orders = orders or []

    def list_orders_for_user(self, *, user_id: str, before: str | None, limit: int):
        items = [order for order in self._orders if order.user_id == user_id]
        return items[:limit], None


class FakeMealOrderRepository:
    def __init__(self, orders: list | None = None) -> None:
        self._orders = orders or []

    def list_orders_for_user(self, *, user_id: str, before: str | None, limit: int):
        items = [order for order in self._orders if order.user_id == user_id]
        return items[:limit], None


class FakeStripeGateway:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.canceled_subscription_ids: list[str] = []

    def cancel_subscription(self, *, subscription_id: str):
        if self.should_fail:
            raise RuntimeError("stripe boom")
        self.canceled_subscription_ids.append(subscription_id)
        return None


class FakeAdminCustomerAuditRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, *, user_id: str, action: str, details: dict, actor_user_id: str) -> dict:
        entry = {
            "user_id": user_id,
            "action": action,
            "details": details,
            "actor_user_id": actor_user_id,
            "created_at": utc_now(),
        }
        self.entries.append(entry)
        return entry

    def list_for_user(self, *, user_id: str) -> list[dict]:
        return [entry for entry in self.entries if entry["user_id"] == user_id]


class FakeSubscriptionCommunicationService:
    def __init__(self) -> None:
        self.started_calls: list[dict] = []
        self.canceled_calls: list[dict] = []

    def notify_subscription_started(self, *, user_id: str, plan_name: str, idempotency_key: str) -> None:
        self.started_calls.append({"user_id": user_id})

    def notify_subscription_canceled(self, *, user_id: str, plan_name: str, idempotency_key: str) -> None:
        self.canceled_calls.append({"user_id": user_id})


class AdminCustomerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_repo = FakeUserRepository([build_user()])
        self.subscription_repo = FakeSubscriptionRepository()
        self.wallet_repo = FakeWalletAccountRepository()
        self.ledger_repo = FakeWalletLedgerRepository()
        self.order_repo = FakeOrderRepository()
        self.meal_order_repo = FakeMealOrderRepository()
        self.stripe_gateway = FakeStripeGateway()
        self.audit_repo = FakeAdminCustomerAuditRepository()
        self.communication_service = FakeSubscriptionCommunicationService()

        self.billing_service = BillingService(
            subscription_repository=self.subscription_repo,
            wallet_account_repository=self.wallet_repo,
            wallet_ledger_repository=self.ledger_repo,
            subscription_communication_service=self.communication_service,
        )
        self.service = AdminCustomerService(
            user_repository=self.user_repo,
            subscription_repository=self.subscription_repo,
            order_repository=self.order_repo,
            meal_order_repository=self.meal_order_repo,
            billing_service=self.billing_service,
            stripe_gateway=self.stripe_gateway,
            admin_customer_audit_repository=self.audit_repo,
        )

    def _activate_premium(self, *, user_id: str, provider: str) -> None:
        self.subscription_repo.upsert_subscription(
            user_id=user_id,
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            provider=provider,
            price_minor=900,
            currency="GBP",
            is_premium=True,
            started_at=utc_now(),
            expires_at=None,
            renewal_at=None,
            original_transaction_id="orig-1",
            latest_transaction_id="latest-1",
            provider_payload={"id": "sub_stripe_123"} if provider == "stripe" else {},
        )

    def test_list_customers_filters_to_customer_type(self) -> None:
        items, total = self.service.list_customers(page=1, page_size=20, search=None)

        self.assertEqual(total, 1)
        self.assertEqual(items[0].id, "cust-1")

    def test_get_customer_detail_raises_when_missing(self) -> None:
        with self.assertRaises(CustomerNotFoundError):
            self.service.get_customer_detail(user_id="missing")

    def test_get_customer_detail_returns_subscription_and_wallet(self) -> None:
        detail = self.service.get_customer_detail(user_id="cust-1")

        self.assertEqual(detail.user.id, "cust-1")
        self.assertEqual(detail.billing_overview.subscription.plan_code, SubscriptionPlanCode.FREE)
        self.assertEqual(detail.recent_grocery_orders, [])
        self.assertEqual(detail.recent_meal_orders, [])

    def test_cancel_subscription_raises_when_not_active(self) -> None:
        with self.assertRaises(CustomerSubscriptionNotActiveError):
            self.service.cancel_subscription(user_id="cust-1", reason="test", actor_user_id="admin-1")

    def test_cancel_subscription_stripe_calls_gateway_and_syncs_local_state(self) -> None:
        self._activate_premium(user_id="cust-1", provider="stripe")

        response = self.service.cancel_subscription(user_id="cust-1", reason="requested by user", actor_user_id="admin-1")

        self.assertFalse(response.is_premium)
        self.assertEqual(self.stripe_gateway.canceled_subscription_ids, ["sub_stripe_123"])
        self.assertEqual(len(self.communication_service.canceled_calls), 1)
        self.assertEqual(len(self.audit_repo.entries), 1)
        self.assertEqual(self.audit_repo.entries[0]["action"], "subscription_canceled")
        self.assertEqual(self.audit_repo.entries[0]["actor_user_id"], "admin-1")

    def test_cancel_subscription_apple_skips_gateway_call(self) -> None:
        self._activate_premium(user_id="cust-1", provider="apple")

        response = self.service.cancel_subscription(user_id="cust-1", reason="requested by user", actor_user_id="admin-1")

        self.assertFalse(response.is_premium)
        self.assertEqual(self.stripe_gateway.canceled_subscription_ids, [])
        self.assertEqual(len(self.communication_service.canceled_calls), 1)

    def test_cancel_subscription_aborts_when_stripe_call_fails(self) -> None:
        self._activate_premium(user_id="cust-1", provider="stripe")
        self.stripe_gateway.should_fail = True

        with self.assertRaises(CustomerSubscriptionCancelFailedError):
            self.service.cancel_subscription(user_id="cust-1", reason="test", actor_user_id="admin-1")

        self.assertTrue(self.subscription_repo.items["cust-1"].is_premium)
        self.assertEqual(self.communication_service.canceled_calls, [])
        self.assertEqual(self.audit_repo.entries, [])


if __name__ == "__main__":
    unittest.main()
