from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.cart import Cart, CartItem, CartItemPricingState, CartStatus
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.repositories.cart_repository import CartRepository
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.subscription_account_repository import SubscriptionAccountRepository
from app.schemas.cart import (
    CartAddPlanItemsResponse,
    CartItemQuantityUpdateRequest,
    CartItemResponse,
    CartItemUpsertRequest,
    CartResponse,
    CartSelectAddressRequest,
    CartSkippedPlanItemResponse,
    CartSummaryResponse,
    CartValidateResponse,
    CartValidationIssueResponse,
)
from app.services.inventory_service import InventoryService


class CartItemNotFoundError(Exception):
    pass


class CartValidationError(Exception):
    pass


class CartService:
    def __init__(
        self,
        *,
        cart_repository: CartRepository,
        grocery_repository: GroceryRepository,
        inventory_repository: InventoryRepository,
        address_repository: AddressRepository,
        inventory_service: InventoryService,
        saved_meal_plan_repository: SavedMealPlanRepository,
        subscription_account_repository: SubscriptionAccountRepository,
        default_store_id: str,
        default_currency: str,
        free_delivery_subtotal_minor: int,
        cart_ttl_seconds: int,
        max_quantity_per_line: int,
    ) -> None:
        self._cart_repository = cart_repository
        self._grocery_repository = grocery_repository
        self._inventory_repository = inventory_repository
        self._address_repository = address_repository
        self._inventory_service = inventory_service
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._subscription_account_repository = subscription_account_repository
        self._default_store_id = default_store_id
        self._default_currency = default_currency
        self._free_delivery_subtotal_minor = max(0, int(free_delivery_subtotal_minor))
        self._cart_ttl_seconds = cart_ttl_seconds
        self._max_quantity_per_line = max_quantity_per_line

    def get_cart(self, *, current_user: User, currency: str | None = None) -> CartResponse:
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=currency or self._default_currency,
        )
        repriced = self._reprice_cart(cart=cart)
        return self._to_response(repriced)

    def upsert_item(self, *, current_user: User, payload: CartItemUpsertRequest) -> CartResponse:
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=self._default_currency,
        )
        existing_item = next((item for item in cart.items if item.product_id == payload.product_id), None)
        document = self._resolve_item_document(
            cart=cart,
            product_id=payload.product_id,
            quantity=payload.quantity,
            allow_substitutions=payload.allow_substitutions,
            substitution_note=payload.substitution_note,
            existing_item=existing_item,
        )
        items = [
            document if item.product_id == payload.product_id else self._item_to_document(item)
            for item in cart.items
        ]
        if existing_item is None:
            items.append(document)
        saved = self._cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return self._to_response(self._reprice_cart(cart=saved))

    def add_saved_plan_buy_items(self, *, current_user: User, saved_plan_id: str) -> CartAddPlanItemsResponse:
        plan = self._saved_meal_plan_repository.get_saved_plan(
            user_id=current_user.id,
            saved_plan_id=saved_plan_id,
        )
        if plan is None:
            raise CartValidationError("Saved meal plan not found.")

        buy_items = list(((plan.plan_payload or {}).get("cart_summary") or {}).get("buy_items") or [])
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=self._default_currency,
        )
        documents_by_product = {item.product_id: self._item_to_document(item) for item in cart.items}
        items_by_product = {item.product_id: item for item in cart.items}
        skipped: list[CartSkippedPlanItemResponse] = []

        for buy_item in buy_items:
            product_id = str(buy_item.get("product_id") or "").strip()
            if not product_id:
                continue
            existing_item = items_by_product.get(product_id)
            meal_ids = [str(meal_id) for meal_id in list(buy_item.get("meal_ids") or [])]
            try:
                quantity = self._estimate_pack_quantity(
                    required_quantity=float(buy_item.get("required_quantity") or 0),
                    unit=str(buy_item.get("unit") or ""),
                    product_id=product_id,
                )
                document = self._resolve_item_document(
                    cart=cart,
                    product_id=product_id,
                    quantity=quantity,
                    allow_substitutions=existing_item.allow_substitutions if existing_item is not None else True,
                    substitution_note=existing_item.substitution_note if existing_item is not None else "",
                    existing_item=existing_item,
                    source_saved_plan_id=saved_plan_id,
                    source_meal_ids=meal_ids,
                )
            except CartValidationError as exc:
                skipped.append(CartSkippedPlanItemResponse(product_id=product_id, reason=str(exc)))
                continue
            documents_by_product[product_id] = document

        saved = self._cart_repository.save_cart(
            cart_id=cart.id,
            items=list(documents_by_product.values()),
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return CartAddPlanItemsResponse(
            cart=self._to_response(self._reprice_cart(cart=saved)),
            skipped_items=skipped,
        )

    def _resolve_item_document(
        self,
        *,
        cart: Cart,
        product_id: str,
        quantity: int,
        allow_substitutions: bool,
        substitution_note: str,
        existing_item: CartItem | None,
        source_saved_plan_id: str | None = None,
        source_meal_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if quantity > self._max_quantity_per_line:
            raise CartValidationError("Requested quantity exceeds the cart limit.")
        product = self._grocery_repository.get_product(product_id)
        if product is None:
            raise CartValidationError("Product not found.")
        inventory = self._inventory_service.ensure_sellable_inventory_item(
            product_id=product_id,
            store_id=self._default_store_id,
        )
        if inventory is None or not inventory.is_active:
            raise CartValidationError("Product is not purchasable.")
        if quantity > inventory.max_per_order:
            raise CartValidationError("Requested quantity exceeds the inventory max per order.")

        resolved_price = self._inventory_service.resolve_member_unit_price_minor(
            product=product,
            currency=cart.currency,
            is_subscriber=self._is_subscriber(cart.user_id),
        )
        unit_price_minor = resolved_price.unit_price_minor
        now = datetime.now(timezone.utc)
        resolved_plan_id = (
            source_saved_plan_id
            if source_saved_plan_id is not None
            else (existing_item.source_saved_plan_id if existing_item is not None else None)
        )
        resolved_meal_ids = (
            list(source_meal_ids)
            if source_meal_ids is not None
            else (list(existing_item.source_meal_ids) if existing_item is not None else [])
        )
        return {
            "id": existing_item.id if existing_item is not None else f"cart-item-{product_id}",
            "product_id": product_id,
            "category_id": product.category_id,
            "product_name": product.product,
            "img_url": product.img_url,
            "quantity": quantity,
            "unit_label": inventory.unit_label,
            "unit_weight_grams": inventory.unit_weight_grams,
            "observed_unit_price_minor": (
                (existing_item.observed_unit_price_minor if existing_item is not None else 0) or unit_price_minor
            ),
            "current_unit_price_minor": unit_price_minor,
            "base_price_minor": resolved_price.base_price_minor,
            "discount_percent_applied": resolved_price.discount_percent_applied,
            "currency": cart.currency,
            "allow_substitutions": allow_substitutions,
            "substitution_note": substitution_note,
            "pricing_state": CartItemPricingState.CURRENT.value,
            "created_at": existing_item.created_at if existing_item is not None else now,
            "updated_at": now,
            "source_saved_plan_id": resolved_plan_id,
            "source_meal_ids": resolved_meal_ids,
        }

    def _is_subscriber(self, user_id: str) -> bool:
        account = self._subscription_account_repository.get_by_user_id(user_id=user_id)
        return account is not None and account.is_premium

    @staticmethod
    def _estimate_pack_quantity(*, required_quantity: float, unit: str, product_id: str) -> int:
        # buy_items express demand in ingredient-measure units (e.g. grams of rice), while
        # a cart line item is a whole-pack count. There's no per-product pack-weight lookup
        # wired to this bridge yet, so this rounds up to a purchasable whole-pack count
        # rather than attempting a weight-accurate conversion — intentionally approximate,
        # not a silent bug: a shopper substitutes/adjusts quantities before checkout anyway.
        del product_id  # reserved for a future pack-weight-aware conversion
        normalized_unit = unit.strip().lower()
        if normalized_unit in {"pcs", "piece", "pieces", "unit", "units"}:
            return max(1, math.ceil(required_quantity))
        if normalized_unit in {"kg", "kilogram", "kilograms"}:
            return max(1, math.ceil(required_quantity))
        if normalized_unit in {"l", "litre", "litres", "liter", "liters"}:
            return max(1, math.ceil(required_quantity))
        # Grams/millilitres/unrecognized units: treat sub-1000 demand as a single pack.
        return max(1, math.ceil(required_quantity / 1000)) if required_quantity > 1000 else 1

    def update_item_quantity(
        self,
        *,
        current_user: User,
        item_id: str,
        payload: CartItemQuantityUpdateRequest,
    ) -> CartResponse:
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=self._default_currency,
        )
        found = False
        items = []
        for item in cart.items:
            if item.id == item_id:
                found = True
                items.append(
                    {
                        **self._item_to_document(item),
                        "quantity": payload.quantity,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            else:
                items.append(self._item_to_document(item))
        if not found:
            raise CartItemNotFoundError
        saved = self._cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return self._to_response(self._reprice_cart(cart=saved))

    def remove_item(self, *, current_user: User, item_id: str) -> CartResponse:
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=self._default_currency,
        )
        items = [self._item_to_document(item) for item in cart.items if item.id != item_id]
        if len(items) == len(cart.items):
            raise CartItemNotFoundError
        saved = self._cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return self._to_response(self._reprice_cart(cart=saved))

    def select_address(self, *, current_user: User, payload: CartSelectAddressRequest) -> CartResponse:
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=self._default_currency,
        )
        if payload.address_id is not None:
            address = self._address_repository.get_for_user(user_id=current_user.id, address_id=payload.address_id)
            if address is None:
                raise CartValidationError("Address not found.")
        updated = self._cart_repository.set_selected_address(cart_id=cart.id, address_id=payload.address_id)
        return self._to_response(self._reprice_cart(cart=updated))

    def validate_cart(self, *, current_user: User, currency: str | None = None) -> CartValidateResponse:
        cart = self._cart_repository.ensure_active_cart(
            user_id=current_user.id,
            store_id=self._default_store_id,
            currency=currency or self._default_currency,
        )
        repriced = self._reprice_cart(cart=cart)
        issues: list[CartValidationIssueResponse] = []
        for item in repriced.items:
            if item.pricing_state == CartItemPricingState.UNAVAILABLE:
                issues.append(
                    CartValidationIssueResponse(
                        product_id=item.product_id,
                        code="unavailable",
                        message="Product is no longer available in the requested quantity.",
                    )
                )
            elif item.pricing_state == CartItemPricingState.PRICE_CHANGED:
                issues.append(
                    CartValidationIssueResponse(
                        product_id=item.product_id,
                        code="price_changed",
                        message="Product price changed since it was added to cart.",
                    )
                )
        return CartValidateResponse(
            cart=self._to_response(repriced),
            valid=not issues,
            issues=issues,
        )

    def _reprice_cart(self, *, cart: Cart) -> Cart:
        now = datetime.now(timezone.utc)
        is_subscriber = self._is_subscriber(cart.user_id)
        items = []
        total_weight = 0
        subtotal_minor = 0
        for item in cart.items:
            product = self._grocery_repository.get_product(item.product_id)
            inventory = self._inventory_service.ensure_sellable_inventory_item(
                product_id=item.product_id,
                store_id=cart.store_id,
            )
            if product is None or inventory is None or not inventory.is_active or inventory.available_quantity < item.quantity:
                pricing_state = CartItemPricingState.UNAVAILABLE
                current_unit_price_minor = item.current_unit_price_minor
                base_price_minor = item.base_price_minor
                discount_percent_applied = item.discount_percent_applied
            else:
                resolved_price = self._inventory_service.resolve_member_unit_price_minor(
                    product=product,
                    currency=cart.currency,
                    is_subscriber=is_subscriber,
                )
                current_unit_price_minor = resolved_price.unit_price_minor
                base_price_minor = resolved_price.base_price_minor
                discount_percent_applied = resolved_price.discount_percent_applied
                pricing_state = (
                    CartItemPricingState.PRICE_CHANGED
                    if current_unit_price_minor != item.observed_unit_price_minor
                    else CartItemPricingState.CURRENT
                )
                total_weight += inventory.unit_weight_grams * item.quantity
                subtotal_minor += current_unit_price_minor * item.quantity
            items.append(
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "category_id": product.category_id if product is not None else item.category_id,
                    "product_name": product.product if product is not None else item.product_name,
                    "img_url": product.img_url if product is not None else item.img_url,
                    "quantity": item.quantity,
                    "unit_label": inventory.unit_label if inventory is not None else item.unit_label,
                    "unit_weight_grams": inventory.unit_weight_grams if inventory is not None else item.unit_weight_grams,
                    "observed_unit_price_minor": item.observed_unit_price_minor,
                    "current_unit_price_minor": current_unit_price_minor,
                    "base_price_minor": base_price_minor,
                    "discount_percent_applied": discount_percent_applied,
                    "currency": cart.currency,
                    "allow_substitutions": item.allow_substitutions if inventory is None else inventory.allow_substitutions and item.allow_substitutions,
                    "substitution_note": item.substitution_note,
                    "pricing_state": pricing_state.value,
                    "created_at": item.created_at,
                    "updated_at": now,
                    "source_saved_plan_id": item.source_saved_plan_id,
                    "source_meal_ids": list(item.source_meal_ids),
                }
            )
        base_delivery_fee_minor = self._inventory_service.resolve_weight_based_delivery_fee(
            total_weight_grams=total_weight,
            currency=cart.currency,
            store_id=cart.store_id,
        )
        free_delivery_unlocked = (
            self._free_delivery_subtotal_minor > 0 and subtotal_minor >= self._free_delivery_subtotal_minor
        )
        delivery_fee_minor = 0 if free_delivery_unlocked else base_delivery_fee_minor
        pricing_snapshot = {
            "currency": cart.currency,
            "subtotal_minor": subtotal_minor,
            "delivery_fee_minor": delivery_fee_minor,
            "service_fee_minor": 0,
            "total_minor": subtotal_minor + delivery_fee_minor,
            "total_weight_grams": total_weight,
            "line_item_count": len(items),
            "free_delivery_threshold_minor": self._free_delivery_subtotal_minor,
            "free_delivery_remaining_minor": (
                max(self._free_delivery_subtotal_minor - subtotal_minor, 0)
                if self._free_delivery_subtotal_minor > 0
                else 0
            ),
            "free_delivery_unlocked": free_delivery_unlocked,
        }
        return self._cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=pricing_snapshot,
            last_priced_at=now,
            expires_at=self._expires_at(),
            status=cart.status,
        )

    def _to_response(self, cart: Cart) -> CartResponse:
        snapshot = dict(cart.pricing_snapshot or {})
        return CartResponse(
            id=cart.id,
            status=cart.status,
            currency=cart.currency,
            store_id=cart.store_id,
            items=[
                CartItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    category_id=item.category_id,
                    product_name=item.product_name,
                    img_url=item.img_url,
                    quantity=item.quantity,
                    unit_label=item.unit_label,
                    unit_weight_grams=item.unit_weight_grams,
                    observed_unit_price_minor=item.observed_unit_price_minor,
                    current_unit_price_minor=item.current_unit_price_minor,
                    base_price_minor=item.base_price_minor,
                    discount_percent_applied=item.discount_percent_applied,
                    currency=item.currency,
                    allow_substitutions=item.allow_substitutions,
                    substitution_note=item.substitution_note,
                    pricing_state=item.pricing_state,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    source_saved_plan_id=item.source_saved_plan_id,
                    source_meal_ids=list(item.source_meal_ids),
                )
                for item in cart.items
            ],
            selected_address_id=cart.selected_address_id,
            summary=CartSummaryResponse(
                currency=str(snapshot.get("currency") or cart.currency),
                subtotal_minor=int(snapshot.get("subtotal_minor") or 0),
                delivery_fee_minor=int(snapshot.get("delivery_fee_minor") or 0),
                service_fee_minor=int(snapshot.get("service_fee_minor") or 0),
                total_minor=int(snapshot.get("total_minor") or 0),
                total_weight_grams=int(snapshot.get("total_weight_grams") or 0),
                line_item_count=int(snapshot.get("line_item_count") or len(cart.items)),
                free_delivery_threshold_minor=int(snapshot.get("free_delivery_threshold_minor") or 0),
                free_delivery_remaining_minor=int(snapshot.get("free_delivery_remaining_minor") or 0),
                free_delivery_unlocked=bool(snapshot.get("free_delivery_unlocked", False)),
            ),
            last_priced_at=cart.last_priced_at,
            expires_at=cart.expires_at,
            updated_at=cart.updated_at,
        )

    def _expires_at(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self._cart_ttl_seconds)

    @staticmethod
    def _item_to_document(item) -> dict[str, object]:
        return {
            "id": item.id,
            "product_id": item.product_id,
            "category_id": item.category_id,
            "product_name": item.product_name,
            "img_url": item.img_url,
            "quantity": item.quantity,
            "unit_label": item.unit_label,
            "unit_weight_grams": item.unit_weight_grams,
            "observed_unit_price_minor": item.observed_unit_price_minor,
            "current_unit_price_minor": item.current_unit_price_minor,
            "base_price_minor": item.base_price_minor,
            "discount_percent_applied": item.discount_percent_applied,
            "currency": item.currency,
            "allow_substitutions": item.allow_substitutions,
            "substitution_note": item.substitution_note,
            "pricing_state": item.pricing_state.value,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "source_saved_plan_id": item.source_saved_plan_id,
            "source_meal_ids": list(item.source_meal_ids),
        }
