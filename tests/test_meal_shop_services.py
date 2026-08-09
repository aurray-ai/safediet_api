from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from app.models.address import UserDeliveryAddress
from app.models.billing import CheckoutPaymentMethod
from app.models.cart import CartItemPricingState, CartStatus
from app.models.grocery import CountryCode, CurrencyCode
from app.models.meal import (
    Meal,
    MealDifficulty,
    MealHighlightTag,
    MealNutritionSummary,
    MealSellingPrice,
    MealType,
)
from app.models.meal_cart import MealCart
from app.models.meal_order import MealDeliveryType, MealOrder
from app.models.order import OrderStatus, PaymentAttemptStatus
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.repositories.meal_favorite_repository import MealFavoriteRepository
from app.schemas.meal_cart import (
    MealCartItemQuantityUpdateRequest,
    MealCartItemUpsertRequest,
    MealCartSelectAddressRequest,
)
from app.schemas.meal_checkout import MealCheckoutConfirmRequest, MealCheckoutQuoteRequest
from app.schemas.meal_plan_checkout import MealPlanCheckoutConfirmRequest, MealPlanCheckoutQuoteRequest
from app.services.billing_service import BillingService
from app.services.delivery_window_service import DeliveryWindowService
from app.services.meal_cart_service import MealCartItemNotFoundError, MealCartService
from app.services.meal_checkout_service import MealCheckoutError, MealCheckoutService
from app.services.meal_order_service import MealOrderService, MealOrderTransitionError
from app.services.meal_plan_checkout_service import MealPlanCheckoutError, MealPlanCheckoutService
from app.services.checkout_service import CheckoutService
from app.services.meal_service import MealNotFoundError, MealService

