from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.cart import Cart, CartItem, CartItemPricingState, CartStatus
from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryCategory, GroceryCategorySlug, GroceryProduct
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


def build_category(*, discount_percent: float | None) -> GroceryCategory:
    now = utc_now()
    return GroceryCategory(
        id="cat-1",
        slug=GroceryCategorySlug.PROTEIN,
        name="Protein",
        icon_name="protein",
        img_url="",
        description="",
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
        discount_percent=discount_percent,
    )


def build_product(*, amount: float = 10.0) -> GroceryProduct:
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
    )


class StubGroceryRepository:
    def __init__(self, *, product: GroceryProduct, category: GroceryCategory) -> None:
        self._product = product
        self._category = category

    def get_product(self, product_id: str):
        return self._product if product_id == self._product.id else None

    def get_product_by_id(self, product_id: str):
        return self.get_product(product_id)

    def get_category(self, category_id: str):
        return self._category if category_id == self._category.id else None


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
    def __init__(self, *, is_premium: bool) -> None:
        self._is_premium = is_premium

    def get_by_user_id(self, *, user_id: str):
        return SimpleNamespace(is_premium=self._is_premium)


def build_service(*, product, category, inventory_item, is_premium: bool):
    grocery_repository = StubGroceryRepository(product=product, category=category)
    inventory_service = InventoryService(
        inventory_repository=StubInventoryRepository(inventory_item),
        grocery_repository=grocery_repository,
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
        subscription_account_repository=StubSubscriptionAccountRepository(is_premium=is_premium),
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
        category = build_category(discount_percent=10.0)
        service, _ = build_service(
            product=product, category=category, inventory_item=build_inventory_item(), is_premium=True
        )

        response = service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        item = response.items[0]
        self.assertEqual(1000, item.base_price_minor)
        self.assertEqual(900, item.current_unit_price_minor)
        self.assertEqual(10.0, item.discount_percent_applied)

    def test_add_item_as_non_subscriber_pays_base_price(self) -> None:
        product = build_product(amount=10.0)
        category = build_category(discount_percent=10.0)
        service, _ = build_service(
            product=product, category=category, inventory_item=build_inventory_item(), is_premium=False
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
        category = build_category(discount_percent=10.0)
        service, cart_repository = build_service(
            product=product, category=category, inventory_item=build_inventory_item(), is_premium=True
        )
        service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="product-1", quantity=1),
        )

        # Category discount increases after the item was added to the cart.
        richer_category = build_category(discount_percent=20.0)
        service._grocery_repository = StubGroceryRepository(product=product, category=richer_category)
        service._inventory_service = InventoryService(
            inventory_repository=StubInventoryRepository(build_inventory_item()),
            grocery_repository=service._grocery_repository,
            default_store_id="main_store",
        )

        revalidated = service.validate_cart(current_user=build_user())

        item = revalidated.cart.items[0]
        self.assertEqual(800, item.current_unit_price_minor)
        self.assertEqual(20.0, item.discount_percent_applied)
        self.assertEqual("price_changed", item.pricing_state.value)


if __name__ == "__main__":
    unittest.main()
