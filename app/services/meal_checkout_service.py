from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.billing import ChargeType, CheckoutPaymentMethod, CheckoutRoute
from app.models.cart import CartItemPricingState
from app.models.meal_order import MealDeliveryType
from app.models.order import OrderStatus, PaymentAttemptStatus
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.repositories.checkout_quote_repository import CheckoutQuoteRepository
from app.repositories.meal_cart_repository import MealCartRepository
from app.repositories.meal_order_repository import MealOrderRepository
from app.repositories.payment_attempt_repository import PaymentAttemptRepository
from app.schemas.meal_checkout import (
    MealCheckoutConfirmRequest,
    MealCheckoutConfirmResponse,
    MealCheckoutPaymentActionResponse,
    MealCheckoutPriceAdjustmentResponse,
    MealCheckoutQuoteItemResponse,
    MealCheckoutQuoteRequest,
    MealCheckoutQuoteResponse,
    MealDeliveryWindowResponse,
)
from app.services.billing_service import BillingService, CheckoutEvaluationInput
from app.services.delivery_window_service import (
    DeliveryWindowOption,
    DeliveryWindowService,
    DeliveryWindowSpec,
)
from app.services.meal_cart_service import MealCartService
from app.services.stripe_billing_gateway import StripeBillingGateway

_MEAL_STORE_ID = "meal_kitchen"


class MealCheckoutError(Exception):
    pass