from tests.test_grocery_shop_services import (
    FakeAddressRepository,
    FakeCheckoutQuoteRepository,
    FakePaymentAttemptRepository,
    FakeStripeGateway,
    FakeSubscriptionRepository,
    FakeWalletAccountRepository,
    FakeWalletLedgerRepository,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_meal(
    *,
    meal_id: str = "meal-1",
    price_amount_minor: int = 650,
    currency: CurrencyCode = CurrencyCode.POUND_STERLING,
) -> Meal:
    return Meal(
        id=meal_id,
        name="Jollof Rice with Chicken",
        hero_image_url="https://example.com/jollof.jpg",
        image_urls=["https://example.com/jollof.jpg"],
        description="Smoky Nigerian jollof rice.",
        meal_type=MealType.DINNER,
        category_ids=["cat-nigerian"],
        culture_tags=["nigerian"],
        diet_rules_supported=[],
        allergy_exclusions=[],
        prep_time_minutes=15,
        cook_time_minutes=35,
        difficulty=MealDifficulty.EASY,
        servings=2,
        nutritional_specs=[],
        nutrition_summary=MealNutritionSummary(calories=520, protein_g=28, carbs_g=60, fat_g=18),
        estimated_costs=[],
        recipe_steps=[],
        recipe_step_items=[],
        ingredient_items=[],
        linked_product_ids=[],
        chef_available=False,
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
        selling_prices=[
            MealSellingPrice(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=currency,
                amount_minor=price_amount_minor,
            )
        ],
        rating_average=4.8,
        rating_count=124,
        highlight_tags=[MealHighlightTag.HIGH_PROTEIN, MealHighlightTag.FAMILY_FRIENDLY],
    )


class FakeMealRepository:
    def __init__(self, *meals: Meal) -> None:
        self.meals: dict[str, Meal] = {meal.id: meal for meal in meals}

    def get_meal(self, meal_id: str):
        meal = self.meals.get(meal_id)
        return meal if meal is not None and meal.is_active else None

    def get_category(self, category_id: str):
        return None


class FakeMealFavoriteRepository:
    def __init__(self) -> None:
        self._favorites: set[tuple[str, str]] = set()

    def add(self, *, user_id: str, meal_id: str):
        self._favorites.add((user_id, meal_id))

    def remove(self, *, user_id: str, meal_id: str) -> None:
        self._favorites.discard((user_id, meal_id))

    def is_favorited(self, *, user_id: str, meal_id: str) -> bool:
        return (user_id, meal_id) in self._favorites

    def list_favorited_meal_ids(self, *, user_id: str) -> set[str]:
        return {meal_id for (uid, meal_id) in self._favorites if uid == user_id}


class FakeMealCartRepository:
    def __init__(self) -> None:
        self.cart: MealCart | None = None

    def get_active_cart(self, *, user_id: str) -> MealCart | None:
        if self.cart is not None and self.cart.user_id == user_id and self.cart.status == CartStatus.ACTIVE:
            return self.cart
        return None

    def ensure_active_cart(self, *, user_id: str, currency: str) -> MealCart:
        if self.cart is not None and self.cart.user_id == user_id and self.cart.status == CartStatus.ACTIVE:
            return self.cart
        now = utc_now()
        self.cart = MealCart(
            id="meal-cart-1",
            user_id=user_id,
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

    def save_cart(self, **kwargs) -> MealCart:
        from app.models.meal_cart import MealCartItem

        current = self.cart
        assert current is not None
        items = [
            MealCartItem(
                id=str(item["id"]),
                meal_id=str(item["meal_id"]),
                meal_name=str(item["meal_name"]),
                img_url=str(item["img_url"]),
                servings=int(item["servings"]),
                observed_unit_price_minor=int(item["observed_unit_price_minor"]),
                current_unit_price_minor=int(item["current_unit_price_minor"]),
                currency=str(item["currency"]),
                pricing_state=CartItemPricingState(str(item["pricing_state"])),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
            for item in kwargs["items"]
        ]
        self.cart = MealCart(
            id=current.id,
            user_id=current.user_id,
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

    def set_selected_address(self, *, cart_id: str, address_id: str | None) -> MealCart:
        assert self.cart is not None
        self.cart = replace(self.cart, selected_address_id=address_id, updated_at=utc_now())
        return self.cart

    def mark_converted(self, *, cart_id: str) -> None:
        assert self.cart is not None
        self.cart = replace(self.cart, status=CartStatus.CONVERTED, updated_at=utc_now())


class FakeMealOrderRepository:
    def __init__(self) -> None:
        self.items: dict[str, MealOrder] = {}
        self._counter = 0

    def create_order(self, **kwargs) -> MealOrder:
        from app.models.meal_order import (
            MealOrderItemSnapshot,
            MealOrderPaymentSummary,
            MealOrderPricingSummary,
            MealOrderStatusHistoryEntry,
        )

        self._counter += 1
        order_id = f"meal-order-{self._counter}"
        now = utc_now()
        order = MealOrder(
            id=order_id,
            order_number=kwargs["order_number"],
            user_id=kwargs["user_id"],
            status=kwargs["status"],
            currency=kwargs["currency"],
            delivery_type=kwargs["delivery_type"],
            items=[
                MealOrderItemSnapshot(
                    id=str(item["id"]),
                    meal_id=str(item["meal_id"]),
                    meal_name=str(item["meal_name"]),
                    img_url=str(item["img_url"]),
                    servings=int(item["servings"]),
                    unit_price_minor=int(item["unit_price_minor"]),
                    line_total_minor=int(item["line_total_minor"]),
                    currency=str(item["currency"]),
                    delivery_date=(
                        date.fromisoformat(str(item["delivery_date"]))
                        if item.get("delivery_date")
                        else None
                    ),
                    slot=str(item.get("slot") or ""),
                )
                for item in kwargs["items"]
            ],
            pricing_summary=MealOrderPricingSummary(**kwargs["pricing_summary"]),
            address_snapshot=dict(kwargs["address_snapshot"]),
            payment_summary=MealOrderPaymentSummary(**kwargs["payment_summary"]),
            cancellation_window_expires_at=kwargs["cancellation_window_expires_at"],
            status_history=[
                MealOrderStatusHistoryEntry(
                    status=OrderStatus(entry["status"]),
                    note=entry["note"],
                    actor_user_id=entry["actor_user_id"],
                    created_at=entry["created_at"],
                )
                for entry in kwargs["status_history"]
            ],
            metadata=dict(kwargs["metadata"]),
            created_at=now,
            updated_at=now,
        )
        self.items[order_id] = order
        return order

    def get_order(self, *, order_id: str) -> MealOrder | None:
        return self.items.get(order_id)

    def get_order_for_user(self, *, user_id: str, order_id: str) -> MealOrder | None:
        order = self.items.get(order_id)
        return order if order is not None and order.user_id == user_id else None

    def list_orders_for_user(self, *, user_id: str, before, limit):
        items = [order for order in self.items.values() if order.user_id == user_id]
        return items[:limit], None

    def update_status(self, *, order_id: str, status, note: str, actor_user_id):
        from app.models.meal_order import MealOrderStatusHistoryEntry

        current = self.items[order_id]
        history_entry = MealOrderStatusHistoryEntry(
            status=status, note=note, actor_user_id=actor_user_id, created_at=utc_now()
        )
        updated = replace(
            current,
            status=status,
            status_history=[*current.status_history, history_entry],
            updated_at=utc_now(),
        )
        self.items[order_id] = updated
        return updated

    def update_payment_summary(self, *, order_id: str, payment_summary: dict):
        from app.models.meal_order import MealOrderPaymentSummary

        current = self.items[order_id]
        updated = replace(
            current,
            payment_summary=MealOrderPaymentSummary(**payment_summary),
            updated_at=utc_now(),
        )
        self.items[order_id] = updated
        return updated

    def update_metadata(self, *, order_id: str, metadata: dict):
        current = self.items[order_id]
        updated = replace(current, metadata=dict(metadata), updated_at=utc_now())
        self.items[order_id] = updated
        return updated


class MealCartServiceTests(unittest.TestCase):
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
        self.meal = make_meal()
        self.meal_repository = FakeMealRepository(self.meal)
        self.meal_cart_repository = FakeMealCartRepository()
        self.address = UserDeliveryAddress(
            id="addr-1",
            user_id="user-1",
            label="Home",
            recipient_name="Ada",
            phone_number="+441234567890",
            line1="1 Test Street",
            line2="",
            city="London",
            state="",
            postal_code="E1 6AN",
            country="GB",
            delivery_notes="",
            is_default=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.address_repository = FakeAddressRepository(self.address)
        self.service = MealCartService(
            meal_cart_repository=self.meal_cart_repository,
            meal_repository=self.meal_repository,
            address_repository=self.address_repository,
            default_currency="GBP",
            cart_ttl_seconds=3600,
            max_servings_per_line=20,
        )

    def test_upsert_item_adds_meal_with_resolved_price(self) -> None:
        response = self.service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=2),
        )
        self.assertEqual(len(response.items), 1)
        item = response.items[0]
        self.assertEqual(item.servings, 2)
        self.assertEqual(item.current_unit_price_minor, 650)
        self.assertEqual(response.summary.subtotal_minor, 1300)
        self.assertEqual(response.summary.total_minor, 1300)
        self.assertEqual(response.summary.delivery_fee_minor, 0)

    def test_update_item_quantity_updates_subtotal(self) -> None:
        self.service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=1),
        )
        item_id = self.meal_cart_repository.cart.items[0].id
        response = self.service.update_item_quantity(
            current_user=self.user,
            item_id=item_id,
            payload=MealCartItemQuantityUpdateRequest(servings=3),
        )
        self.assertEqual(response.items[0].servings, 3)
        self.assertEqual(response.summary.subtotal_minor, 1950)

    def test_update_item_quantity_missing_item_raises(self) -> None:
        self.service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=1),
        )
        with self.assertRaises(MealCartItemNotFoundError):
            self.service.update_item_quantity(
                current_user=self.user,
                item_id="does-not-exist",
                payload=MealCartItemQuantityUpdateRequest(servings=2),
            )

    def test_reprice_marks_deleted_meal_as_unavailable(self) -> None:
        self.service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=1),
        )
        del self.meal_repository.meals["meal-1"]
        validation = self.service.validate_cart(current_user=self.user)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.issues[0].code, "unavailable")
        self.assertEqual(validation.cart.summary.subtotal_minor, 0)

    def test_reprice_flags_price_change(self) -> None:
        self.service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=1),
        )
        self.meal_repository.meals["meal-1"] = make_meal(price_amount_minor=800)
        validation = self.service.validate_cart(current_user=self.user)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.issues[0].code, "price_changed")
        self.assertEqual(validation.cart.summary.subtotal_minor, 800)


