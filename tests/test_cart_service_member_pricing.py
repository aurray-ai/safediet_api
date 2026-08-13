from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.billing import SubscriptionStatus
from app.models.cart import Cart, CartItem, CartItemPricingState, CartStatus
from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryDiscount, GroceryProduct
from app.models.user import User, UserType
from app.schemas.cart import CartItemUpsertRequest
from app.services.cart_service import CartService
from app.services.inventory_service import InventoryService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user() -> User:
    return User(
        id="user-1",
        name="Test User",
        email="test@example.com",
        password_hash="x",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


def build_discount(*, discount_id: str = "disc-1", percent: float) -> GroceryDiscount:
    now = utc_now()
    return GroceryDiscount(
        id=discount_id,
        label=f"{percent:g}% Off",
        percent=percent,
        created_at=now,
        updated_at=now,
    )


def build_product(*, amount: float = 10.0, discount_id: str | None = "disc-1") -> GroceryProduct:
    now = utc_now()
    return GroceryProduct(
        id="product-1",
        category_id="cat-1",
        img_url="",
        product="Chicken breast",
        product_tags=[],
        culture_tags=[],
        nutritional_specs=[],
        prices=[
            CountryPrice(
                country_code=CountryCode.UNITED_KINGDOM,
                currency_code=CurrencyCode.POUND_STERLING,
                amount=amount,
                price_unit="pack",
                source="test",
                updated_at=now,
                is_active=True,
            )
        ],
        description="",
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
        discount_id=discount_id,
    )


class StubGroceryRepository:
    def __init__(self, *, product: GroceryProduct) -> None:
        self._product = product

    def get_product(self, product_id: str):
        return self._product if product_id == self._product.id else None

    def get_product_by_id(self, product_id: str):
        return self.get_product(product_id)


class StubDiscountRepository:
    def __init__(self, *, discount: GroceryDiscount | None) -> None:
        self._discount = discount

    def get_discount(self, discount_id: str):
        return self._discount if self._discount is not None and self._discount.id == discount_id else None


class StubInventoryRepository:
    def __init__(self, item: SimpleNamespace) -> None:
        self._item = item

    def get_by_product_id(self, *, store_id: str, product_id: str):
        return self._item

    def list_delivery_fee_rules(self, *, store_id: str, currency: str):
        return []


class StubCartRepository:
    def __init__(self) -> None:
        self.cart: Cart | None = None

    def ensure_active_cart(self, *, user_id: str, store_id: str, currency: str) -> Cart:
        if self.cart is not None:
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

    def save_cart(self, *, cart_id, items, selected_address_id, pricing_snapshot, last_priced_at, expires_at, status) -> Cart:
        assert self.cart is not None
        built_items = [
            CartItem(
                id=str(item["id"]),
                product_id=str(item["product_id"]),
                category_id=str(item["category_id"]),
                product_name=str(item["product_name"]),
                img_url=str(item["img_url"]),
                quantity=int(item["quantity"]),
                unit_label=str(item["unit_label"]),
                unit_weight_grams=int(item["unit_weight_grams"]),
                observed_unit_price_minor=int(item["observed_unit_price_minor"]),
                current_unit_price_minor=int(item["current_unit_price_minor"]),
                base_price_minor=int(item.get("base_price_minor") or item["current_unit_price_minor"]),
                discount_percent_applied=float(item.get("discount_percent_applied") or 0.0),
                member_price_minor=int(item.get("member_price_minor") or item["current_unit_price_minor"]),
                member_discount_percent=float(item.get("member_discount_percent") or 0.0),
                currency=str(item["currency"]),
                allow_substitutions=bool(item["allow_substitutions"]),
                substitution_note=str(item["substitution_note"]),
                pricing_state=CartItemPricingState(str(item["pricing_state"])),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
                source_saved_plan_id=item.get("source_saved_plan_id"),
                source_meal_ids=list(item.get("source_meal_ids") or []),
            )
            for item in items
        ]
        self.cart = Cart(
            id=self.cart.id,
            user_id=self.cart.user_id,
            store_id=self.cart.store_id,
            currency=self.cart.currency,
            status=status,
            items=built_items,
            selected_address_id=selected_address_id,
            pricing_snapshot=dict(pricing_snapshot),
            last_priced_at=last_priced_at,
            expires_at=expires_at,
            created_at=self.cart.created_at,
            updated_at=utc_now(),
        )
        return self.cart


class StubSavedMealPlanRepository:
    def get_saved_plan(self, *, user_id, saved_plan_id):
        return None


class StubSubscriptionAccountRepository:
    def __init__(self, *, is_premium: bool, status: SubscriptionStatus | None = None) -> None:
        self._is_premium = is_premium
        self._status = status or (SubscriptionStatus.ACTIVE if is_premium else SubscriptionStatus.INACTIVE)

    def get_by_user_id(self, *, user_id: str):
        return SimpleNamespace(is_premium=self._is_premium, status=self._status)


def build_service(*, product, discount, inventory_item, is_premium: bool, subscription_status: SubscriptionStatus | None = None):
    grocery_repository = StubGroceryRepository(product=product)
    inventory_service = InventoryService(
        inventory_repository=StubInventoryRepository(inventory_item),
        grocery_repository=grocery_repository,
        discount_repository=StubDiscountRepository(discount=discount),
        default_store_id="main_store",
    )
    cart_repository = StubCartRepository()
    service = CartService(
        cart_repository=cart_repository,
        grocery_repository=grocery_repository,
        inventory_repository=object(),
        address_repository=object(),
        inventory_service=inventory_service,
        saved_meal_plan_repository=StubSavedMealPlanRepository(),
        subscription_account_repository=StubSubscriptionAccountRepository(
            is_premium=is_premium, status=subscription_status
        ),
        default_store_id="main_store",
        default_currency="GBP",
        free_delivery_subtotal_minor=0,
        cart_ttl_seconds=3600,
        max_quantity_per_line=25,
    )
    return service, cart_repository


def build_inventory_item() -> SimpleNamespace:
    return SimpleNamespace(
        is_active=True,
        unit_label="pack",
        unit_weight_grams=500,
        max_per_order=10,
        available_quantity=999,
        allow_substitutions=True,
    )


class CartServiceMemberPricingTests(unittest.TestCase):
    def test_add_item_as_subscriber_stamps_discounted_price(self) -> None:
        product = build_product(amount=10.0)
        discount = build_discount(percent=10.0)
        service, _ = build_service(
            product=product, discount=discount, inventory_item=build_inventory_item(), is_premium=True
        )

        response = service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        item = response.items[0]
        self.assertEqual(1000, item.base_price_minor)
        self.assertEqual(900, item.current_unit_price_minor)
        self.assertEqual(10.0, item.discount_percent_applied)
        self.assertEqual(900, item.member_price_minor)
        self.assertEqual(10.0, item.member_discount_percent)
        self.assertEqual(1000, response.summary.base_subtotal_minor)
        self.assertEqual(900, response.summary.member_subtotal_minor)
        self.assertEqual(100, response.summary.savings_minor)

    def test_non_subscriber_cart_still_exposes_member_price_and_savings(self) -> None:
        # A non-subscriber is charged base price, but the cart must still surface
        # what a member would pay so the UI can show "members would pay £X /
        # you could save £Y" even though nothing is being discounted for them.
        product = build_product(amount=10.0)
        discount = build_discount(percent=10.0)
        service, _ = build_service(
            product=product, discount=discount, inventory_item=build_inventory_item(), is_premium=False
        )

        response = service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        item = response.items[0]
        self.assertEqual(1000, item.current_unit_price_minor)
        self.assertEqual(0.0, item.discount_percent_applied)
        self.assertEqual(900, item.member_price_minor)
        self.assertEqual(10.0, item.member_discount_percent)
        self.assertEqual(1000, response.summary.subtotal_minor)
        self.assertEqual(1000, response.summary.base_subtotal_minor)
        self.assertEqual(900, response.summary.member_subtotal_minor)
        self.assertEqual(100, response.summary.savings_minor)

    def test_add_item_with_stale_premium_flag_but_canceled_status_pays_base_price(self) -> None:
        # Reproduces the reported bug: is_premium is still True from before the
        # subscription was canceled (e.g. a missed Stripe webhook left it stale),
        # but status has already moved to CANCELED. The charged price must not
        # keep the member discount off that stale flag.
        product = build_product(amount=10.0)
        discount = build_discount(percent=10.0)
        service, _ = build_service(
            product=product,
            discount=discount,
            inventory_item=build_inventory_item(),
            is_premium=True,
            subscription_status=SubscriptionStatus.CANCELED,
        )

        response = service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        item = response.items[0]
        self.assertEqual(1000, item.base_price_minor)
        self.assertEqual(1000, item.current_unit_price_minor)
        self.assertEqual(0.0, item.discount_percent_applied)

    def test_add_item_as_non_subscriber_pays_base_price(self) -> None:
        product = build_product(amount=10.0)
        discount = build_discount(percent=10.0)
        service, _ = build_service(
            product=product, discount=discount, inventory_item=build_inventory_item(), is_premium=False
        )

        response = service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        item = response.items[0]
        self.assertEqual(1000, item.base_price_minor)
        self.assertEqual(1000, item.current_unit_price_minor)
        self.assertEqual(0.0, item.discount_percent_applied)

    def test_reprice_reflects_discount_change_since_item_was_added(self) -> None:
        product = build_product(amount=10.0)
        discount = build_discount(percent=10.0)
        service, cart_repository = build_service(
            product=product, discount=discount, inventory_item=build_inventory_item(), is_premium=True
        )
        service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        # The discount's percent increases after the item was added to the cart.
        richer_discount = build_discount(percent=20.0)
        service._grocery_repository = StubGroceryRepository(product=product)
        service._inventory_service = InventoryService(
            inventory_repository=StubInventoryRepository(build_inventory_item()),
            grocery_repository=service._grocery_repository,
            discount_repository=StubDiscountRepository(discount=richer_discount),
            default_store_id="main_store",
        )

        revalidated = service.validate_cart(current_user=build_user())

        item = revalidated.cart.items[0]
        self.assertEqual(800, item.current_unit_price_minor)
        self.assertEqual(20.0, item.discount_percent_applied)
        self.assertEqual("price_changed", item.pricing_state.value)


if __name__ == "__main__":
    unittest.main()
