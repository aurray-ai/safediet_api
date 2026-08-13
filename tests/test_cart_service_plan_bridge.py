from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.cart import Cart, CartItem, CartItemPricingState, CartStatus
from app.models.grocery import CountryCode, CountryPrice, CurrencyCode, GroceryProduct
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User, UserType
from app.schemas.cart import CartItemUpsertRequest
from app.services.cart_service import CartService, CartValidationError
from app.services.inventory_service import ResolvedMemberPrice


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


def build_product(*, product_id: str, name: str, amount: float) -> GroceryProduct:
    now = utc_now()
    return GroceryProduct(
        id=product_id,
        category_id="cat-1",
        img_url="https://example.com/img.png",
        product=name,
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
        sort_order=0,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def make_saved_plan(*, plan_id: str, buy_items: list[dict]) -> SavedMealPlan:
    now = utc_now()
    return SavedMealPlan(
        id=plan_id,
        user_id="user-1",
        title="Meal Plan",
        status="saved",
        view_mode="day",
        plan_scope="standalone_day",
        effective_date=None,
        week_start=None,
        week_end=None,
        day_index=None,
        parent_saved_plan_id=None,
        source_saved_plan_id=None,
        linked_day_plan_ids=[],
        meal_type=None,
        country_code=None,
        planned_meals=[],
        plan_payload={"cart_summary": {"buy_items": buy_items}},
        requested_culture=None,
        user_goal=None,
        source_snapshot_id=f"snapshot-{plan_id}",
        source_conversation_id="conversation-1",
        agent_type="meal_planner_agent",
        created_at=now,
        updated_at=now,
    )


class StubGroceryRepository:
    def __init__(self, products: dict[str, GroceryProduct]) -> None:
        self._products = products

    def get_product(self, product_id: str) -> GroceryProduct | None:
        return self._products.get(product_id)


class StubInventoryService:
    def __init__(self, items: dict[str, SimpleNamespace]) -> None:
        self._items = items

    def ensure_sellable_inventory_item(self, *, product_id: str, store_id: str | None = None):
        return self._items.get(product_id)

    def resolve_unit_price_minor(self, *, product: GroceryProduct, currency: str) -> int:
        active_prices = [price for price in product.prices if price.is_active]
        return int(round(active_prices[0].amount * 100)) if active_prices else 0

    def resolve_member_unit_price_minor(
        self, *, product: GroceryProduct, currency: str, is_subscriber: bool
    ) -> ResolvedMemberPrice:
        base_price_minor = self.resolve_unit_price_minor(product=product, currency=currency)
        return ResolvedMemberPrice(
            base_price_minor=base_price_minor,
            unit_price_minor=base_price_minor,
            discount_percent_applied=0.0,
            member_price_minor=base_price_minor,
            member_discount_percent=0.0,
        )

    def resolve_weight_based_delivery_fee(
        self, *, total_weight_grams: int, currency: str, store_id: str | None = None
    ) -> int:
        return 0


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

    def save_cart(
        self,
        *,
        cart_id,
        items,
        selected_address_id,
        pricing_snapshot,
        last_priced_at,
        expires_at,
        status,
    ) -> Cart:
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


class StubSubscriptionAccountRepository:
    def get_by_user_id(self, *, user_id: str):
        return None


class StubSavedMealPlanRepository:
    def __init__(self, plan: SavedMealPlan | None) -> None:
        self._plan = plan

    def get_saved_plan(self, *, user_id: str, saved_plan_id: str) -> SavedMealPlan | None:
        if self._plan is not None and self._plan.id == saved_plan_id and self._plan.user_id == user_id:
            return self._plan
        return None


def build_inventory_item(*, product_id: str, unit_weight_grams: int = 500, max_per_order: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        is_active=True,
        unit_label="pack",
        unit_weight_grams=unit_weight_grams,
        max_per_order=max_per_order,
        available_quantity=999,
        allow_substitutions=True,
    )


def build_service(
    *,
    grocery_repository: StubGroceryRepository,
    inventory_service: StubInventoryService,
    cart_repository: StubCartRepository,
    saved_meal_plan_repository: StubSavedMealPlanRepository,
) -> CartService:
    return CartService(
        cart_repository=cart_repository,
        grocery_repository=grocery_repository,
        inventory_repository=object(),
        address_repository=object(),
        inventory_service=inventory_service,
        saved_meal_plan_repository=saved_meal_plan_repository,
        subscription_account_repository=StubSubscriptionAccountRepository(),
        default_store_id="main_store",
        default_currency="GBP",
        free_delivery_subtotal_minor=0,
        cart_ttl_seconds=3600,
        max_quantity_per_line=25,
    )


class CartServicePlanBridgeTests(unittest.TestCase):
    def test_add_saved_plan_buy_items_stamps_provenance_on_new_cart_item(self) -> None:
        plan = make_saved_plan(
            plan_id="plan-1",
            buy_items=[
                {
                    "product_id": "prod-rice",
                    "required_quantity": 400,
                    "unit": "g",
                    "meal_ids": ["meal-1", "meal-2"],
                    "is_shared": True,
                }
            ],
        )
        service = build_service(
            grocery_repository=StubGroceryRepository(
                {"prod-rice": build_product(product_id="prod-rice", name="Rice", amount=2.5)}
            ),
            inventory_service=StubInventoryService(
                {"prod-rice": build_inventory_item(product_id="prod-rice", unit_weight_grams=500)}
            ),
            cart_repository=StubCartRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository(plan),
        )

        response = service.add_saved_plan_buy_items(current_user=build_user(), saved_plan_id="plan-1")

        self.assertEqual(0, len(response.skipped_items))
        self.assertEqual(1, len(response.cart.items))
        item = response.cart.items[0]
        self.assertEqual("prod-rice", item.product_id)
        self.assertEqual("plan-1", item.source_saved_plan_id)
        self.assertEqual(["meal-1", "meal-2"], item.source_meal_ids)
        self.assertEqual(1, item.quantity)

    def test_add_saved_plan_buy_items_skips_missing_product(self) -> None:
        plan = make_saved_plan(
            plan_id="plan-1",
            buy_items=[{"product_id": "prod-missing", "required_quantity": 100, "unit": "g", "meal_ids": []}],
        )
        service = build_service(
            grocery_repository=StubGroceryRepository({}),
            inventory_service=StubInventoryService({}),
            cart_repository=StubCartRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository(plan),
        )

        response = service.add_saved_plan_buy_items(current_user=build_user(), saved_plan_id="plan-1")

        self.assertEqual(0, len(response.cart.items))
        self.assertEqual(1, len(response.skipped_items))
        self.assertEqual("prod-missing", response.skipped_items[0].product_id)
        self.assertEqual("Product not found.", response.skipped_items[0].reason)

    def test_add_saved_plan_buy_items_skips_unpurchasable_product(self) -> None:
        plan = make_saved_plan(
            plan_id="plan-1",
            buy_items=[{"product_id": "prod-rice", "required_quantity": 100, "unit": "g", "meal_ids": []}],
        )
        service = build_service(
            grocery_repository=StubGroceryRepository(
                {"prod-rice": build_product(product_id="prod-rice", name="Rice", amount=2.5)}
            ),
            inventory_service=StubInventoryService({}),
            cart_repository=StubCartRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository(plan),
        )

        response = service.add_saved_plan_buy_items(current_user=build_user(), saved_plan_id="plan-1")

        self.assertEqual(0, len(response.cart.items))
        self.assertEqual(1, len(response.skipped_items))
        self.assertEqual("Product is not purchasable.", response.skipped_items[0].reason)

    def test_add_saved_plan_buy_items_raises_when_plan_not_found(self) -> None:
        service = build_service(
            grocery_repository=StubGroceryRepository({}),
            inventory_service=StubInventoryService({}),
            cart_repository=StubCartRepository(),
            saved_meal_plan_repository=StubSavedMealPlanRepository(None),
        )

        with self.assertRaises(CartValidationError):
            service.add_saved_plan_buy_items(current_user=build_user(), saved_plan_id="does-not-exist")

    def test_add_saved_plan_buy_items_preserves_manually_added_items(self) -> None:
        plan = make_saved_plan(
            plan_id="plan-1",
            buy_items=[{"product_id": "prod-rice", "required_quantity": 200, "unit": "g", "meal_ids": ["meal-1"]}],
        )
        cart_repository = StubCartRepository()
        grocery_repository = StubGroceryRepository(
            {
                "prod-rice": build_product(product_id="prod-rice", name="Rice", amount=2.5),
                "prod-eggs": build_product(product_id="prod-eggs", name="Eggs", amount=3.0),
            }
        )
        inventory_service = StubInventoryService(
            {
                "prod-rice": build_inventory_item(product_id="prod-rice"),
                "prod-eggs": build_inventory_item(product_id="prod-eggs"),
            }
        )
        service = build_service(
            grocery_repository=grocery_repository,
            inventory_service=inventory_service,
            cart_repository=cart_repository,
            saved_meal_plan_repository=StubSavedMealPlanRepository(plan),
        )
        service.upsert_item(
            current_user=build_user(),
            payload=CartItemUpsertRequest(product_id="prod-eggs", quantity=2),
        )

        response = service.add_saved_plan_buy_items(current_user=build_user(), saved_plan_id="plan-1")

        product_ids = {item.product_id for item in response.cart.items}
        self.assertEqual({"prod-rice", "prod-eggs"}, product_ids)
        eggs_item = next(item for item in response.cart.items if item.product_id == "prod-eggs")
        self.assertIsNone(eggs_item.source_saved_plan_id)


if __name__ == "__main__":
    unittest.main()