class MealCheckoutServiceTests(unittest.TestCase):
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
        self.meal = make_meal()
        self.meal_repository = FakeMealRepository(self.meal)
        self.meal_cart_repository = FakeMealCartRepository()
        self.address = UserDeliveryAddress(
            id="addr-1",
            user_id="user-1",
            label="Home",
            recipient_name="Ada",
            phone_number="+441234567890",
            line1="1 Test Street",
            line2="",
            city="London",
            state="",
            postal_code="E1 6AN",
            country="GB",
            delivery_notes="",
            is_default=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.address_repository = FakeAddressRepository(self.address)
        self.meal_cart_service = MealCartService(
            meal_cart_repository=self.meal_cart_repository,
            meal_repository=self.meal_repository,
            address_repository=self.address_repository,
            default_currency="GBP",
            cart_ttl_seconds=3600,
            max_servings_per_line=20,
        )
        self.meal_cart_service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=2),
        )
        self.meal_cart_service.select_address(
            current_user=self.user,
            payload=MealCartSelectAddressRequest(address_id="addr-1"),
        )
        self.checkout_quote_repository = FakeCheckoutQuoteRepository()
        self.meal_order_repository = FakeMealOrderRepository()
        self.payment_attempt_repository = FakePaymentAttemptRepository()
        self.subscription_repo = FakeSubscriptionRepository()
        self.wallet_repo = FakeWalletAccountRepository()
        self.ledger_repo = FakeWalletLedgerRepository()
        self.billing_service = BillingService(
            subscription_repository=self.subscription_repo,
            wallet_account_repository=self.wallet_repo,
            wallet_ledger_repository=self.ledger_repo,
        )
        self.stripe_gateway = FakeStripeGateway()
        self.delivery_window_service = DeliveryWindowService()
        self.checkout_service = MealCheckoutService(
            meal_cart_service=self.meal_cart_service,
            meal_cart_repository=self.meal_cart_repository,
            checkout_quote_repository=self.checkout_quote_repository,
            meal_order_repository=self.meal_order_repository,
            payment_attempt_repository=self.payment_attempt_repository,
            address_repository=self.address_repository,
            billing_service=self.billing_service,
            stripe_gateway=self.stripe_gateway,
            delivery_window_service=self.delivery_window_service,
            default_currency="GBP",
            delivery_timezone_name="Europe/London",
            express_delivery_fee_minor=300,
            quote_ttl_seconds=900,
            cancellation_window_minutes=20,
        )

    def test_quote_standard_delivery_is_free(self) -> None:
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=MealCheckoutQuoteRequest(address_id="addr-1"),
        )
        self.assertEqual(quote.delivery_fee_minor, 0)
        self.assertEqual(quote.subtotal_minor, 1300)
        self.assertEqual(quote.total_minor, 1300)
        self.assertEqual(len(quote.available_delivery_windows), 4)

    def test_quote_express_delivery_adds_fee(self) -> None:
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=MealCheckoutQuoteRequest(address_id="addr-1", delivery_type=MealDeliveryType.EXPRESS),
        )
        self.assertEqual(quote.delivery_fee_minor, 300)
        self.assertEqual(quote.total_minor, 1600)

    def test_quote_requires_address(self) -> None:
        empty_cart_repository = FakeMealCartRepository()
        cart_service = MealCartService(
            meal_cart_repository=empty_cart_repository,
            meal_repository=self.meal_repository,
            address_repository=self.address_repository,
            default_currency="GBP",
            cart_ttl_seconds=3600,
            max_servings_per_line=20,
        )
        cart_service.upsert_item(
            current_user=self.user,
            payload=MealCartItemUpsertRequest(meal_id="meal-1", servings=1),
        )
        checkout_service = MealCheckoutService(
            meal_cart_service=cart_service,
            meal_cart_repository=empty_cart_repository,
            checkout_quote_repository=self.checkout_quote_repository,
            meal_order_repository=self.meal_order_repository,
            payment_attempt_repository=self.payment_attempt_repository,
            address_repository=self.address_repository,
            billing_service=self.billing_service,
            stripe_gateway=self.stripe_gateway,
            delivery_window_service=self.delivery_window_service,
            default_currency="GBP",
            delivery_timezone_name="Europe/London",
            express_delivery_fee_minor=300,
            quote_ttl_seconds=900,
            cancellation_window_minutes=20,
        )
        with self.assertRaises(MealCheckoutError):
            checkout_service.create_quote(current_user=self.user, payload=MealCheckoutQuoteRequest())

    def test_confirm_wallet_only_checkout_confirms_order(self) -> None:
        self.wallet_repo.ensure_default_for_user(user_id=self.user.id, currency="GBP")
        self.wallet_repo.apply_balance_delta(wallet_account_id=f"wallet-{self.user.id}", available_delta_minor=5000)
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=MealCheckoutQuoteRequest(address_id="addr-1"),
        )
        confirm = self.checkout_service.confirm_checkout(
            current_user=self.user,
            payload=MealCheckoutConfirmRequest(
                quote_id=quote.quote_id,
                idempotency_key="idem-key-12345678",
                payment_method=CheckoutPaymentMethod.WALLET,
            ),
        )
        self.assertFalse(confirm.requires_payment_action)
        self.assertEqual(confirm.status, OrderStatus.CONFIRMED.value)
        order = self.meal_order_repository.get_order(order_id=confirm.order_id)
        self.assertIsNotNone(order)
        self.assertEqual(order.items[0].meal_id, "meal-1")
        self.assertEqual(order.pricing_summary.total_minor, 1300)

    def test_confirm_card_checkout_requires_payment_action_then_webhook_confirms(self) -> None:
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=MealCheckoutQuoteRequest(address_id="addr-1"),
        )
        confirm = self.checkout_service.confirm_checkout(
            current_user=self.user,
            payload=MealCheckoutConfirmRequest(
                quote_id=quote.quote_id,
                idempotency_key="idem-key-abcdefgh",
                payment_method=CheckoutPaymentMethod.CARD,
            ),
        )
        self.assertTrue(confirm.requires_payment_action)
        self.assertEqual(confirm.status, OrderStatus.PAYMENT_PROCESSING.value)

        self.checkout_service.handle_payment_intent_succeeded(
            event_object={
                "id": confirm.payment_action.payment_intent_id,
                "metadata": {"purpose": "meal_order"},
            }
        )
        order = self.meal_order_repository.get_order(order_id=confirm.order_id)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)

    def test_grocery_purpose_webhook_is_ignored_by_meal_checkout_service(self) -> None:
        quote = self.checkout_service.create_quote(
            current_user=self.user,
            payload=MealCheckoutQuoteRequest(address_id="addr-1"),
        )
        confirm = self.checkout_service.confirm_checkout(
            current_user=self.user,
            payload=MealCheckoutConfirmRequest(
                quote_id=quote.quote_id,
                idempotency_key="idem-key-ignoreme1",
                payment_method=CheckoutPaymentMethod.CARD,
            ),
        )
        self.checkout_service.handle_payment_intent_succeeded(
            event_object={
                "id": confirm.payment_action.payment_intent_id,
                "metadata": {"purpose": "grocery_order"},
            }
        )
        order = self.meal_order_repository.get_order(order_id=confirm.order_id)
        self.assertEqual(order.status, OrderStatus.PAYMENT_PROCESSING)


class MealOrderServiceCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeMealOrderRepository()
        self.service = MealOrderService(meal_order_repository=self.repository)
        self.user = User(
            id="user-1",
            name="Ada",
            email="ada@example.com",
            password_hash="hash",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.order = self.repository.create_order(
            order_number="MSO-TEST-1",
            user_id="user-1",
            status=OrderStatus.CONFIRMED,
            currency="GBP",
            delivery_type=MealDeliveryType.STANDARD,
            items=[
                {
                    "id": "item-1",
                    "meal_id": "meal-1",
                    "meal_name": "Jollof Rice",
                    "img_url": "",
                    "servings": 2,
                    "unit_price_minor": 650,
                    "line_total_minor": 1300,
                    "currency": "GBP",
                }
            ],
            pricing_summary={
                "currency": "GBP",
                "subtotal_minor": 1300,
                "delivery_fee_minor": 0,
                "service_fee_minor": 0,
                "total_minor": 1300,
            },
            address_snapshot={},
            payment_summary={
                "currency": "GBP",
                "wallet_amount_minor": 1300,
                "card_amount_minor": 0,
                "total_paid_minor": 1300,
                "provider": "wallet",
                "provider_payment_intent_id": None,
            },
            cancellation_window_expires_at=utc_now() + timedelta(minutes=20),
            status_history=[
                {
                    "status": OrderStatus.CONFIRMED.value,
                    "note": "Order created.",
                    "actor_user_id": "user-1",
                    "created_at": utc_now(),
                }
            ],
            metadata={},
        )

    def test_cancel_within_window_succeeds(self) -> None:
        response = self.service.cancel_order(current_user=self.user, order_id=self.order.id, reason="Changed my mind")
        self.assertEqual(response.order.status, OrderStatus.CANCELED.value)

    def test_cancel_after_window_expires_raises(self) -> None:
        expired_order = replace(
            self.order,
            cancellation_window_expires_at=utc_now() - timedelta(minutes=1),
        )
        self.repository.items[self.order.id] = expired_order
        with self.assertRaises(MealOrderTransitionError):
            self.service.cancel_order(current_user=self.user, order_id=self.order.id, reason="Too late")


class DeliveryWindowServiceRegressionTests(unittest.TestCase):
    """Confirms extracting DeliveryWindowService out of CheckoutService kept Grocery's
    3-window schedule (today 14-16 default, today 18-20, tomorrow 9-11) unchanged."""

    def test_grocery_delivery_windows_unchanged_after_extraction(self) -> None:
        service = DeliveryWindowService()
        windows = service.build_windows(
            timezone_name="Europe/London",
            specs=CheckoutService._DELIVERY_WINDOW_SPECS,
        )
        self.assertEqual(len(windows), 3)
        self.assertEqual(
            [window.window_id for window in windows],
            ["today-14-16", "today-18-20", "tomorrow-09-11"],
        )
        self.assertEqual(windows[0].label, "Today, 2:00 PM - 4:00 PM")
        self.assertEqual(windows[1].label, "Today, 6:00 PM - 8:00 PM")
        self.assertEqual(windows[2].label, "Tomorrow, 9:00 AM - 11:00 AM")
        self.assertTrue(windows[0].is_default)
        self.assertFalse(windows[1].is_default)
        self.assertFalse(windows[2].is_default)
        self.assertEqual(windows[2].starts_at - windows[0].starts_at, timedelta(hours=19))


class MealServiceFavoritesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.meal = make_meal()
        self.meal_repository = FakeMealRepository(self.meal)

        class _NoGroceryRepository:
            def list_products_by_ids(self, product_ids):
                return []

        self.meal_favorite_repository = MealFavoriteRepository(_FakeMongoCollection())
        self.service = MealService(
            meal_repository=self.meal_repository,
            grocery_repository=_NoGroceryRepository(),
            meal_favorite_repository=self.meal_favorite_repository,
        )

    def test_get_meal_not_found_raises(self) -> None:
        with self.assertRaises(MealNotFoundError):
            self.service.get_meal("does-not-exist", country=CountryCode.UNITED_KINGDOM)

    def test_get_meal_resolves_price_rating_and_tags(self) -> None:
        detail = self.service.get_meal("meal-1", country=CountryCode.UNITED_KINGDOM)
        self.assertIsNotNone(detail.resolved_selling_price)
        self.assertEqual(detail.resolved_selling_price.amount, 6.5)
        self.assertEqual(detail.rating_average, 4.8)
        self.assertEqual(detail.rating_count, 124)
        self.assertIn("high_protein", detail.highlight_tags)
        self.assertFalse(detail.is_favorited)


class _FakeMongoCollection:
    """Minimal in-memory stand-in for the subset of pymongo.Collection used by MealFavoriteRepository."""

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}

    def find_one(self, query):
        for document in self._docs.values():
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    def insert_one(self, document):
        self._docs[document["_id"]] = document

    def delete_one(self, query):
        for doc_id, document in list(self._docs.items()):
            if all(document.get(key) == value for key, value in query.items()):
                del self._docs[doc_id]
                break

    def find(self, query, projection=None):
        return [
            document
            for document in self._docs.values()
            if all(document.get(key) == value for key, value in query.items())
        ]