class MealCheckoutService:
    _DELIVERY_WINDOW_SPECS: list[DeliveryWindowSpec] = [
        DeliveryWindowSpec(
            window_id="tomorrow-09-12",
            label_prefix="Tomorrow",
            start_hour=9,
            end_hour=12,
            day_offset=1,
            is_default=True,
        ),
        DeliveryWindowSpec(
            window_id="tomorrow-12-15",
            label_prefix="Tomorrow",
            start_hour=12,
            end_hour=15,
            day_offset=1,
        ),
        DeliveryWindowSpec(
            window_id="tomorrow-15-18",
            label_prefix="Tomorrow",
            start_hour=15,
            end_hour=18,
            day_offset=1,
        ),
        DeliveryWindowSpec(
            window_id="tomorrow-18-21",
            label_prefix="Tomorrow",
            start_hour=18,
            end_hour=21,
            day_offset=1,
        ),
    ]

    def __init__(
        self,
        *,
        meal_cart_service: MealCartService,
        meal_cart_repository: MealCartRepository,
        checkout_quote_repository: CheckoutQuoteRepository,
        meal_order_repository: MealOrderRepository,
        payment_attempt_repository: PaymentAttemptRepository,
        address_repository: AddressRepository,
        billing_service: BillingService,
        stripe_gateway: StripeBillingGateway,
        delivery_window_service: DeliveryWindowService,
        default_currency: str,
        delivery_timezone_name: str,
        express_delivery_fee_minor: int,
        quote_ttl_seconds: int,
        cancellation_window_minutes: int,
    ) -> None:
        self._meal_cart_service = meal_cart_service
        self._meal_cart_repository = meal_cart_repository
        self._checkout_quote_repository = checkout_quote_repository
        self._meal_order_repository = meal_order_repository
        self._payment_attempt_repository = payment_attempt_repository
        self._address_repository = address_repository
        self._billing_service = billing_service
        self._stripe_gateway = stripe_gateway
        self._delivery_window_service = delivery_window_service
        self._default_currency = default_currency
        self._delivery_timezone_name = delivery_timezone_name
        self._express_delivery_fee_minor = max(0, int(express_delivery_fee_minor))
        self._quote_ttl_seconds = quote_ttl_seconds
        self._cancellation_window_minutes = cancellation_window_minutes

    def create_quote(self, *, current_user: User, payload: MealCheckoutQuoteRequest) -> MealCheckoutQuoteResponse:
        if payload.address_id is not None:
            address = self._address_repository.get_for_user(user_id=current_user.id, address_id=payload.address_id)
        else:
            address = None
        cart_validation = self._meal_cart_service.validate_cart(current_user=current_user, currency=payload.currency)
        cart_response = cart_validation.cart
        selected_address_id = payload.address_id or cart_response.selected_address_id
        if selected_address_id is None:
            raise MealCheckoutError("A delivery address is required.")
        if address is None:
            address = self._address_repository.get_for_user(user_id=current_user.id, address_id=selected_address_id)
        if address is None:
            raise MealCheckoutError("Selected delivery address was not found.")

        cart = self._meal_cart_repository.get_active_cart(user_id=current_user.id)
        if cart is None:
            raise MealCheckoutError("Active cart not found.")

        delivery_windows = self._delivery_window_service.build_windows(
            timezone_name=self._delivery_timezone_name,
            specs=self._DELIVERY_WINDOW_SPECS,
        )
        selected_delivery_window = next(
            (
                item
                for item in delivery_windows
                if item.window_id == (payload.delivery_window_id or delivery_windows[0].window_id)
            ),
            None,
        )
        if selected_delivery_window is None:
            raise MealCheckoutError("Selected delivery window was not found.")

        price_adjustments = [
            MealCheckoutPriceAdjustmentResponse(
                meal_id=item.meal_id,
                previous_unit_price_minor=item.observed_unit_price_minor,
                current_unit_price_minor=item.current_unit_price_minor,
            )
            for item in cart.items
            if item.pricing_state == CartItemPricingState.PRICE_CHANGED
        ]
        unavailable_meal_ids = [
            item.meal_id for item in cart.items if item.pricing_state == CartItemPricingState.UNAVAILABLE
        ]

        delivery_fee_minor = (
            self._express_delivery_fee_minor if payload.delivery_type == MealDeliveryType.EXPRESS else 0
        )
        subtotal_minor = cart_response.summary.subtotal_minor
        total_minor = subtotal_minor + delivery_fee_minor + cart_response.summary.service_fee_minor

        evaluation = self._billing_service.evaluate_checkout(
            current_user=current_user,
            payload=CheckoutEvaluationInput(
                charge_type=ChargeType.MEAL_ORDER,
                amount_minor=total_minor,
                currency=cart.currency,
                reference_type="meal_cart",
                reference_id=cart.id,
                metadata={},
            ),
        )
        wallet_available_minor = evaluation.wallet_available_minor
        wallet_contribution_minor = min(total_minor, wallet_available_minor)
        card_contribution_minor = max(total_minor - wallet_contribution_minor, 0)
        route = evaluation.route
        quote_status = "ready" if not unavailable_meal_ids else "requires_review"
        message = (
            "Checkout quote created."
            if not unavailable_meal_ids
            else "Some meals became unavailable and require review."
        )
        document = self._checkout_quote_repository.create_quote(
            user_id=current_user.id,
            cart_id=cart.id,
            store_id=_MEAL_STORE_ID,
            currency=cart.currency,
            quote_status=quote_status,
            line_items=[
                {
                    "id": item.id,
                    "meal_id": item.meal_id,
                    "meal_name": item.meal_name,
                    "img_url": item.img_url,
                    "servings": item.servings,
                    "current_unit_price_minor": item.current_unit_price_minor,
                    "currency": item.currency,
                }
                for item in cart.items
            ],
            pricing_summary={
                "currency": cart_response.summary.currency,
                "subtotal_minor": subtotal_minor,
                "delivery_fee_minor": delivery_fee_minor,
                "service_fee_minor": cart_response.summary.service_fee_minor,
                "total_minor": total_minor,
            },
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
                "delivery_type": payload.delivery_type.value,
            },
            route=route.value,
            message=message,
            ttl_seconds=self._quote_ttl_seconds,
        )
        return MealCheckoutQuoteResponse(
            quote_id=str(document["_id"]),
            cart_id=str(document["cart_id"]),
            currency=cart.currency,
            route=route,
            delivery_type=payload.delivery_type,
            wallet_available_minor=wallet_available_minor,
            wallet_contribution_minor=wallet_contribution_minor,
            card_contribution_minor=card_contribution_minor,
            subtotal_minor=subtotal_minor,
            delivery_fee_minor=delivery_fee_minor,
            service_fee_minor=cart_response.summary.service_fee_minor,
            total_minor=total_minor,
            items=[
                MealCheckoutQuoteItemResponse(
                    meal_id=item.meal_id,
                    meal_name=item.meal_name,
                    img_url=item.img_url,
                    servings=item.servings,
                    unit_price_minor=item.current_unit_price_minor,
                    line_total_minor=item.current_unit_price_minor * item.servings,
                    pricing_changed=item.pricing_state == CartItemPricingState.PRICE_CHANGED,
                    unavailable=item.pricing_state == CartItemPricingState.UNAVAILABLE,
                )
                for item in cart.items
            ],
            price_adjustments=price_adjustments,
            unavailable_meal_ids=unavailable_meal_ids,
            selected_delivery_window=self._to_delivery_window_response(selected_delivery_window),
            available_delivery_windows=[self._to_delivery_window_response(item) for item in delivery_windows],
            expires_at=document["expires_at"],
            message=message,
        )

    def confirm_checkout(
        self,
        *,
        current_user: User,
        payload: MealCheckoutConfirmRequest,
    ) -> MealCheckoutConfirmResponse:
        existing_attempt = self._payment_attempt_repository.get_by_idempotency_key(idempotency_key=payload.idempotency_key)
        if existing_attempt is not None:
            order = self._meal_order_repository.get_order(order_id=existing_attempt.order_id)
            if order is None:
                raise MealCheckoutError("Existing payment attempt references a missing order.")
            return self._to_confirm_response(order=order, attempt=existing_attempt)

        quote = self._checkout_quote_repository.get_quote_for_user(user_id=current_user.id, quote_id=payload.quote_id)
        if quote is None:
            raise MealCheckoutError("Checkout quote not found.")
        if quote["expires_at"] < datetime.now(timezone.utc):
            raise MealCheckoutError("Checkout quote expired.")
        if str(quote.get("quote_status") or "") != "ready":
            raise MealCheckoutError("Checkout quote requires review before confirmation.")

        cart = self._meal_cart_repository.get_active_cart(user_id=current_user.id)
        if cart is None:
            raise MealCheckoutError("Active cart not found.")

        pricing_summary = dict(quote.get("pricing_summary") or {})
        order_pricing_summary = {
            "currency": str(pricing_summary.get("currency") or self._default_currency),
            "subtotal_minor": int(pricing_summary.get("subtotal_minor") or 0),
            "delivery_fee_minor": int(pricing_summary.get("delivery_fee_minor") or 0),
            "service_fee_minor": int(pricing_summary.get("service_fee_minor") or 0),
            "total_minor": int(pricing_summary.get("total_minor") or 0),
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
        delivery_window_snapshot = dict(quote.get("delivery_window_snapshot") or {})
        delivery_type = MealDeliveryType(
            str(delivery_window_snapshot.get("delivery_type") or MealDeliveryType.STANDARD.value)
        )
        order = self._meal_order_repository.create_order(
            order_number=self._new_order_number(),
            user_id=current_user.id,
            status=OrderStatus.PENDING_PAYMENT,
            currency=str(quote.get("currency") or self._default_currency),
            delivery_type=delivery_type,
            items=self._build_order_items(
                list(quote.get("line_items") or []),
                delivery_date=self._local_delivery_date(delivery_window_snapshot.get("starts_at")),
            ),
            pricing_summary=order_pricing_summary,
            address_snapshot=dict(quote.get("address_snapshot") or {}),
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
                "delivery_window_id": str(delivery_window_snapshot.get("id") or ""),
                "payment_method": (
                    payload.payment_method.value if payload.payment_method is not None else None
                ),
            },
        )

        if wallet_contribution_minor > 0:
            self._billing_service.place_wallet_hold(
                user_id=current_user.id,
                amount_minor=wallet_contribution_minor,
                currency=order.currency,
                reference_type="meal_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )

        if card_contribution_minor > 0:
            result = self._stripe_gateway.create_meal_payment_intent(
                user_id=current_user.id,
                order_id=order.id,
                amount_minor=card_contribution_minor,
                currency=order.currency,
                idempotency_key=payload.idempotency_key,
                metadata={
                    "purpose": "meal_order",
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
            self._meal_order_repository.update_payment_summary(
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
            self._meal_order_repository.update_status(
                order_id=order.id,
                status=OrderStatus.PAYMENT_PROCESSING,
                note="Awaiting Stripe payment confirmation.",
                actor_user_id=current_user.id,
            )
            return self._to_confirm_response(
                order=self._meal_order_repository.get_order(order_id=order.id) or order,
                attempt=attempt,
            )

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
                reference_type="meal_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._finalize_successful_payment(order_id=order.id)
        finalized_order = self._meal_order_repository.get_order(order_id=order.id)
        if finalized_order is None:
            raise MealCheckoutError("Order was not found after finalization.")
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
                    charge_type=ChargeType.MEAL_ORDER,
                    amount_minor=total_minor,
                    currency=currency,
                    reference_type="meal_cart",
                    reference_id=cart_id,
                    metadata={},
                ),
            )
            if evaluation.wallet_available_minor < total_minor:
                raise MealCheckoutError("Wallet balance is insufficient for this payment method.")
            return total_minor, 0

        raise MealCheckoutError("Selected payment method is not available yet.")

    def handle_payment_intent_succeeded(self, *, event_object: dict[str, Any]) -> None:
        metadata = dict(event_object.get("metadata") or {})
        if str(metadata.get("purpose") or "") != "meal_order":
            return
        payment_intent_id = str(event_object.get("id") or "")
        if not payment_intent_id:
            raise MealCheckoutError("Missing Stripe payment intent id.")
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
        order = self._meal_order_repository.get_order(order_id=attempt.order_id)
        if order is None:
            raise MealCheckoutError("Order not found for payment attempt.")
        if attempt.wallet_capture_amount_minor > 0:
            self._billing_service.capture_wallet_hold(
                user_id=order.user_id,
                amount_minor=attempt.wallet_capture_amount_minor,
                currency=attempt.currency,
                reference_type="meal_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._finalize_successful_payment(order_id=order.id)

    def handle_payment_intent_failed(self, *, event_object: dict[str, Any]) -> None:
        metadata = dict(event_object.get("metadata") or {})
        if str(metadata.get("purpose") or "") != "meal_order":
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
        order = self._meal_order_repository.get_order(order_id=attempt.order_id)
        if order is None:
            return
        if attempt.wallet_hold_amount_minor > 0:
            self._billing_service.release_wallet_hold(
                user_id=order.user_id,
                amount_minor=attempt.wallet_hold_amount_minor,
                currency=attempt.currency,
                reference_type="meal_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._meal_order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.PAYMENT_FAILED,
            note="Stripe payment failed.",
            actor_user_id=None,
        )

    def _finalize_successful_payment(self, *, order_id: str) -> None:
        order = self._meal_order_repository.get_order(order_id=order_id)
        if order is None:
            raise MealCheckoutError("Order not found.")
        if order.status == OrderStatus.CONFIRMED:
            return
        cart_id = str((order.metadata or {}).get("cart_id") or "")
        if cart_id:
            self._meal_cart_repository.mark_converted(cart_id=cart_id)
        self._meal_order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.CONFIRMED,
            note="Payment succeeded.",
            actor_user_id=order.user_id,
        )

    def _local_delivery_date(self, starts_at: Any) -> date | None:
        if starts_at is None:
            return None
        if isinstance(starts_at, str):
            try:
                starts_at = datetime.fromisoformat(starts_at)
            except ValueError:
                return None
        if not isinstance(starts_at, datetime):
            return None
        try:
            tzinfo = ZoneInfo(self._delivery_timezone_name or "Europe/London")
        except ZoneInfoNotFoundError:
            tzinfo = timezone.utc
        return starts_at.astimezone(tzinfo).date()

    @staticmethod
    def _build_order_items(
        items: list[dict[str, Any]],
        *,
        delivery_date: date | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": str(item.get("id") or f"meal-order-item-{index + 1}"),
                "meal_id": str(item.get("meal_id") or ""),
                "meal_name": str(item.get("meal_name") or ""),
                "img_url": str(item.get("img_url") or ""),
                "servings": int(item.get("servings") or 0),
                "unit_price_minor": int(item.get("current_unit_price_minor") or 0),
                "line_total_minor": int(item.get("current_unit_price_minor") or 0) * int(item.get("servings") or 0),
                "currency": str(item.get("currency") or "GBP"),
                "delivery_date": delivery_date.isoformat() if delivery_date is not None else None,
                "slot": "",
            }
            for index, item in enumerate(items)
        ]

    @staticmethod
    def _new_order_number() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"MSO-{timestamp}-{uuid4().hex[:6].upper()}"

    @staticmethod
    def _to_delivery_window_response(item: DeliveryWindowOption) -> MealDeliveryWindowResponse:
        return MealDeliveryWindowResponse(
            id=item.window_id,
            label=item.label,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            is_default=item.is_default,
        )

    def _to_confirm_response(self, *, order, attempt) -> MealCheckoutConfirmResponse:
        requires_payment_action = attempt.card_amount_minor > 0 and attempt.status == PaymentAttemptStatus.REQUIRES_ACTION
        return MealCheckoutConfirmResponse(
            order_id=order.id,
            order_number=order.order_number,
            status=order.status.value,
            requires_payment_action=requires_payment_action,
            payment_action=(
                MealCheckoutPaymentActionResponse(
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
