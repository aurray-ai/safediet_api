from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.billing import SubscriptionPlanCode, SubscriptionStatus
from app.models.meal_order import MealOrder
from app.models.order import Order
from app.models.user import User, UserType
from app.repositories.admin_customer_audit_repository import AdminCustomerAuditRepository
from app.repositories.meal_order_repository import MealOrderRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.subscription_account_repository import SubscriptionAccountRepository
from app.repositories.user_repository import UserRepository
from app.schemas.billing import BillingOverviewResponse, SubscriptionSnapshotResponse
from app.services.billing_service import BillingService, SubscriptionSyncInput
from app.services.stripe_billing_gateway import StripeBillingGateway

logger = logging.getLogger(__name__)


class CustomerNotFoundError(Exception):
    pass


class CustomerSubscriptionNotActiveError(Exception):
    pass


class CustomerSubscriptionCancelFailedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AdminCustomerDetail:
    user: User
    billing_overview: BillingOverviewResponse
    recent_grocery_orders: list[Order]
    recent_meal_orders: list[MealOrder]


@dataclass(frozen=True, slots=True)
class AdminCustomerService:
    user_repository: UserRepository
    subscription_repository: SubscriptionAccountRepository
    order_repository: OrderRepository
    meal_order_repository: MealOrderRepository
    billing_service: BillingService
    stripe_gateway: StripeBillingGateway
    admin_customer_audit_repository: AdminCustomerAuditRepository

    def list_customers(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        return self.user_repository.list_users(
            page=page,
            page_size=page_size,
            search=search,
            user_type=UserType.CUSTOMER,
        )

    def get_customer_detail(self, *, user_id: str) -> AdminCustomerDetail:
        user = self.user_repository.find_by_id(user_id)
        if user is None:
            raise CustomerNotFoundError

        billing_overview = self.billing_service.get_overview(current_user=user)
        recent_grocery_orders, _ = self.order_repository.list_orders_for_user(
            user_id=user_id, before=None, limit=5
        )
        recent_meal_orders, _ = self.meal_order_repository.list_orders_for_user(
            user_id=user_id, before=None, limit=5
        )

        return AdminCustomerDetail(
            user=user,
            billing_overview=billing_overview,
            recent_grocery_orders=recent_grocery_orders,
            recent_meal_orders=recent_meal_orders,
        )

    def cancel_subscription(
        self,
        *,
        user_id: str,
        reason: str,
        actor_user_id: str,
    ) -> SubscriptionSnapshotResponse:
        user = self.user_repository.find_by_id(user_id)
        if user is None:
            raise CustomerNotFoundError

        subscription = self.subscription_repository.get_by_user_id(user_id=user_id)
        if subscription is None or not subscription.is_premium:
            raise CustomerSubscriptionNotActiveError

        if subscription.provider == "stripe":
            stripe_subscription_id = str(subscription.provider_payload.get("id") or "").strip()
            if stripe_subscription_id:
                try:
                    self.stripe_gateway.cancel_subscription(subscription_id=stripe_subscription_id)
                except Exception as exc:
                    logger.exception(
                        "admin_customer.cancel_subscription.stripe_failed user_id=%s", user_id
                    )
                    raise CustomerSubscriptionCancelFailedError from exc

        response = self.billing_service.sync_subscription_for_user_id(
            user_id=user_id,
            payload=SubscriptionSyncInput(
                plan_code=SubscriptionPlanCode.FREE,
                status=SubscriptionStatus.CANCELED,
                provider=subscription.provider,
                price_minor=0,
                currency=subscription.currency,
                is_premium=False,
                started_at=subscription.started_at,
                expires_at=datetime.now(timezone.utc),
                renewal_at=None,
                original_transaction_id=subscription.original_transaction_id,
                latest_transaction_id=subscription.latest_transaction_id,
                provider_payload=subscription.provider_payload,
            ),
        )

        self.admin_customer_audit_repository.append(
            user_id=user_id,
            action="subscription_canceled",
            details={"reason": reason, "provider": subscription.provider},
            actor_user_id=actor_user_id,
        )

        return response

    def list_audit_log(self, *, user_id: str) -> list[dict]:
        return self.admin_customer_audit_repository.list_for_user(user_id=user_id)
