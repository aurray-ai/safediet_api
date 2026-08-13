from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.v1.endpoints.admin_customers import (
    cancel_customer_subscription,
    get_customer,
    get_customer_audit_log,
    list_customers,
)
from app.models.billing import SubscriptionPlanCode, SubscriptionStatus, WalletAccountStatus
from app.models.user import User, UserType
from app.schemas.admin_customer import CancelCustomerSubscriptionRequest
from app.schemas.billing import BillingOverviewResponse, SubscriptionSnapshotResponse, WalletSnapshotResponse
from app.services.admin_customer_service import (
    AdminCustomerDetail,
    CustomerNotFoundError,
    CustomerSubscriptionCancelFailedError,
    CustomerSubscriptionNotActiveError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_admin() -> User:
    return User(
        id="admin-1",
        name="Admin",
        email="admin@example.com",
        password_hash="x",
        user_types=[UserType.PLATFORM_USER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_customer() -> User:
    return User(
        id="cust-1",
        name="Ada",
        email="ada@example.com",
        password_hash="x",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_billing_overview(*, is_premium: bool = False) -> BillingOverviewResponse:
    return BillingOverviewResponse(
        subscription=SubscriptionSnapshotResponse(
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY_STANDARD if is_premium else SubscriptionPlanCode.FREE,
            plan_name="Premium" if is_premium else "Free",
            status=SubscriptionStatus.ACTIVE if is_premium else SubscriptionStatus.INACTIVE,
            provider="stripe",
            price_minor=900 if is_premium else 0,
            currency="GBP",
            is_premium=is_premium,
        ),
        wallet=WalletSnapshotResponse(
            currency="GBP",
            status=WalletAccountStatus.ACTIVE,
            available_balance_minor=0,
            held_balance_minor=0,
            lifetime_credited_minor=0,
            lifetime_debited_minor=0,
        ),
        recent_transactions=[],
    )


def make_fake_order(*, order_id: str, created_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=order_id,
        order_number=f"GRO-{order_id}",
        status="delivered",
        currency="GBP",
        created_at=created_at,
        pricing_summary=SimpleNamespace(total_minor=2500),
    )


class StubAdminCustomerService:
    def __init__(
        self,
        *,
        customers: list[User] | None = None,
        detail: AdminCustomerDetail | None = None,
        cancel_error: Exception | None = None,
    ) -> None:
        self._customers = customers or []
        self._detail = detail
        self._cancel_error = cancel_error
        self.cancel_calls: list[dict] = []

    def list_customers(self, *, page: int, page_size: int, search: str | None = None):
        return self._customers, len(self._customers)

    def get_customer_detail(self, *, user_id: str) -> AdminCustomerDetail:
        if self._detail is None:
            raise CustomerNotFoundError
        return self._detail

    def cancel_subscription(self, *, user_id: str, reason: str, actor_user_id: str):
        self.cancel_calls.append({"user_id": user_id, "reason": reason, "actor_user_id": actor_user_id})
        if self._cancel_error is not None:
            raise self._cancel_error
        return self._detail.billing_overview.subscription if self._detail else None

    def list_audit_log(self, *, user_id: str) -> list[dict]:
        return [
            {
                "action": "subscription_canceled",
                "details": {"reason": "test"},
                "actor_user_id": "admin-1",
                "created_at": utc_now(),
            }
        ]


class AdminCustomersEndpointsTests(unittest.TestCase):
    def test_list_customers_returns_items(self) -> None:
        service = StubAdminCustomerService(customers=[make_customer()])

        response = list_customers(page=1, page_size=20, search=None, _=make_admin(), admin_customer_service=service)

        self.assertEqual(1, response.total)
        self.assertEqual("cust-1", response.items[0].id)

    def test_get_customer_returns_detail(self) -> None:
        detail = AdminCustomerDetail(
            user=make_customer(),
            billing_overview=make_billing_overview(is_premium=True),
            recent_grocery_orders=[make_fake_order(order_id="ord-1", created_at=utc_now())],
            recent_meal_orders=[],
        )
        service = StubAdminCustomerService(detail=detail)

        response = get_customer(user_id="cust-1", _=make_admin(), admin_customer_service=service)

        self.assertEqual("cust-1", response.id)
        self.assertTrue(response.subscription.is_premium)
        self.assertEqual(1, len(response.recent_orders))
        self.assertEqual("grocery", response.recent_orders[0].kind)

    def test_get_customer_maps_not_found_to_404(self) -> None:
        service = StubAdminCustomerService(detail=None)

        with self.assertRaises(HTTPException) as context:
            get_customer(user_id="missing", _=make_admin(), admin_customer_service=service)

        self.assertEqual(404, context.exception.status_code)

    def test_cancel_customer_subscription_passes_actor_and_reason(self) -> None:
        detail = AdminCustomerDetail(
            user=make_customer(),
            billing_overview=make_billing_overview(is_premium=False),
            recent_grocery_orders=[],
            recent_meal_orders=[],
        )
        service = StubAdminCustomerService(detail=detail)
        payload = CancelCustomerSubscriptionRequest(reason="Requested by customer support")

        response = cancel_customer_subscription(
            user_id="cust-1", payload=payload, current_admin=make_admin(), admin_customer_service=service
        )

        self.assertEqual(1, len(service.cancel_calls))
        self.assertEqual("admin-1", service.cancel_calls[0]["actor_user_id"])
        self.assertEqual("Requested by customer support", service.cancel_calls[0]["reason"])
        self.assertFalse(response.subscription.is_premium)

    def test_cancel_customer_subscription_maps_not_active_to_400(self) -> None:
        service = StubAdminCustomerService(cancel_error=CustomerSubscriptionNotActiveError())
        payload = CancelCustomerSubscriptionRequest(reason="test")

        with self.assertRaises(HTTPException) as context:
            cancel_customer_subscription(
                user_id="cust-1", payload=payload, current_admin=make_admin(), admin_customer_service=service
            )

        self.assertEqual(400, context.exception.status_code)

    def test_cancel_customer_subscription_maps_gateway_failure_to_502(self) -> None:
        service = StubAdminCustomerService(cancel_error=CustomerSubscriptionCancelFailedError())
        payload = CancelCustomerSubscriptionRequest(reason="test")

        with self.assertRaises(HTTPException) as context:
            cancel_customer_subscription(
                user_id="cust-1", payload=payload, current_admin=make_admin(), admin_customer_service=service
            )

        self.assertEqual(502, context.exception.status_code)

    def test_get_customer_audit_log_returns_entries(self) -> None:
        service = StubAdminCustomerService()

        response = get_customer_audit_log(user_id="cust-1", _=make_admin(), admin_customer_service=service)

        self.assertEqual(1, len(response.items))
        self.assertEqual("subscription_canceled", response.items[0].action)


if __name__ == "__main__":
    unittest.main()
