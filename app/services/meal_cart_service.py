from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.cart import CartItemPricingState, CartStatus
from app.models.meal_cart import MealCart
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.repositories.meal_cart_repository import MealCartRepository
from app.repositories.meal_repository import MealRepository
from app.services.meal_pricing import resolve_meal_unit_price_minor
from app.schemas.meal_cart import (
    MealCartItemQuantityUpdateRequest,
    MealCartItemResponse,
    MealCartItemUpsertRequest,
    MealCartResponse,
    MealCartSelectAddressRequest,
    MealCartSummaryResponse,
    MealCartValidateResponse,
    MealCartValidationIssueResponse,
)


class MealCartItemNotFoundError(Exception):
    pass


class MealCartValidationError(Exception):
    pass


class MealCartService:
    def __init__(
        self,
        *,
        meal_cart_repository: MealCartRepository,
        meal_repository: MealRepository,
        address_repository: AddressRepository,
        default_currency: str,
        cart_ttl_seconds: int,
        max_servings_per_line: int,
    ) -> None:
        self._meal_cart_repository = meal_cart_repository
        self._meal_repository = meal_repository
        self._address_repository = address_repository
        self._default_currency = default_currency
        self._cart_ttl_seconds = cart_ttl_seconds
        self._max_servings_per_line = max_servings_per_line

    def get_cart(self, *, current_user: User, currency: str | None = None) -> MealCartResponse:
        cart = self._meal_cart_repository.ensure_active_cart(
            user_id=current_user.id,
            currency=currency or self._default_currency,
        )
        return self._to_response(self._reprice_cart(cart=cart))

    def upsert_item(self, *, current_user: User, payload: MealCartItemUpsertRequest) -> MealCartResponse:
        if payload.servings > self._max_servings_per_line:
            raise MealCartValidationError("Requested servings exceed the cart limit.")
        cart = self._meal_cart_repository.ensure_active_cart(
            user_id=current_user.id,
            currency=self._default_currency,
        )
        meal = self._meal_repository.get_meal(payload.meal_id)
        if meal is None:
            raise MealCartValidationError("Meal not found.")

        unit_price_minor = resolve_meal_unit_price_minor(meal=meal, currency=cart.currency)
        now = datetime.now(timezone.utc)
        items = []
        replaced = False
        for item in cart.items:
            if item.meal_id == payload.meal_id:
                items.append(
                    {
                        "id": item.id,
                        "meal_id": payload.meal_id,
                        "meal_name": meal.name,
                        "img_url": meal.hero_image_url,
                        "servings": payload.servings,
                        "observed_unit_price_minor": item.observed_unit_price_minor or unit_price_minor,
                        "current_unit_price_minor": unit_price_minor,
                        "currency": cart.currency,
                        "pricing_state": CartItemPricingState.CURRENT.value,
                        "created_at": item.created_at,
                        "updated_at": now,
                    }
                )
                replaced = True
            else:
                items.append(self._item_to_document(item))
        if not replaced:
            items.append(
                {
                    "id": f"meal-cart-item-{payload.meal_id}",
                    "meal_id": payload.meal_id,
                    "meal_name": meal.name,
                    "img_url": meal.hero_image_url,
                    "servings": payload.servings,
                    "observed_unit_price_minor": unit_price_minor,
                    "current_unit_price_minor": unit_price_minor,
                    "currency": cart.currency,
                    "pricing_state": CartItemPricingState.CURRENT.value,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        saved = self._meal_cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return self._to_response(self._reprice_cart(cart=saved))

    def update_item_quantity(
        self,
        *,
        current_user: User,
        item_id: str,
        payload: MealCartItemQuantityUpdateRequest,
    ) -> MealCartResponse:
        cart = self._meal_cart_repository.ensure_active_cart(
            user_id=current_user.id,
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
                        "servings": payload.servings,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            else:
                items.append(self._item_to_document(item))
        if not found:
            raise MealCartItemNotFoundError
        saved = self._meal_cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return self._to_response(self._reprice_cart(cart=saved))

    def remove_item(self, *, current_user: User, item_id: str) -> MealCartResponse:
        cart = self._meal_cart_repository.ensure_active_cart(
            user_id=current_user.id,
            currency=self._default_currency,
        )
        items = [self._item_to_document(item) for item in cart.items if item.id != item_id]
        if len(items) == len(cart.items):
            raise MealCartItemNotFoundError
        saved = self._meal_cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=cart.pricing_snapshot,
            last_priced_at=cart.last_priced_at,
            expires_at=self._expires_at(),
            status=CartStatus.ACTIVE,
        )
        return self._to_response(self._reprice_cart(cart=saved))

    def select_address(self, *, current_user: User, payload: MealCartSelectAddressRequest) -> MealCartResponse:
        cart = self._meal_cart_repository.ensure_active_cart(
            user_id=current_user.id,
            currency=self._default_currency,
        )
        if payload.address_id is not None:
            address = self._address_repository.get_for_user(user_id=current_user.id, address_id=payload.address_id)
            if address is None:
                raise MealCartValidationError("Address not found.")
        updated = self._meal_cart_repository.set_selected_address(cart_id=cart.id, address_id=payload.address_id)
        return self._to_response(self._reprice_cart(cart=updated))

    def validate_cart(self, *, current_user: User, currency: str | None = None) -> MealCartValidateResponse:
        cart = self._meal_cart_repository.ensure_active_cart(
            user_id=current_user.id,
            currency=currency or self._default_currency,
        )
        repriced = self._reprice_cart(cart=cart)
        issues: list[MealCartValidationIssueResponse] = []
        for item in repriced.items:
            if item.pricing_state == CartItemPricingState.UNAVAILABLE:
                issues.append(
                    MealCartValidationIssueResponse(
                        meal_id=item.meal_id,
                        code="unavailable",
                        message="Meal is no longer available.",
                    )
                )
            elif item.pricing_state == CartItemPricingState.PRICE_CHANGED:
                issues.append(
                    MealCartValidationIssueResponse(
                        meal_id=item.meal_id,
                        code="price_changed",
                        message="Meal price changed since it was added to cart.",
                    )
                )
        return MealCartValidateResponse(
            cart=self._to_response(repriced),
            valid=not issues,
            issues=issues,
        )

    def _reprice_cart(self, *, cart: MealCart) -> MealCart:
        now = datetime.now(timezone.utc)
        items = []
        subtotal_minor = 0
        for item in cart.items:
            meal = self._meal_repository.get_meal(item.meal_id)
            if meal is None:
                pricing_state = CartItemPricingState.UNAVAILABLE
                current_unit_price_minor = item.current_unit_price_minor
            else:
                current_unit_price_minor = resolve_meal_unit_price_minor(meal=meal, currency=cart.currency)
                pricing_state = (
                    CartItemPricingState.PRICE_CHANGED
                    if current_unit_price_minor != item.observed_unit_price_minor
                    else CartItemPricingState.CURRENT
                )
                subtotal_minor += current_unit_price_minor * item.servings
            items.append(
                {
                    "id": item.id,
                    "meal_id": item.meal_id,
                    "meal_name": meal.name if meal is not None else item.meal_name,
                    "img_url": meal.hero_image_url if meal is not None else item.img_url,
                    "servings": item.servings,
                    "observed_unit_price_minor": item.observed_unit_price_minor,
                    "current_unit_price_minor": current_unit_price_minor,
                    "currency": cart.currency,
                    "pricing_state": pricing_state.value,
                    "created_at": item.created_at,
                    "updated_at": now,
                }
            )
        pricing_snapshot = {
            "currency": cart.currency,
            "subtotal_minor": subtotal_minor,
            "delivery_fee_minor": 0,
            "service_fee_minor": 0,
            "total_minor": subtotal_minor,
            "line_item_count": len(items),
        }
        return self._meal_cart_repository.save_cart(
            cart_id=cart.id,
            items=items,
            selected_address_id=cart.selected_address_id,
            pricing_snapshot=pricing_snapshot,
            last_priced_at=now,
            expires_at=self._expires_at(),
            status=cart.status,
        )

    def _to_response(self, cart: MealCart) -> MealCartResponse:
        snapshot = dict(cart.pricing_snapshot or {})
        return MealCartResponse(
            id=cart.id,
            status=cart.status,
            currency=cart.currency,
            items=[
                MealCartItemResponse(
                    id=item.id,
                    meal_id=item.meal_id,
                    meal_name=item.meal_name,
                    img_url=item.img_url,
                    servings=item.servings,
                    observed_unit_price_minor=item.observed_unit_price_minor,
                    current_unit_price_minor=item.current_unit_price_minor,
                    currency=item.currency,
                    pricing_state=item.pricing_state,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in cart.items
            ],
            selected_address_id=cart.selected_address_id,
            summary=MealCartSummaryResponse(
                currency=str(snapshot.get("currency") or cart.currency),
                subtotal_minor=int(snapshot.get("subtotal_minor") or 0),
                delivery_fee_minor=int(snapshot.get("delivery_fee_minor") or 0),
                service_fee_minor=int(snapshot.get("service_fee_minor") or 0),
                total_minor=int(snapshot.get("total_minor") or 0),
                line_item_count=int(snapshot.get("line_item_count") or len(cart.items)),
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
            "meal_id": item.meal_id,
            "meal_name": item.meal_name,
            "img_url": item.img_url,
            "servings": item.servings,
            "observed_unit_price_minor": item.observed_unit_price_minor,
            "current_unit_price_minor": item.current_unit_price_minor,
            "currency": item.currency,
            "pricing_state": item.pricing_state.value,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
