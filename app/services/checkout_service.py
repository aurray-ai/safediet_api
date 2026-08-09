from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.models.billing import ChargeType, CheckoutPaymentMethod, CheckoutRoute
from app.models.cart import CartItemPricingState, CartStatus
from app.models.inventory import InventoryAdjustmentType
from app.models.order import OrderStatus, PaymentAttemptStatus
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.repositories.cart_repository import CartRepository
from app.repositories.checkout_quote_repository import CheckoutQuoteRepository
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_attempt_repository import PaymentAttemptRepository
from app.schemas.checkout import (
    CheckoutConfirmRequest,
    CheckoutConfirmResponse,
    DeliveryWindowResponse,
    CheckoutPaymentActionResponse,
    CheckoutPriceAdjustmentResponse,
    CheckoutQuoteItemResponse,
    CheckoutQuoteRequest,
    CheckoutQuoteResponse,
)
from app.services.billing_service import BillingService, CheckoutEvaluationInput
from app.services.cart_service import CartService
from app.services.delivery_window_service import (
    DeliveryWindowOption,
    DeliveryWindowService,
    DeliveryWindowSpec,
)
from app.services.inventory_service import InventoryService
from app.services.stripe_billing_gateway import StripeBillingGateway


class CheckoutError(Exception):
    pass