def make_saved_day_plan(
    *,
    plan_id: str = "plan-1",
    user_id: str = "user-1",
    effective_date,
    sections: list[dict],
) -> SavedMealPlan:
    now = utc_now()
    return SavedMealPlan(
        id=plan_id,
        user_id=user_id,
        title="My Meal Plan",
        status="saved",
        view_mode="day",
        plan_scope="standalone_day",
        effective_date=effective_date,
        week_start=None,
        week_end=None,
        day_index=None,
        parent_saved_plan_id=None,
        source_saved_plan_id=None,
        linked_day_plan_ids=[],
        meal_type=None,
        country_code=None,
        planned_meals=[],
        plan_payload={"sections": sections},
        requested_culture=None,
        user_goal=None,
        source_snapshot_id="test-snapshot",
        source_conversation_id="manual",
        agent_type="slot_mutation",
        created_at=now,
        updated_at=now,
    )


class FakeSavedMealPlanRepository:
    def __init__(self, plan: SavedMealPlan | None = None) -> None:
        self.plan = plan

    def get_saved_day_plan_for_date(self, *, user_id: str, effective_date, allowed_statuses=None):
        if self.plan is not None and self.plan.effective_date == effective_date:
            if allowed_statuses and self.plan.status not in allowed_statuses:
                return None
            return self.plan
        return None

    def get_saved_weekly_plan_for_week(self, *, user_id: str, week_start, week_end, allowed_statuses=None):
        return None

    def get_saved_weekly_plan_covering_date(self, *, user_id: str, target_date, allowed_statuses=None):
        return None

    def get_saved_plan(self, *, user_id: str, saved_plan_id: str):
        if self.plan is not None and self.plan.user_id == user_id and self.plan.id == saved_plan_id:
            return self.plan
        return None


