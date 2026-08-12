from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.address import UserDeliveryAddress
from app.models.billing import (
    CheckoutPaymentMethod,
    WalletAccount,
    WalletAccountStatus,
    WalletFundingMethod,
    WalletLedgerDirection,
    WalletLedgerEntry,
    WalletLedgerEntryType,
)
from app.models.cart import Cart, CartItem, CartItemPricingState, CartStatus
from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, CultureTag, GroceryProduct, NutritionSpec, NutrientType, NutrientUnit
from app.models.inventory import DeliveryFeeRule, InventoryAdjustment, InventoryAdjustmentType, InventoryItem
from app.models.order import Order, OrderPaymentSummary, OrderPricingSummary, OrderStatus, OrderStatusHistoryEntry, PaymentAttempt, PaymentAttemptStatus, Refund, RefundStatus
from app.models.user import User, UserType
from app.schemas.cart import CartItemUpsertRequest, CartSelectAddressRequest
from app.schemas.checkout import CheckoutConfirmRequest, CheckoutQuoteRequest
from app.schemas.order import RefundCreateRequest
from app.services.billing_service import BillingService
from app.services.cart_service import CartService, CartValidationError
from app.services.checkout_service import CheckoutError, CheckoutService
from app.services.delivery_window_service import DeliveryWindowService
from app.services.inventory_service import InventoryService
from app.services.refund_service import RefundService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeSubscriptionRepository:
    def ensure_default_for_user(self, *, user_id: str, currency: str = "GBP"):
        return SimpleNamespace(
            id=f"sub-{user_id}",
            user_id=user_id,
            plan_code=SimpleNamespace(value="free"),
            status=SimpleNamespace(value="inactive"),
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

    def upsert_subscription(self, **kwargs):
        return self.ensure_default_for_user(user_id=kwargs["user_id"], currency=kwargs["currency"])


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

    def create_entry(self, **kwargs) -> WalletLedgerEntry:
        entry = WalletLedgerEntry(
            id=f"entry-{len(self.items) + 1}",
            wallet_account_id=kwargs["wallet_account_id"],
            user_id=kwargs["user_id"],
            entry_type=kwargs["entry_type"],
            direction=kwargs["direction"],
            amount_minor=kwargs["amount_minor"],
            currency=kwargs["currency"],
            reference_type=kwargs["reference_type"],
            reference_id=kwargs["reference_id"],
            funding_method=kwargs["funding_method"],
            idempotency_key=kwargs["idempotency_key"],
            metadata=dict(kwargs["metadata"]),
            created_at=utc_now(),
        )
        self.items.append(entry)
        return entry

    def get_by_idempotency_key(self, *, idempotency_key: str) -> WalletLedgerEntry | None:
        return next((item for item in self.items if item.idempotency_key == idempotency_key), None)

    def get_by_reference_id(self, *, reference_type: str, reference_id: str) -> WalletLedgerEntry | None:
        return next(
            (
                item
                for item in self.items
                if item.reference_type == reference_type and item.reference_id == reference_id
            ),
            None,
        )

    def list_for_user(self, *, user_id: str, before: str | None, limit: int):
        items = [item for item in self.items if item.user_id == user_id]
        return items[:limit], None


class FakeGroceryRepository:
    def __init__(self, product: GroceryProduct) -> None:
        self.product = product

    def get_product(self, product_id: str) -> GroceryProduct | None:
        return self.product if product_id == self.product.id else None

    def get_product_by_id(self, product_id: str) -> GroceryProduct | None:
        return self.get_product(product_id)

    def get_category(self, category_id: str):
        return None


class FakeDiscountRepository:
    def get_discount(self, discount_id: str):
        return None


class FakeCartSubscriptionAccountRepository:
    def get_by_user_id(self, *, user_id: str):
        return None


class FakeInventoryRepository:
    def __init__(self, item: InventoryItem | None, fee_rule: DeliveryFeeRule) -> None:
        self.item = item
        self.adjustments: list[InventoryAdjustment] = []
        self.fee_rule = fee_rule

    def get_by_product_id(self, *, store_id: str, product_id: str) -> InventoryItem | None:
        if self.item is None:
            return None
        if store_id == self.item.store_id and product_id == self.item.product_id:
            return self.item
        return None

    def upsert_inventory_item(self, **kwargs) -> InventoryItem:
        created_at = self.item.created_at if self.item is not None else utc_now()
        item_id = self.item.id if self.item is not None else "inv-generated"
        self.item = InventoryItem(
            id=item_id,
            store_id=kwargs["store_id"],
            product_id=kwargs["product_id"],
            sku=kwargs["sku"],
            is_active=kwargs["is_active"],
            available_quantity=kwargs["available_quantity"],
            reserved_quantity=kwargs["reserved_quantity"],
            unit_label=kwargs["unit_label"],
            unit_weight_grams=kwargs["unit_weight_grams"],
            max_per_order=kwargs["max_per_order"],
            allow_substitutions=kwargs["allow_substitutions"],
            substitution_group=kwargs["substitution_group"],
            created_at=created_at,
            updated_at=utc_now(),
        )
        return self.item

    def decrement_available(self, *, store_id: str, product_id: str, quantity: int) -> InventoryItem:
        if self.item is None:
            raise ValueError("Inventory item not found.")
        self.item = replace(self.item, available_quantity=self.item.available_quantity - quantity, updated_at=utc_now())
        return self.item

    def increment_available(self, *, store_id: str, product_id: str, quantity: int) -> InventoryItem:
        if self.item is None:
            raise ValueError("Inventory item not found.")
        self.item = replace(self.item, available_quantity=self.item.available_quantity + quantity, updated_at=utc_now())
        return self.item

    def apply_adjustment(self, **kwargs) -> InventoryAdjustment:
        adjustment = InventoryAdjustment(
            id=f"adj-{len(self.adjustments) + 1}",
            inventory_item_id=kwargs["inventory_item_id"],
            product_id=kwargs["product_id"],
            store_id=kwargs["store_id"],
            adjustment_type=kwargs["adjustment_type"],
            delta_quantity=kwargs["delta_quantity"],
            reason=kwargs["reason"],
            actor_user_id=kwargs["actor_user_id"],
            reference_type=kwargs["reference_type"],
            reference_id=kwargs["reference_id"],
            metadata=dict(kwargs["metadata"]),
            created_at=utc_now(),
        )
        self.adjustments.append(adjustment)
        return adjustment

    def list_inventory(self, **kwargs):
        return [self.item], 1

    def list_adjustments(self, **kwargs):
        return self.adjustments, len(self.adjustments)

    def list_delivery_fee_rules(self, *, store_id: str, currency: str | None = None):
        if store_id == self.fee_rule.store_id and (currency is None or currency == self.fee_rule.currency):
            return [self.fee_rule]
        return []

    def create_delivery_fee_rule(self, **kwargs):
        return self.fee_rule

    def update_delivery_fee_rule(self, **kwargs):
        return self.fee_rule


class FakeAddressRepository:
    def __init__(self, address: UserDeliveryAddress) -> None:
        self.address = address

    def get_for_user(self, *, user_id: str, address_id: str):
        if self.address.user_id == user_id and self.address.id == address_id:
            return self.address
        return None


class FakeCartRepository:
    def __init__(self) -> None:
        self.cart: Cart | None = None

    def get_active_cart(self, *, user_id: str) -> Cart | None:
        if self.cart is not None and self.cart.user_id == user_id and self.cart.status == CartStatus.ACTIVE:
            return self.cart
        return None

    def ensure_active_cart(self, *, user_id: str, store_id: str, currency: str) -> Cart:
        if self.cart is not None and self.cart.user_id == user_id and self.cart.status == CartStatus.ACTIVE:
            return self.cart
        now = utc_now()
        self.cart = Cart(
            id="cart-1",
            user_id=user_id,
            store_id=store_id,
            currency=currency,
            status=CartStatus.ACTIVE,
            items=[],
            selected_address_id=None,
            pricing_snapshot={},
            last_priced_at=None,
            expires_at=None,
            created_at=now,
            updated_at=now,
        )
        return self.cart

    def save_cart(self, **kwargs) -> Cart:
        current = self.cart
        assert current is not None
        items = [
            CartItem(
                id=str(item["id"]),
                product_id=str(item["product_id"]),
                product_name=str(item["product_name"]),
                img_url=str(item["img_url"]),
                quantity=int(item["quantity"]),
                unit_label=str(item["unit_label"]),
                unit_weight_grams=int(item["unit_weight_grams"]),
                observed_unit_price_minor=int(item["observed_unit_price_minor"]),
                current_unit_price_minor=int(item["current_unit_price_minor"]),
                currency=str(item["currency"]),
                allow_substitutions=bool(item["allow_substitutions"]),
                substitution_note=str(item["substitution_note"]),
                pricing_state=CartItemPricingState(str(item["pricing_state"])),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
            for item in kwargs["items"]
        ]
        self.cart = Cart(
            id=current.id,
            user_id=current.user_id,
            store_id=current.store_id,
            currency=current.currency,
            status=kwargs["status"],
            items=items,
            selected_address_id=kwargs["selected_address_id"],
            pricing_snapshot=dict(kwargs["pricing_snapshot"]),
            last_priced_at=kwargs["last_priced_at"],
            expires_at=kwargs["expires_at"],
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        return self.cart

    def set_selected_address(self, *, cart_id: str, address_id: str | None) -> Cart:
        assert self.cart is not None
        self.cart = replace(self.cart, selected_address_id=address_id, updated_at=utc_now())
        return self.cart

    def mark_converted(self, *, cart_id: str) -> None:
        assert self.cart is not None
        self.cart = replace(self.cart, status=CartStatus.CONVERTED, updated_at=utc_now())


class FakeCheckoutQuoteRepository:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}

    def create_quote(self, **kwargs):
        document = {
            "_id": "quote-1",
            **kwargs,
            "expires_at": utc_now() + timedelta(seconds=kwargs["ttl_seconds"]),
            "created_at": utc_now(),
        }
        self.items["quote-1"] = document
        return document

    def get_quote_for_user(self, *, user_id: str, quote_id: str):
        document = self.items.get(quote_id)
        if document is not None and document["user_id"] == user_id:
            return document
        return None


class FakeOrderRepository:
    def __init__(self) -> None:
        self.items: dict[str, Order] = {}

    def create_order(self, **kwargs) -> Order:
        order = Order(
            id="order-1",
            order_number=kwargs["order_number"],
            user_id=kwargs["user_id"],
            store_id=kwargs["store_id"],
            status=kwargs["status"],
            currency=kwargs["currency"],
            items=[],
            pricing_summary=OrderPricingSummary(**kwargs["pricing_summary"]),
            address_snapshot=dict(kwargs["address_snapshot"]),
            substitution_policy=dict(kwargs["substitution_policy"]),
            payment_summary=OrderPaymentSummary(**kwargs["payment_summary"]),
            cancellation_window_expires_at=kwargs["cancellation_window_expires_at"],
            status_history=[
                OrderStatusHistoryEntry(
                    status=OrderStatus(entry["status"]),
                    note=entry["note"],
                    actor_user_id=entry["actor_user_id"],
                    created_at=entry["created_at"],
                )
                for entry in kwargs["status_history"]
            ],
            metadata=dict(kwargs["metadata"]),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        from app.models.order import OrderItemSnapshot
        order = replace(
            order,
            items=[OrderItemSnapshot(**item) for item in kwargs["items"]],
        )
        self.items[order.id] = order
        return order

    def get_order(self, *, order_id: str) -> Order | None:
        return self.items.get(order_id)

    def get_order_for_user(self, *, user_id: str, order_id: str) -> Order | None:
        item = self.items.get(order_id)
        return item if item is not None and item.user_id == user_id else None

    def update_status(self, *, order_id: str, status: OrderStatus, note: str, actor_user_id: str | None) -> Order | None:
        order = self.items.get(order_id)
        if order is None:
            return None
        updated = replace(
            order,
            status=status,
            status_history=[
                *order.status_history,
                OrderStatusHistoryEntry(status=status, note=note, actor_user_id=actor_user_id, created_at=utc_now()),
            ],
            updated_at=utc_now(),
        )
        self.items[order_id] = updated
        return updated

    def update_payment_summary(self, *, order_id: str, payment_summary: dict[str, object]):
        order = self.items.get(order_id)
        if order is None:
            return None
        updated = replace(order, payment_summary=OrderPaymentSummary(**payment_summary), updated_at=utc_now())
        self.items[order_id] = updated
        return updated

    def apply_refund_state(self, *, order_id: str, status: OrderStatus, metadata: dict[str, object]):
        order = self.items.get(order_id)
        if order is None:
            return None
        updated = replace(order, status=status, metadata=dict(metadata), updated_at=utc_now())
        self.items[order_id] = updated
        return updated

    def replace_items(self, *, order_id: str, items: list[dict[str, object]]):
        return self.items.get(order_id)

    def list_orders_for_user(self, *, user_id: str, before: str | None, limit: int):
        return [item for item in self.items.values() if item.user_id == user_id][:limit], None

    def list_orders_admin(self, *, status: str | None, before: str | None, limit: int):
        return list(self.items.values())[:limit], None


class FakePaymentAttemptRepository:
    def __init__(self) -> None:
        self.items: dict[str, PaymentAttempt] = {}

    def create_attempt(self, **kwargs) -> PaymentAttempt:
        item = PaymentAttempt(
            id="attempt-1",
            order_id=kwargs["order_id"],
            user_id=kwargs["user_id"],
            quote_id=kwargs["quote_id"],
            status=kwargs["status"],
            currency=kwargs["currency"],
            wallet_hold_amount_minor=kwargs["wallet_hold_amount_minor"],
            wallet_capture_amount_minor=kwargs["wallet_capture_amount_minor"],
            card_amount_minor=kwargs["card_amount_minor"],
            provider=kwargs["provider"],
            provider_payment_intent_id=kwargs["provider_payment_intent_id"],
            client_secret=kwargs["client_secret"],
            idempotency_key=kwargs["idempotency_key"],
            provider_payload=dict(kwargs["provider_payload"]),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_by_idempotency_key(self, *, idempotency_key: str):
        return next((item for item in self.items.values() if item.idempotency_key == idempotency_key), None)

    def get_by_provider_payment_intent_id(self, *, provider: str, provider_payment_intent_id: str):
        return next(
            (
                item
                for item in self.items.values()
                if item.provider == provider and item.provider_payment_intent_id == provider_payment_intent_id
            ),
            None,
        )

    def mark_status(self, *, attempt_id: str, status: PaymentAttemptStatus, provider_payload: dict[str, object] | None = None):
        current = self.items[attempt_id]
        updated = replace(current, status=status, provider_payload=dict(provider_payload or {}), updated_at=utc_now())
        self.items[attempt_id] = updated
        return updated


class FakeRefundRepository:
    def __init__(self) -> None:
        self.items: dict[str, Refund] = {}

    def create_refund(self, **kwargs) -> Refund:
        item = Refund(
            id="refund-1",
            order_id=kwargs["order_id"],
            user_id=kwargs["user_id"],
            status=kwargs["status"],
            currency=kwargs["currency"],
            refund_type=kwargs["refund_type"],
            reason=kwargs["reason"],
            wallet_refund_minor=kwargs["wallet_refund_minor"],
            card_refund_minor=kwargs["card_refund_minor"],
            line_items=list(kwargs["line_items"]),
            provider=kwargs["provider"],
            provider_refund_id=kwargs["provider_refund_id"],
            idempotency_key=kwargs["idempotency_key"],
            metadata=dict(kwargs["metadata"]),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_by_idempotency_key(self, *, idempotency_key: str):
        return next((item for item in self.items.values() if item.idempotency_key == idempotency_key), None)

    def list_for_order(self, *, order_id: str):
        return [item for item in self.items.values() if item.order_id == order_id]

    def list_for_user_order(self, *, user_id: str, order_id: str):
        return [item for item in self.items.values() if item.user_id == user_id and item.order_id == order_id]


class FakeStripeGateway:
    publishable_key = "pk_test_123"

    def create_grocery_payment_intent(self, **kwargs):
        return SimpleNamespace(
            payment_intent_id="pi_test_1",
            client_secret="pi_test_secret_1",
            amount_minor=kwargs["amount_minor"],
            currency=kwargs["currency"],
            status="requires_payment_method",
        )

    def create_meal_payment_intent(self, **kwargs):
        return SimpleNamespace(
            payment_intent_id="pi_test_meal_1",
            client_secret="pi_test_meal_secret_1",
            amount_minor=kwargs["amount_minor"],
            currency=kwargs["currency"],
            status="requires_payment_method",
        )

    def refund_payment_intent(self, **kwargs):
        return "re_test_1"

    def retrieve_payment_method(self, **kwargs):
        return SimpleNamespace(
            payment_method_id=kwargs["payment_method_id"],
            payment_method_type="card",
            brand="visa",
            last4="4242",
            exp_month=12,
            exp_year=2030,
        )


class GroceryShopServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = User(
            id="user-1",
            name="Ada",
            email="ada@example.com",
            password_hash="hash",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.product = GroceryProduct(
            id="prod-1",
            category_id="cat-1",
            img_url="https://example.com/apple.jpg",
            product="Apples",
            product_tags=["fruit"],
            culture_tags=[CultureTag.BRITISH],
            nutritional_specs=[
                NutritionSpec(nutrient_id=NutrientType.FIBER, amount=1.2, unit=NutrientUnit.GRAM)
            ],
            prices=[
                CountryPrice(
                    country_code=CountryCode.UNITED_KINGDOM,
                    currency_code=CurrencyCode.POUND_STERLING,
                    amount=3.50,
                    price_unit="1kg bag",
                    source="admin",
                    updated_at=utc_now(),
                    is_active=True,
                )
            ],
            description="Fresh apples",
            sort_order=0,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.inventory_item = InventoryItem(
            id="inv-1",
            store_id="main_store",
            product_id="prod-1",
            sku="APPLE-001",
            is_active=True,
            available_quantity=10,
            reserved_quantity=0,
            unit_label="1kg bag",
            unit_weight_grams=500,
            max_per_order=10,
            allow_substitutions=True,
            substitution_group="fruit",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.fee_rule = DeliveryFeeRule(
            id="fee-1",
            store_id="main_store",
            currency="GBP",
            min_weight_grams=0,
            max_weight_grams=10_000,
            fee_minor=100,
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.address = UserDeliveryAddress(
            id="addr-1",
            user_id="user-1",
            label="Home",
            recipient_name="Ada",
            phone_number="07123456789",
            line1="1 Test Street",
            line2="",
            city="London",
            state="London",
            postal_code="N1 1AA",
            country_code="GB",
            delivery_notes="Leave at door",
            is_default=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        self.subscription_repo = FakeSubscriptionRepository()
        self.wallet_repo = FakeWalletAccountRepository()
        self.ledger_repo = FakeWalletLedgerRepository()
        self.billing_service = BillingService(
            subscription_repository=self.subscription_repo,
            wallet_account_repository=self.wallet_repo,
            wallet_ledger_repository=self.ledger_repo,
        )
        self.grocery_repository = FakeGroceryRepository(self.product)
        self.inventory_repository = FakeInventoryRepository(self.inventory_item, self.fee_rule)
        self.address_repository = FakeAddressRepository(self.address)
        self.cart_repository = FakeCartRepository()
        self.quote_repository = FakeCheckoutQuoteRepository()
        self.order_repository = FakeOrderRepository()
        self.payment_attempt_repository = FakePaymentAttemptRepository()
        self.refund_repository = FakeRefundRepository()
        self.stripe_gateway = FakeStripeGateway()

        self.inventory_service = InventoryService(
            inventory_repository=self.inventory_repository,
            grocery_repository=self.grocery_repository,
            discount_repository=FakeDiscountRepository(),
            default_store_id="main_store",
        )
        self.cart_service = CartService(
            cart_repository=self.cart_repository,
            grocery_repository=self.grocery_repository,
            inventory_repository=self.inventory_repository,
            address_repository=self.address_repository,
            inventory_service=self.inventory_service,
            subscription_account_repository=FakeCartSubscriptionAccountRepository(),
            default_store_id="main_store",
            default_currency="GBP",
            free_delivery_subtotal_minor=2000,
            cart_ttl_seconds=3600,
            max_quantity_per_line=25,
        )
        self.checkout_service = CheckoutService(
            cart_service=self.cart_service,
            cart_repository=self.cart_repository,
            checkout_quote_repository=self.quote_repository,
            order_repository=self.order_repository,
            payment_attempt_repository=self.payment_attempt_repository,
            grocery_repository=self.grocery_repository,
            inventory_repository=self.inventory_repository,
            address_repository=self.address_repository,
            inventory_service=self.inventory_service,
            billing_service=self.billing_service,
            stripe_gateway=self.stripe_gateway,
            delivery_window_service=DeliveryWindowService(),
            default_store_id="main_store",
            default_currency="GBP",
            free_delivery_subtotal_minor=2000,
            delivery_timezone_name="Europe/London",
            quote_ttl_seconds=900,
            cancellation_window_minutes=20,
        )
        self.refund_service = RefundService(
            order_repository=self.order_repository,
            refund_repository=self.refund_repository,
            billing_service=self.billing_service,
            stripe_gateway=self.stripe_gateway,
        )

    def test_create_quote_supports_split_wallet_and_card(self) -> None:
        self.billing_service.confirm_wallet_topup_for_user_id(
            user_id=self.user.id,
            payload=SimpleNamespace(
                amount_minor=300,
                currency="GBP",
                funding_method=WalletFundingMethod.CARD,
                provider="stripe",
                provider_reference_id="topup_ref_12345678",
                idempotency_key="topup_ref_12345678",
                metadata={},
            ),
        )
        self.cart_service.upsert_item(
            current_user=self.user,
            payload=CartItemUpsertRequest(product_id="prod-1", quantity=2, allow_substitutions=True, substitution_note=""),
        )
        self.cart_service.select_address(
            current_user=self.user,
            payload=CartSelectAddressRequest(address_id="addr-1"),
        )

        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=CheckoutQuoteRequest(address_id="addr-1", currency="GBP"),
        )

        self.assertEqual(quote.route.value, "wallet_then_direct_pay")
        self.assertEqual(quote.total_minor, 800)
        self.assertEqual(quote.wallet_contribution_minor, 300)
        self.assertEqual(quote.card_contribution_minor, 500)
        self.assertEqual(quote.selected_delivery_window.label, "Today, 2:00 PM - 4:00 PM")
        self.assertGreaterEqual(len(quote.available_delivery_windows), 3)
        self.assertEqual(quote.free_delivery_threshold_minor, 2000)
        self.assertEqual(quote.free_delivery_remaining_minor, 1300)
        self.assertFalse(quote.free_delivery_unlocked)

    def test_cart_upsert_creates_default_inventory_for_seeded_product(self) -> None:
        self.inventory_repository.item = None

        cart = self.cart_service.upsert_item(
            current_user=self.user,
            payload=CartItemUpsertRequest(product_id="prod-1", quantity=2, allow_substitutions=True, substitution_note=""),
        )

        self.assertEqual(len(cart.items), 1)
        self.assertIsNotNone(self.inventory_repository.item)
        self.assertEqual(self.inventory_repository.item.product_id, "prod-1")
        self.assertEqual(self.inventory_repository.item.sku, "PROD-1")
        self.assertEqual(self.inventory_repository.item.available_quantity, 100)
        self.assertEqual(self.inventory_repository.item.max_per_order, 25)
        self.assertEqual(cart.summary.free_delivery_threshold_minor, 2000)

    def test_cart_upsert_keeps_inactive_inventory_unpurchasable(self) -> None:
        self.inventory_repository.item = replace(self.inventory_repository.item, is_active=False)

        with self.assertRaises(CartValidationError):
            self.cart_service.upsert_item(
                current_user=self.user,
                payload=CartItemUpsertRequest(product_id="prod-1", quantity=1, allow_substitutions=True, substitution_note=""),
            )

    def test_wallet_only_checkout_confirms_order_and_decrements_inventory(self) -> None:
        self.billing_service.confirm_wallet_topup_for_user_id(
            user_id=self.user.id,
            payload=SimpleNamespace(
                amount_minor=2000,
                currency="GBP",
                funding_method=WalletFundingMethod.CARD,
                provider="stripe",
                provider_reference_id="topup_ref_wallet_only",
                idempotency_key="topup_ref_wallet_only",
                metadata={},
            ),
        )
        self.cart_service.upsert_item(
            current_user=self.user,
            payload=CartItemUpsertRequest(product_id="prod-1", quantity=2, allow_substitutions=True, substitution_note=""),
        )
        self.cart_service.select_address(
            current_user=self.user,
            payload=CartSelectAddressRequest(address_id="addr-1"),
        )
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=CheckoutQuoteRequest(address_id="addr-1", currency="GBP"),
        )

        result = self.checkout_service.confirm_checkout(
            current_user=self.user,
            payload=CheckoutConfirmRequest(quote_id=quote.quote_id, idempotency_key="checkout-wallet-only-1234"),
        )

        self.assertFalse(result.requires_payment_action)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(self.inventory_repository.item.available_quantity, 8)
        self.assertEqual(self.cart_repository.cart.status, CartStatus.CONVERTED)
        self.assertEqual(self.order_repository.get_order(order_id="order-1").status, OrderStatus.CONFIRMED)

    def test_card_payment_method_forces_full_card_checkout(self) -> None:
        self.billing_service.confirm_wallet_topup_for_user_id(
            user_id=self.user.id,
            payload=SimpleNamespace(
                amount_minor=2000,
                currency="GBP",
                funding_method=WalletFundingMethod.CARD,
                provider="stripe",
                provider_reference_id="topup_ref_force_card",
                idempotency_key="topup_ref_force_card",
                metadata={},
            ),
        )
        self.cart_service.upsert_item(
            current_user=self.user,
            payload=CartItemUpsertRequest(product_id="prod-1", quantity=2, allow_substitutions=True, substitution_note=""),
        )
        self.cart_service.select_address(
            current_user=self.user,
            payload=CartSelectAddressRequest(address_id="addr-1"),
        )
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=CheckoutQuoteRequest(address_id="addr-1", currency="GBP"),
        )

        result = self.checkout_service.confirm_checkout(
            current_user=self.user,
            payload=CheckoutConfirmRequest(
                quote_id=quote.quote_id,
                idempotency_key="checkout-force-card-1234",
                payment_method=CheckoutPaymentMethod.CARD,
            ),
        )

        order = self.order_repository.get_order(order_id=result.order_id)
        self.assertIsNotNone(order)
        self.assertTrue(result.requires_payment_action)
        self.assertEqual(order.payment_summary.wallet_amount_minor, 0)
        self.assertEqual(order.payment_summary.card_amount_minor, quote.total_minor)

    def test_wallet_payment_method_requires_full_wallet_balance(self) -> None:
        self.billing_service.confirm_wallet_topup_for_user_id(
            user_id=self.user.id,
            payload=SimpleNamespace(
                amount_minor=300,
                currency="GBP",
                funding_method=WalletFundingMethod.CARD,
                provider="stripe",
                provider_reference_id="topup_ref_partial_wallet",
                idempotency_key="topup_ref_partial_wallet",
                metadata={},
            ),
        )
        self.cart_service.upsert_item(
            current_user=self.user,
            payload=CartItemUpsertRequest(product_id="prod-1", quantity=2, allow_substitutions=True, substitution_note=""),
        )
        self.cart_service.select_address(
            current_user=self.user,
            payload=CartSelectAddressRequest(address_id="addr-1"),
        )
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=CheckoutQuoteRequest(address_id="addr-1", currency="GBP"),
        )

        with self.assertRaises(CheckoutError):
            self.checkout_service.confirm_checkout(
                current_user=self.user,
                payload=CheckoutConfirmRequest(
                    quote_id=quote.quote_id,
                    idempotency_key="checkout-wallet-insufficient-1234",
                    payment_method=CheckoutPaymentMethod.WALLET,
                ),
            )

    def test_refund_splits_wallet_and_card_components(self) -> None:
        order = self.order_repository.create_order(
            order_number="GSO-TEST",
            user_id=self.user.id,
            store_id="main_store",
            status=OrderStatus.CONFIRMED,
            currency="GBP",
            items=[
                {
                    "id": "item-1",
                    "product_id": "prod-1",
                    "product_name": "Apples",
                    "img_url": "https://example.com/apple.jpg",
                    "quantity": 2,
                    "unit_label": "1kg bag",
                    "unit_weight_grams": 500,
                    "unit_price_minor": 350,
                    "line_total_minor": 700,
                    "currency": "GBP",
                    "allow_substitutions": True,
                    "substitution_resolution": "none",
                    "substituted_product_id": None,
                }
            ],
            pricing_summary={
                "currency": "GBP",
                "subtotal_minor": 700,
                "delivery_fee_minor": 100,
                "service_fee_minor": 0,
                "total_minor": 800,
                "total_weight_grams": 1000,
            },
            address_snapshot={"id": "addr-1"},
            substitution_policy={"allow_substitutions": True},
            payment_summary={
                "currency": "GBP",
                "wallet_amount_minor": 200,
                "card_amount_minor": 600,
                "total_paid_minor": 800,
                "provider": "stripe",
                "provider_payment_intent_id": "pi_123",
            },
            cancellation_window_expires_at=utc_now() + timedelta(minutes=20),
            status_history=[],
            metadata={},
        )

        refund = self.refund_service.create_admin_refund(
            order_id=order.id,
            payload=RefundCreateRequest(reason="Customer request", amount_minor=400, line_items=[], idempotency_key="refund-1234"),
        )

        self.assertEqual(refund.wallet_refund_minor, 100)
        self.assertEqual(refund.card_refund_minor, 300)
        self.assertEqual(self.order_repository.get_order(order_id=order.id).status, OrderStatus.PARTIALLY_REFUNDED)

    def test_cart_unlocks_free_delivery_when_subtotal_reaches_threshold(self) -> None:
        cart = self.cart_service.upsert_item(
            current_user=self.user,
            payload=CartItemUpsertRequest(product_id="prod-1", quantity=6, allow_substitutions=True, substitution_note=""),
        )

        self.assertEqual(cart.summary.subtotal_minor, 2100)
        self.assertEqual(cart.summary.delivery_fee_minor, 0)
        self.assertEqual(cart.summary.total_minor, 2100)
        self.assertTrue(cart.summary.free_delivery_unlocked)
        self.assertEqual(cart.summary.free_delivery_remaining_minor, 0)

    def test_list_refunds_is_scoped_to_the_current_user(self) -> None:
        self.refund_repository.items["refund-1"] = Refund(
            id="refund-1",
            order_id="order-1",
            user_id=self.user.id,
            status=RefundStatus.COMPLETED,
            currency="GBP",
            refund_type="full",
            reason="visible",
            wallet_refund_minor=0,
            card_refund_minor=100,
            line_items=[],
            provider="stripe",
            provider_refund_id="re_1",
            idempotency_key="refund-visible",
            metadata={},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.refund_repository.items["refund-2"] = Refund(
            id="refund-2",
            order_id="order-1",
            user_id="user-2",
            status=RefundStatus.COMPLETED,
            currency="GBP",
            refund_type="full",
            reason="hidden",
            wallet_refund_minor=0,
            card_refund_minor=100,
            line_items=[],
            provider="stripe",
            provider_refund_id="re_2",
            idempotency_key="refund-hidden",
            metadata={},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.order_repository.create_order(
            order_number="GSO-REFUNDS",
            user_id=self.user.id,
            store_id="main_store",
            status=OrderStatus.CONFIRMED,
            currency="GBP",
            items=[],
            pricing_summary={
                "currency": "GBP",
                "subtotal_minor": 0,
                "delivery_fee_minor": 0,
                "service_fee_minor": 0,
                "total_minor": 0,
                "total_weight_grams": 0,
            },
            address_snapshot={"id": "addr-1"},
            substitution_policy={"allow_substitutions": True},
            payment_summary={
                "currency": "GBP",
                "wallet_amount_minor": 0,
                "card_amount_minor": 0,
                "total_paid_minor": 0,
                "provider": "stripe",
                "provider_payment_intent_id": None,
            },
            cancellation_window_expires_at=utc_now(),
            status_history=[],
            metadata={},
        )

        response = self.refund_service.list_refunds(current_user=self.user, order_id="order-1")

        self.assertEqual([item.id for item in response.items], ["refund-1"])


if __name__ == "__main__":
    unittest.main()