class CheckoutService:
    _DELIVERY_WINDOW_SPECS: list[DeliveryWindowSpec] = [
        DeliveryWindowSpec(
            window_id="today-14-16",
            label_prefix="Today",
            start_hour=14,
            end_hour=16,
            day_offset=0,
            is_default=True,
        ),
        DeliveryWindowSpec(
            window_id="today-18-20",
            label_prefix="Today",
            start_hour=18,
            end_hour=20,
            day_offset=0,
        ),
        DeliveryWindowSpec(
            window_id="tomorrow-09-11",
            label_prefix="Tomorrow",
            start_hour=9,
            end_hour=11,
            day_offset=1,
        ),
    ]

    def __init__(
        self,
        *,
        cart_service: CartService,
        cart_repository: CartRepository,
        checkout_quote_repository: CheckoutQuoteRepository,
        order_repository: OrderRepository,
        payment_attempt_repository: PaymentAttemptRepository,
        grocery_repository: GroceryRepository,
        inventory_repository: InventoryRepository,
        address_repository: AddressRepository,
        inventory_service: InventoryService,
        billing_service: BillingService,
        stripe_gateway: StripeBillingGateway,
        delivery_window_service: DeliveryWindowService,
        default_store_id: str,
        default_currency: str,
        free_delivery_subtotal_minor: int,
        delivery_timezone_name: str,
        quote_ttl_seconds: int,
        cancellation_window_minutes: int,
    ) -> None:
        self._cart_service = cart_service
        self._cart_repository = cart_repository
        self._checkout_quote_repository = checkout_quote_repository
        self._order_repository = order_repository
        self._payment_attempt_repository = payment_attempt_repository
        self._grocery_repository = grocery_repository
        self._inventory_repository = inventory_repository
        self._address_repository = address_repository
        self._inventory_service = inventory_service
        self._billing_service = billing_service
        self._stripe_gateway = stripe_gateway
        self._delivery_window_service = delivery_window_service
        self._default_store_id = default_store_id
        self._default_currency = default_currency
        self._free_delivery_subtotal_minor = max(0, int(free_delivery_subtotal_minor))
        self._delivery_timezone_name = delivery_timezone_name
        self._quote_ttl_seconds = quote_ttl_seconds
        self._cancellation_window_minutes = cancellation_window_minutes

    def create_quote(self, *, current_user: User, payload: CheckoutQuoteRequest) -> CheckoutQuoteResponse:
        if payload.address_id is not None:
            address = self._address_repository.get_for_user(user_id=current_user.id, address_id=payload.address_id)
        else:
            address = None
        cart_validation = self._cart_service.validate_cart(current_user=current_user, currency=payload.currency)
        cart = cart_validation.cart
        selected_address_id = payload.address_id or cart.selected_address_id
        if selected_address_id is None:
            raise CheckoutError("A delivery address is required.")
        if address is None:
            address = self._address_repository.get_for_user(user_id=current_user.id, address_id=selected_address_id)
        if address is None:
            raise CheckoutError("Selected delivery address was not found.")
        delivery_windows = self._build_delivery_windows()
        selected_delivery_window = next(
            (
                item
                for item in delivery_windows
                if item.window_id == (payload.delivery_window_id or delivery_windows[0].window_id)
            ),
            None,
        )
        if selected_delivery_window is None:
            raise CheckoutError("Selected delivery window was not found.")
        price_adjustments = [
            CheckoutPriceAdjustmentResponse(
                product_id=item.product_id,
                previous_unit_price_minor=item.observed_unit_price_minor,
                current_unit_price_minor=item.current_unit_price_minor,
            )
            for item in cart.items
            if item.pricing_state == CartItemPricingState.PRICE_CHANGED
        ]
        unavailable_product_ids = [
            item.product_id
            for item in cart.items
            if item.pricing_state == CartItemPricingState.UNAVAILABLE
        ]

        summary = cart.summary
        evaluation = self._billing_service.evaluate_checkout(
            current_user=current_user,
            payload=CheckoutEvaluationInput(
                charge_type=ChargeType.GROCERY_ORDER,
                amount_minor=summary.total_minor,
                currency=cart.currency,
                reference_type="grocery_cart",
                reference_id=cart.id,
                metadata={},
            ),
        )
        wallet_available_minor = evaluation.wallet_available_minor
        wallet_contribution_minor = min(summary.total_minor, wallet_available_minor)
        card_contribution_minor = max(summary.total_minor - wallet_contribution_minor, 0)
        route = evaluation.route
        quote_status = "ready" if not unavailable_product_ids else "requires_review"
        message = (
            "Checkout quote created."
            if not unavailable_product_ids
            else "Some items became unavailable and require review."
        )
        document = self._checkout_quote_repository.create_quote(
            user_id=current_user.id,
            cart_id=cart.id,
            store_id=cart.store_id,
            currency=cart.currency,
            quote_status=quote_status,
            line_items=[item.model_dump() for item in cart.items],
            pricing_summary=summary.model_dump(),
            wallet_contribution_minor=wallet_contribution_minor,
            card_contribution_minor=card_contribution_minor,
            address_snapshot={
                "id": address.id,
                "label": address.label,
                "recipient_name": address.recipient_name,
                "phone_number": address.phone_number,
                "line1": address.line1,
                "line2": address.line2,
                "city": address.city,
                "state": address.state,
                "postal_code": address.postal_code,
                "country": address.country,
                "delivery_notes": address.delivery_notes,
            },
            delivery_window_snapshot={
                "id": selected_delivery_window.window_id,
                "label": selected_delivery_window.label,
                "starts_at": selected_delivery_window.starts_at,
                "ends_at": selected_delivery_window.ends_at,
            },
            route=route.value,
            message=message,
            ttl_seconds=self._quote_ttl_seconds,
        )
        return CheckoutQuoteResponse(
            quote_id=str(document["_id"]),
            cart_id=str(document["cart_id"]),
            currency=cart.currency,
            route=route,
            wallet_available_minor=wallet_available_minor,
            wallet_contribution_minor=wallet_contribution_minor,
            card_contribution_minor=card_contribution_minor,
            subtotal_minor=summary.subtotal_minor,
            delivery_fee_minor=summary.delivery_fee_minor,
            service_fee_minor=summary.service_fee_minor,
            total_minor=summary.total_minor,
            total_weight_grams=summary.total_weight_grams,
            free_delivery_threshold_minor=summary.free_delivery_threshold_minor,
            free_delivery_remaining_minor=summary.free_delivery_remaining_minor,
            free_delivery_unlocked=summary.free_delivery_unlocked,
            items=[
                self._to_quote_item_response(store_id=cart.store_id, item=item)
                for item in cart.items
            ],
            price_adjustments=price_adjustments,
            unavailable_product_ids=unavailable_product_ids,
            selected_delivery_window=self._to_delivery_window_response(selected_delivery_window),
            available_delivery_windows=[self._to_delivery_window_response(item) for item in delivery_windows],
            expires_at=document["expires_at"],
            message=message,
        )

    def confirm_checkout(self, *, current_user: User, payload: CheckoutConfirmRequest) -> CheckoutConfirmResponse:
        existing_attempt = self._payment_attempt_repository.get_by_idempotency_key(idempotency_key=payload.idempotency_key)
        if existing_attempt is not None:
            order = self._order_repository.get_order(order_id=existing_attempt.order_id)
            if order is None:
                raise CheckoutError("Existing payment attempt references a missing order.")
            return self._to_confirm_response(order=order, attempt=existing_attempt)

        quote = self._checkout_quote_repository.get_quote_for_user(user_id=current_user.id, quote_id=payload.quote_id)
        if quote is None:
            raise CheckoutError("Checkout quote not found.")
        if quote["expires_at"] < datetime.now(timezone.utc):
            raise CheckoutError("Checkout quote expired.")
        if str(quote.get("quote_status") or "") != "ready":
            raise CheckoutError("Checkout quote requires review before confirmation.")

        cart = self._cart_repository.get_active_cart(user_id=current_user.id)
        if cart is None:
            raise CheckoutError("Active cart not found.")

        pricing_summary = dict(quote.get("pricing_summary") or {})
        order_pricing_summary = {
            "currency": str(pricing_summary.get("currency") or self._default_currency),
            "subtotal_minor": int(pricing_summary.get("subtotal_minor") or 0),
            "delivery_fee_minor": int(pricing_summary.get("delivery_fee_minor") or 0),
            "service_fee_minor": int(pricing_summary.get("service_fee_minor") or 0),
            "total_minor": int(pricing_summary.get("total_minor") or 0),
            "total_weight_grams": int(pricing_summary.get("total_weight_grams") or 0),
        }
        total_minor = int(pricing_summary.get("total_minor") or 0)
        wallet_contribution_minor = int(quote.get("wallet_contribution_minor") or 0)
        card_contribution_minor = int(quote.get("card_contribution_minor") or 0)
        if payload.payment_method is not None:
            wallet_contribution_minor, card_contribution_minor = self._resolve_payment_split(
                current_user=current_user,
                cart_id=cart.id,
                currency=str(quote.get("currency") or self._default_currency),
                total_minor=total_minor,
                payment_method=payload.payment_method,
            )
        line_items = list(quote.get("line_items") or [])
        source_plan_ids = {
            str(item["source_saved_plan_id"]) for item in line_items if item.get("source_saved_plan_id")
        }
        source_meal_ids: list[str] = []
        for item in line_items:
            for meal_id in list(item.get("source_meal_ids") or []):
                if str(meal_id) not in source_meal_ids:
                    source_meal_ids.append(str(meal_id))

        order = self._order_repository.create_order(
            order_number=self._new_order_number(),
            user_id=current_user.id,
            store_id=str(quote.get("store_id") or self._default_store_id),
            status=OrderStatus.PENDING_PAYMENT,
            currency=str(quote.get("currency") or self._default_currency),
            items=self._build_order_items(line_items),
            pricing_summary=order_pricing_summary,
            address_snapshot=dict(quote.get("address_snapshot") or {}),
            substitution_policy={"allow_substitutions": True},
            payment_summary={
                "currency": str(quote.get("currency") or self._default_currency),
                "wallet_amount_minor": wallet_contribution_minor,
                "card_amount_minor": card_contribution_minor,
                "total_paid_minor": total_minor,
                "provider": "stripe" if card_contribution_minor > 0 else "wallet",
                "provider_payment_intent_id": None,
            },
            cancellation_window_expires_at=datetime.now(timezone.utc) + timedelta(minutes=self._cancellation_window_minutes),
            status_history=[
                {
                    "status": OrderStatus.PENDING_PAYMENT.value,
                    "note": "Order created.",
                    "actor_user_id": current_user.id,
                    "created_at": datetime.now(timezone.utc),
                }
            ],
            metadata={
                "quote_id": str(quote["_id"]),
                "cart_id": str(quote.get("cart_id") or cart.id),
                "delivery_window_id": str(dict(quote.get("delivery_window_snapshot") or {}).get("id") or ""),
                "payment_method": (
                    payload.payment_method.value
                    if payload.payment_method is not None
                    else None
                ),
                "source_saved_plan_id": next(iter(source_plan_ids)) if len(source_plan_ids) == 1 else None,
                "source_meal_ids": source_meal_ids,
            },
        )

        if wallet_contribution_minor > 0:
            self._billing_service.place_wallet_hold(
                user_id=current_user.id,
                amount_minor=wallet_contribution_minor,
                currency=order.currency,
                reference_type="grocery_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )

        if card_contribution_minor > 0:
            result = self._stripe_gateway.create_grocery_payment_intent(
                user_id=current_user.id,
                order_id=order.id,
                amount_minor=card_contribution_minor,
                currency=order.currency,
                idempotency_key=payload.idempotency_key,
                metadata={
                    "purpose": "grocery_order",
                    "order_id": order.id,
                    "user_id": current_user.id,
                    "wallet_hold_amount_minor": wallet_contribution_minor,
                },
            )
            attempt = self._payment_attempt_repository.create_attempt(
                order_id=order.id,
                user_id=current_user.id,
                quote_id=str(quote["_id"]),
                status=PaymentAttemptStatus.REQUIRES_ACTION,
                currency=order.currency,
                wallet_hold_amount_minor=wallet_contribution_minor,
                wallet_capture_amount_minor=wallet_contribution_minor,
                card_amount_minor=card_contribution_minor,
                provider="stripe",
                provider_payment_intent_id=result.payment_intent_id,
                client_secret=result.client_secret,
                idempotency_key=payload.idempotency_key,
                provider_payload={"status": result.status},
            )
            self._order_repository.update_payment_summary(
                order_id=order.id,
                payment_summary={
                    "currency": order.currency,
                    "wallet_amount_minor": wallet_contribution_minor,
                    "card_amount_minor": card_contribution_minor,
                    "total_paid_minor": total_minor,
                    "provider": "stripe",
                    "provider_payment_intent_id": result.payment_intent_id,
                },
            )
            self._order_repository.update_status(
                order_id=order.id,
                status=OrderStatus.PAYMENT_PROCESSING,
                note="Awaiting Stripe payment confirmation.",
                actor_user_id=current_user.id,
            )
            return self._to_confirm_response(order=self._order_repository.get_order(order_id=order.id) or order, attempt=attempt)

        attempt = self._payment_attempt_repository.create_attempt(
            order_id=order.id,
            user_id=current_user.id,
            quote_id=str(quote["_id"]),
            status=PaymentAttemptStatus.SUCCEEDED,
            currency=order.currency,
            wallet_hold_amount_minor=wallet_contribution_minor,
            wallet_capture_amount_minor=wallet_contribution_minor,
            card_amount_minor=0,
            provider="wallet",
            provider_payment_intent_id=None,
            client_secret=None,
            idempotency_key=payload.idempotency_key,
            provider_payload={"status": "succeeded"},
        )
        if wallet_contribution_minor > 0:
            self._billing_service.capture_wallet_hold(
                user_id=current_user.id,
                amount_minor=wallet_contribution_minor,
                currency=order.currency,
                reference_type="grocery_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._finalize_successful_payment(order_id=order.id, attempt=attempt)
        finalized_order = self._order_repository.get_order(order_id=order.id)
        if finalized_order is None:
            raise CheckoutError("Order was not found after finalization.")
        return self._to_confirm_response(order=finalized_order, attempt=attempt)

    def _resolve_payment_split(
        self,
        *,
        current_user: User,
        cart_id: str,
        currency: str,
        total_minor: int,
        payment_method: CheckoutPaymentMethod,
    ) -> tuple[int, int]:
        if payment_method == CheckoutPaymentMethod.CARD:
            return 0, total_minor

        if payment_method == CheckoutPaymentMethod.WALLET:
            evaluation = self._billing_service.evaluate_checkout(
                current_user=current_user,
                payload=CheckoutEvaluationInput(
                    charge_type=ChargeType.GROCERY_ORDER,
                    amount_minor=total_minor,
                    currency=currency,
                    reference_type="grocery_cart",
                    reference_id=cart_id,
                    metadata={},
                ),
            )
            if evaluation.wallet_available_minor < total_minor:
                raise CheckoutError("Wallet balance is insufficient for this payment method.")
            return total_minor, 0

        raise CheckoutError("Selected payment method is not available yet.")

    def handle_payment_intent_succeeded(self, *, event_object: dict[str, Any]) -> None:
        metadata = dict(event_object.get("metadata") or {})
        if str(metadata.get("purpose") or "") != "grocery_order":
            return
        payment_intent_id = str(event_object.get("id") or "")
        if not payment_intent_id:
            raise CheckoutError("Missing Stripe payment intent id.")
        attempt = self._payment_attempt_repository.get_by_provider_payment_intent_id(
            provider="stripe",
            provider_payment_intent_id=payment_intent_id,
        )
        if attempt is None or attempt.status == PaymentAttemptStatus.SUCCEEDED:
            return
        self._payment_attempt_repository.mark_status(
            attempt_id=attempt.id,
            status=PaymentAttemptStatus.SUCCEEDED,
            provider_payload=event_object,
        )
        order = self._order_repository.get_order(order_id=attempt.order_id)
        if order is None:
            raise CheckoutError("Order not found for payment attempt.")
        if attempt.wallet_capture_amount_minor > 0:
            self._billing_service.capture_wallet_hold(
                user_id=order.user_id,
                amount_minor=attempt.wallet_capture_amount_minor,
                currency=attempt.currency,
                reference_type="grocery_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._finalize_successful_payment(order_id=order.id, attempt=attempt)

    def handle_payment_intent_failed(self, *, event_object: dict[str, Any]) -> None:
        metadata = dict(event_object.get("metadata") or {})
        if str(metadata.get("purpose") or "") != "grocery_order":
            return
        payment_intent_id = str(event_object.get("id") or "")
        attempt = self._payment_attempt_repository.get_by_provider_payment_intent_id(
            provider="stripe",
            provider_payment_intent_id=payment_intent_id,
        )
        if attempt is None or attempt.status == PaymentAttemptStatus.FAILED:
            return
        self._payment_attempt_repository.mark_status(
            attempt_id=attempt.id,
            status=PaymentAttemptStatus.FAILED,
            provider_payload=event_object,
        )
        order = self._order_repository.get_order(order_id=attempt.order_id)
        if order is None:
            return
        if attempt.wallet_hold_amount_minor > 0:
            self._billing_service.release_wallet_hold(
                user_id=order.user_id,
                amount_minor=attempt.wallet_hold_amount_minor,
                currency=attempt.currency,
                reference_type="grocery_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.PAYMENT_FAILED,
            note="Stripe payment failed.",
            actor_user_id=None,
        )

    def _finalize_successful_payment(self, *, order_id: str, attempt) -> None:
        order = self._order_repository.get_order(order_id=order_id)
        if order is None:
            raise CheckoutError("Order not found.")
        if order.status == OrderStatus.CONFIRMED:
            return
        for item in order.items:
            self._inventory_repository.decrement_available(
                store_id=order.store_id,
                product_id=item.product_id,
                quantity=item.quantity,
            )
            inventory_item = self._inventory_repository.get_by_product_id(
                store_id=order.store_id,
                product_id=item.product_id,
            )
            if inventory_item is not None:
                self._inventory_repository.apply_adjustment(
                    inventory_item_id=inventory_item.id,
                    product_id=item.product_id,
                    store_id=order.store_id,
                    adjustment_type=InventoryAdjustmentType.ORDER_CAPTURE,
                    delta_quantity=-item.quantity,
                    reason="Order captured.",
                    actor_user_id=order.user_id,
                    reference_type="grocery_order",
                    reference_id=order.id,
                    metadata={"order_id": order.id},
                )
        cart_id = str((order.metadata or {}).get("cart_id") or "")
        if cart_id:
            self._cart_repository.mark_converted(cart_id=cart_id)
        self._order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.CONFIRMED,
            note="Payment succeeded and inventory captured.",
            actor_user_id=order.user_id,
        )

    @staticmethod
    def _build_order_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": str(item.get("id") or f"order-item-{index + 1}"),
                "product_id": str(item.get("product_id") or ""),
                "category_id": str(item.get("category_id") or ""),
                "product_name": str(item.get("product_name") or ""),
                "img_url": str(item.get("img_url") or ""),
                "quantity": int(item.get("quantity") or 0),
                "unit_label": str(item.get("unit_label") or ""),
                "unit_weight_grams": int(item.get("unit_weight_grams") or 0),
                "unit_price_minor": int(item.get("current_unit_price_minor") or 0),
                "line_total_minor": int(item.get("current_unit_price_minor") or 0) * int(item.get("quantity") or 0),
                "base_price_minor": int(item.get("base_price_minor") or item.get("current_unit_price_minor") or 0),
                "discount_percent_applied": float(item.get("discount_percent_applied") or 0.0),
                "currency": str(item.get("currency") or "GBP"),
                "allow_substitutions": bool(item.get("allow_substitutions", True)),
                "substitution_resolution": "none",
                "substituted_product_id": None,
                # A cart line can aggregate the same shared ingredient across several
                # planned meals (source_meal_ids); the order snapshot only needs one
                # breadcrumb per line, so take the first — full multi-meal detail is
                # still recoverable via metadata["source_saved_plan_id"] on the order.
                "source_meal_id": (
                    str(list(item.get("source_meal_ids") or [])[0])
                    if item.get("source_meal_ids")
                    else None
                ),
            }
            for index, item in enumerate(items)
        ]

    @staticmethod
    def _new_order_number() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"GSO-{timestamp}-{uuid4().hex[:6].upper()}"

    def _to_quote_item_response(self, *, store_id: str, item) -> CheckoutQuoteItemResponse:
        inventory = self._inventory_repository.get_by_product_id(store_id=store_id, product_id=item.product_id)
        return CheckoutQuoteItemResponse(
            product_id=item.product_id,
            category_id=item.category_id,
            product_name=item.product_name,
            img_url=item.img_url,
            quantity=item.quantity,
            unit_price_minor=item.current_unit_price_minor,
            line_total_minor=item.current_unit_price_minor * item.quantity,
            available_quantity=inventory.available_quantity if inventory is not None else 0,
            pricing_changed=item.pricing_state == CartItemPricingState.PRICE_CHANGED,
            unavailable=item.pricing_state == CartItemPricingState.UNAVAILABLE,
        )

    @staticmethod
    def _to_delivery_window_response(item: DeliveryWindowOption) -> DeliveryWindowResponse:
        return DeliveryWindowResponse(
            id=item.window_id,
            label=item.label,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            is_default=item.is_default,
        )

    def _build_delivery_windows(self) -> list[DeliveryWindowOption]:
        return self._delivery_window_service.build_windows(
            timezone_name=self._delivery_timezone_name,
            specs=self._DELIVERY_WINDOW_SPECS,
        )

    def _to_confirm_response(self, *, order, attempt) -> CheckoutConfirmResponse:
        requires_payment_action = attempt.card_amount_minor > 0 and attempt.status == PaymentAttemptStatus.REQUIRES_ACTION
        return CheckoutConfirmResponse(
            order_id=order.id,
            order_number=order.order_number,
            status=order.status.value,
            requires_payment_action=requires_payment_action,
            payment_action=(
                CheckoutPaymentActionResponse(
                    provider=attempt.provider,
                    payment_intent_id=attempt.provider_payment_intent_id,
                    client_secret=attempt.client_secret,
                    publishable_key=self._stripe_gateway.publishable_key,
                )
                if requires_payment_action
                else None
            ),
            message=(
                "Checkout confirmed. Complete the card payment to finish the order."
                if requires_payment_action
                else "Order confirmed."
            ),
        )