class FakeSavedMealPlanService:
    def __init__(self, repository: FakeSavedMealPlanRepository) -> None:
        self.repository = repository

    def publish_saved_plan(self, *, user_id: str, saved_plan_id: str):
        plan = self.repository.get_saved_plan(user_id=user_id, saved_plan_id=saved_plan_id)
        if plan is None:
            raise AssertionError("Missing saved plan in fake publish.")
        if plan.status == "draft":
            self.repository.plan = replace(plan, status="saved")
            return self.repository.plan
        return plan


class MealPlanCheckoutServiceTests(unittest.TestCase):
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
        self.meal_one = make_meal(meal_id="meal-1", price_amount_minor=650)
        self.meal_two = make_meal(meal_id="meal-2", price_amount_minor=800)
        self.meal_repository = FakeMealRepository(self.meal_one, self.meal_two)

        self.plan_date = utc_now().date()
        self.plan = make_saved_day_plan(
            effective_date=self.plan_date,
            sections=[
                {
                    "slot": "lunch",
                    "items": [
                        {"meal_id": "meal-1", "name": "Jollof Rice", "servings": 2, "hero_image_url": ""},
                    ],
                },
                {
                    "slot": "dinner",
                    "items": [
                        {"meal_id": "meal-2", "name": "Egusi Soup", "servings": 1, "hero_image_url": ""},
                    ],
                },
            ],
        )
        self.saved_meal_plan_repository = FakeSavedMealPlanRepository(self.plan)

        self.address = UserDeliveryAddress(
            id="addr-1",
            user_id="user-1",
            label="Home",
            recipient_name="Ada",
            phone_number="+441234567890",
            line1="1 Test Street",
            line2="",
            city="London",
            state="",
            postal_code="E1 6AN",
            country="GB",
            delivery_notes="",
            is_default=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.address_repository = FakeAddressRepository(self.address)
        self.checkout_quote_repository = FakeCheckoutQuoteRepository()
        self.meal_order_repository = FakeMealOrderRepository()
        self.payment_attempt_repository = FakePaymentAttemptRepository()
        self.subscription_repo = FakeSubscriptionRepository()
        self.wallet_repo = FakeWalletAccountRepository()
        self.ledger_repo = FakeWalletLedgerRepository()
        self.billing_service = BillingService(
            subscription_repository=self.subscription_repo,
            wallet_account_repository=self.wallet_repo,
            wallet_ledger_repository=self.ledger_repo,
        )
        self.stripe_gateway = FakeStripeGateway()
        self.service = MealPlanCheckoutService(
            saved_meal_plan_repository=self.saved_meal_plan_repository,
            meal_repository=self.meal_repository,
            checkout_quote_repository=self.checkout_quote_repository,
            meal_order_repository=self.meal_order_repository,
            payment_attempt_repository=self.payment_attempt_repository,
            address_repository=self.address_repository,
            billing_service=self.billing_service,
            saved_meal_plan_service=FakeSavedMealPlanService(self.saved_meal_plan_repository),
            stripe_gateway=self.stripe_gateway,
            default_currency="GBP",
            quote_ttl_seconds=900,
            cancellation_window_minutes=20,
        )

    def test_quote_builds_line_items_with_delivery_date_and_slot(self) -> None:
        quote = self.service.create_quote(
            current_user=self.user,
            payload=MealPlanCheckoutQuoteRequest(
                address_id="addr-1",
                effective_date=self.plan_date,
                view="day",
            ),
        )
        self.assertEqual(len(quote.items), 2)
        self.assertEqual(quote.subtotal_minor, 650 * 2 + 800 * 1)
        self.assertEqual(quote.total_minor, quote.subtotal_minor)
        self.assertEqual(quote.delivery_fee_minor, 0)
        self.assertEqual(quote.delivery_days, [self.plan_date])
        slots = {item.slot for item in quote.items}
        self.assertEqual(slots, {"lunch", "dinner"})

    def test_quote_missing_plan_raises(self) -> None:
        empty_repository = FakeSavedMealPlanRepository(None)
        service = MealPlanCheckoutService(
            saved_meal_plan_repository=empty_repository,
            meal_repository=self.meal_repository,
            checkout_quote_repository=self.checkout_quote_repository,
            meal_order_repository=self.meal_order_repository,
            payment_attempt_repository=self.payment_attempt_repository,
            address_repository=self.address_repository,
            billing_service=self.billing_service,
            saved_meal_plan_service=FakeSavedMealPlanService(empty_repository),
            stripe_gateway=self.stripe_gateway,
            default_currency="GBP",
            quote_ttl_seconds=900,
            cancellation_window_minutes=20,
        )
        with self.assertRaises(MealPlanCheckoutError):
            service.create_quote(
                current_user=self.user,
                payload=MealPlanCheckoutQuoteRequest(
                    address_id="addr-1",
                    effective_date=self.plan_date,
                    view="day",
                ),
            )

    def test_confirm_wallet_only_checkout_creates_one_order_with_all_items(self) -> None:
        self.wallet_repo.ensure_default_for_user(user_id=self.user.id, currency="GBP")
        self.wallet_repo.apply_balance_delta(wallet_account_id=f"wallet-{self.user.id}", available_delta_minor=5000)

        quote = self.service.create_quote(
            current_user=self.user,
            payload=MealPlanCheckoutQuoteRequest(
                address_id="addr-1",
                effective_date=self.plan_date,
                view="day",
            ),
        )
        confirm = self.service.confirm_checkout(
            current_user=self.user,
            payload=MealPlanCheckoutConfirmRequest(
                quote_id=quote.quote_id,
                idempotency_key="idem-plan-checkout-1",
                payment_method=CheckoutPaymentMethod.WALLET,
            ),
        )
        self.assertFalse(confirm.requires_payment_action)
        self.assertEqual(confirm.status, OrderStatus.CONFIRMED.value)
        self.assertEqual(len(self.meal_order_repository.items), 1)
        order = next(iter(self.meal_order_repository.items.values()))
        self.assertEqual(len(order.items), 2)
        self.assertEqual({item.slot for item in order.items}, {"lunch", "dinner"})
        self.assertTrue(all(item.delivery_date == self.plan_date for item in order.items))
        self.assertEqual(order.metadata.get("saved_plan_id"), "plan-1")

    def test_grocery_and_meal_order_webhooks_are_ignored_by_plan_checkout_service(self) -> None:
        self.wallet_repo.ensure_default_for_user(user_id=self.user.id, currency="GBP")
        self.wallet_repo.apply_balance_delta(wallet_account_id=f"wallet-{self.user.id}", available_delta_minor=5000)
        quote = self.service.create_quote(
            current_user=self.user,
            payload=MealPlanCheckoutQuoteRequest(
                address_id="addr-1",
                effective_date=self.plan_date,
                view="day",
            ),
        )
        confirm = self.service.confirm_checkout(
            current_user=self.user,
            payload=MealPlanCheckoutConfirmRequest(
                quote_id=quote.quote_id,
                idempotency_key="idem-plan-checkout-2",
                payment_method=CheckoutPaymentMethod.CARD,
            ),
        )
        self.assertTrue(confirm.requires_payment_action)
        # Neither a grocery_order nor a plain meal_order webhook should touch this order.
        self.service.handle_payment_intent_succeeded(
            event_object={"id": "pi_unrelated", "metadata": {"purpose": "meal_order"}}
        )
        order = self.meal_order_repository.get_order(order_id=confirm.order_id)
        self.assertEqual(order.status, OrderStatus.PAYMENT_PROCESSING)

        self.service.handle_payment_intent_succeeded(
            event_object={
                "id": confirm.payment_action.payment_intent_id,
                "metadata": {"purpose": "meal_plan_order"},
            }
        )
        order = self.meal_order_repository.get_order(order_id=confirm.order_id)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)


class MealOrderEstimatedStatusTests(unittest.TestCase):
    def test_estimated_status_reflects_date_and_order_status(self) -> None:
        from app.models.meal_order import MealOrderItemSnapshot

        today = utc_now().date()
        past_item = MealOrderItemSnapshot(
            id="i1", meal_id="m1", meal_name="Past", img_url="", servings=1,
            unit_price_minor=100, line_total_minor=100, currency="GBP",
            delivery_date=today - timedelta(days=1), slot="lunch",
        )
        today_item = replace(past_item, id="i2", delivery_date=today)
        future_item = replace(past_item, id="i3", delivery_date=today + timedelta(days=1))
        no_date_item = replace(past_item, id="i4", delivery_date=None)

        self.assertEqual(
            MealOrderService._estimated_status(past_item, order_status=OrderStatus.CONFIRMED),
            "delivered",
        )
        self.assertEqual(
            MealOrderService._estimated_status(today_item, order_status=OrderStatus.CONFIRMED),
            "out_for_delivery",
        )
        self.assertEqual(
            MealOrderService._estimated_status(future_item, order_status=OrderStatus.CONFIRMED),
            "upcoming",
        )
        self.assertEqual(
            MealOrderService._estimated_status(no_date_item, order_status=OrderStatus.CONFIRMED),
            "upcoming",
        )
        self.assertEqual(
            MealOrderService._estimated_status(past_item, order_status=OrderStatus.PENDING_PAYMENT),
            "upcoming",
        )
        self.assertEqual(
            MealOrderService._estimated_status(past_item, order_status=OrderStatus.CANCELED),
            "canceled",
        )


if __name__ == "__main__":
    unittest.main()
