from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.models.billing import ChargeType, CheckoutPaymentMethod
from app.models.meal_order import MealDeliveryType
from app.models.order import OrderStatus, PaymentAttemptStatus
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.repositories.checkout_quote_repository import CheckoutQuoteRepository
from app.repositories.meal_order_repository import MealOrderRepository
from app.repositories.meal_repository import MealRepository
from app.repositories.payment_attempt_repository import PaymentAttemptRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.schemas.meal_checkout import MealCheckoutPaymentActionResponse
from app.schemas.meal_plan_checkout import (
    MealPlanCheckoutConfirmRequest,
    MealPlanCheckoutConfirmResponse,
    MealPlanCheckoutQuoteItemResponse,
    MealPlanCheckoutQuoteRequest,
    MealPlanCheckoutQuoteResponse,
)
from app.services.billing_service import BillingService, CheckoutEvaluationInput
from app.services.meal_pricing import resolve_meal_unit_price_minor
from app.services.saved_meal_plan_service import SavedMealPlanNotFoundError, SavedMealPlanService
from app.services.stripe_billing_gateway import StripeBillingGateway

_PLAN_CHECKOUT_STORE_ID = "meal_plan"


class MealPlanCheckoutError(Exception):
    pass


class MealPlanCheckoutService:
    def __init__(
        self,
        *,
        saved_meal_plan_repository: SavedMealPlanRepository,
        meal_repository: MealRepository,
        checkout_quote_repository: CheckoutQuoteRepository,
        meal_order_repository: MealOrderRepository,
        payment_attempt_repository: PaymentAttemptRepository,
        address_repository: AddressRepository,
        billing_service: BillingService,
        saved_meal_plan_service: SavedMealPlanService,
        stripe_gateway: StripeBillingGateway,
        default_currency: str,
        quote_ttl_seconds: int,
        cancellation_window_minutes: int,
    ) -> None:
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._meal_repository = meal_repository
        self._checkout_quote_repository = checkout_quote_repository
        self._meal_order_repository = meal_order_repository
        self._payment_attempt_repository = payment_attempt_repository
        self._address_repository = address_repository
        self._billing_service = billing_service
        self._saved_meal_plan_service = saved_meal_plan_service
        self._stripe_gateway = stripe_gateway
        self._default_currency = default_currency
        self._quote_ttl_seconds = quote_ttl_seconds
        self._cancellation_window_minutes = cancellation_window_minutes

    def create_quote(
        self,
        *,
        current_user: User,
        payload: MealPlanCheckoutQuoteRequest,
    ) -> MealPlanCheckoutQuoteResponse:
        address = self._address_repository.get_for_user(user_id=current_user.id, address_id=payload.address_id)
        if address is None:
            raise MealPlanCheckoutError("Selected delivery address was not found.")

        plan = self._resolve_plan(
            user_id=current_user.id,
            effective_date=payload.effective_date,
            view=payload.view,
        )
        if plan is None:
            raise MealPlanCheckoutError("No meal plan was found for the selected date.")

        line_items = self._extract_plan_line_items(plan)
        if not line_items:
            raise MealPlanCheckoutError("This plan has no meals assigned yet.")

        quote_items: list[dict[str, Any]] = []
        unavailable_meal_ids: list[str] = []
        subtotal_minor = 0
        for line_item in line_items:
            meal_id = str(line_item.get("meal_id") or "")
            meal = self._meal_repository.get_meal(meal_id) if meal_id else None
            servings = max(int(line_item.get("servings") or 1), 1)
            if meal is None:
                unavailable_meal_ids.append(meal_id)
                quote_items.append(
                    {
                        "meal_id": meal_id,
                        "meal_name": str(line_item.get("name") or "Unavailable meal"),
                        "img_url": str(line_item.get("hero_image_url") or ""),
                        "servings": servings,
                        "unit_price_minor": 0,
                        "line_total_minor": 0,
                        "delivery_date": line_item["delivery_date"],
                        "slot": line_item["slot"],
                        "unavailable": True,
                    }
                )
                continue

            unit_price_minor = resolve_meal_unit_price_minor(meal=meal, currency=payload.currency)
            line_total_minor = unit_price_minor * servings
            subtotal_minor += line_total_minor
            quote_items.append(
                {
                    "meal_id": meal.id,
                    "meal_name": meal.name,
                    "img_url": meal.hero_image_url,
                    "servings": servings,
                    "unit_price_minor": unit_price_minor,
                    "line_total_minor": line_total_minor,
                    "delivery_date": line_item["delivery_date"],
                    "slot": line_item["slot"],
                    "unavailable": False,
                }
            )

        delivery_fee_minor = 0
        service_fee_minor = 0
        total_minor = subtotal_minor + delivery_fee_minor + service_fee_minor

        evaluation = self._billing_service.evaluate_checkout(
            current_user=current_user,
            payload=CheckoutEvaluationInput(
                charge_type=ChargeType.MEAL_ORDER,
                amount_minor=total_minor,
                currency=payload.currency,
                reference_type="saved_meal_plan",
                reference_id=plan.id,
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
            else "Some planned meals are no longer available and require review."
        )

        document = self._checkout_quote_repository.create_quote(
            user_id=current_user.id,
            cart_id=plan.id,
            store_id=_PLAN_CHECKOUT_STORE_ID,
            currency=payload.currency,
            quote_status=quote_status,
            line_items=[
                {
                    **item,
                    "delivery_date": item["delivery_date"].isoformat(),
                }
                for item in quote_items
            ],
            pricing_summary={
                "currency": payload.currency,
                "subtotal_minor": subtotal_minor,
                "delivery_fee_minor": delivery_fee_minor,
                "service_fee_minor": service_fee_minor,
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
                "saved_plan_id": plan.id,
                "source_saved_plan_id": plan.source_saved_plan_id,
                "view_mode": plan.view_mode,
            },
            route=route.value,
            message=message,
            ttl_seconds=self._quote_ttl_seconds,
        )

        delivery_days = sorted({item["delivery_date"] for item in quote_items})
        return MealPlanCheckoutQuoteResponse(
            quote_id=str(document["_id"]),
            plan_id=plan.id,
            currency=payload.currency,
            route=route,
            wallet_available_minor=wallet_available_minor,
            wallet_contribution_minor=wallet_contribution_minor,
            card_contribution_minor=card_contribution_minor,
            subtotal_minor=subtotal_minor,
            delivery_fee_minor=delivery_fee_minor,
            service_fee_minor=service_fee_minor,
            total_minor=total_minor,
            items=[MealPlanCheckoutQuoteItemResponse(**item) for item in quote_items],
            unavailable_meal_ids=unavailable_meal_ids,
            delivery_days=delivery_days,
            expires_at=document["expires_at"],
            message=message,
        )

    def confirm_checkout(
        self,
        *,
        current_user: User,
        payload: MealPlanCheckoutConfirmRequest,
    ) -> MealPlanCheckoutConfirmResponse:
        existing_attempt = self._payment_attempt_repository.get_by_idempotency_key(
            idempotency_key=payload.idempotency_key
        )
        if existing_attempt is not None:
            order = self._meal_order_repository.get_order(order_id=existing_attempt.order_id)
            if order is None:
                raise MealPlanCheckoutError("Existing payment attempt references a missing order.")
            return self._to_confirm_response(order=order, attempt=existing_attempt)

        quote = self._checkout_quote_repository.get_quote_for_user(user_id=current_user.id, quote_id=payload.quote_id)
        if quote is None:
            raise MealPlanCheckoutError("Checkout quote not found.")
        if quote["expires_at"] < datetime.now(timezone.utc):
            raise MealPlanCheckoutError("Checkout quote expired.")
        if str(quote.get("quote_status") or "") != "ready":
            raise MealPlanCheckoutError("Checkout quote requires review before confirmation.")

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
                reference_id=str(quote.get("cart_id") or ""),
                currency=str(quote.get("currency") or self._default_currency),
                total_minor=total_minor,
                payment_method=payload.payment_method,
            )

        delivery_window_snapshot = dict(quote.get("delivery_window_snapshot") or {})
        source_saved_plan_id = str(delivery_window_snapshot.get("saved_plan_id") or quote.get("cart_id") or "")
        resolved_saved_plan_id = source_saved_plan_id
        source_plan = None
        if source_saved_plan_id:
            source_plan = self._saved_meal_plan_repository.get_saved_plan(
                user_id=current_user.id,
                saved_plan_id=source_saved_plan_id,
            )
            if source_plan is not None and str(source_plan.status or "").lower() == "draft":
                resolved_saved_plan_id = ""

        order = self._meal_order_repository.create_order(
            order_number=self._new_order_number(),
            user_id=current_user.id,
            status=OrderStatus.PENDING_PAYMENT,
            currency=str(quote.get("currency") or self._default_currency),
            delivery_type=MealDeliveryType.STANDARD,
            items=[
                {
                    "id": str(item.get("id") or f"meal-plan-order-item-{index + 1}"),
                    "meal_id": str(item.get("meal_id") or ""),
                    "meal_name": str(item.get("meal_name") or ""),
                    "img_url": str(item.get("img_url") or ""),
                    "servings": int(item.get("servings") or 0),
                    "unit_price_minor": int(item.get("unit_price_minor") or 0),
                    "line_total_minor": int(item.get("line_total_minor") or 0),
                    "currency": str(quote.get("currency") or self._default_currency),
                    "delivery_date": item.get("delivery_date"),
                    "slot": str(item.get("slot") or ""),
                }
                for index, item in enumerate(list(quote.get("line_items") or []))
            ],
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
            cancellation_window_expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=self._cancellation_window_minutes),
            status_history=[
                {
                    "status": OrderStatus.PENDING_PAYMENT.value,
                    "note": "Plan order created.",
                    "actor_user_id": current_user.id,
                    "created_at": datetime.now(timezone.utc),
                }
            ],
            metadata={
                "quote_id": str(quote["_id"]),
                "saved_plan_id": resolved_saved_plan_id or None,
                "source_saved_plan_id": source_saved_plan_id or None,
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
                    "purpose": "meal_plan_order",
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
        self._publish_draft_plan_if_needed(user_id=current_user.id, order_id=order.id)
        self._meal_order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.CONFIRMED,
            note="Payment succeeded.",
            actor_user_id=current_user.id,
        )
        finalized_order = self._meal_order_repository.get_order(order_id=order.id)
        if finalized_order is None:
            raise MealPlanCheckoutError("Order was not found after finalization.")
        return self._to_confirm_response(order=finalized_order, attempt=attempt)

    def handle_payment_intent_succeeded(self, *, event_object: dict[str, Any]) -> None:
        metadata = dict(event_object.get("metadata") or {})
        if str(metadata.get("purpose") or "") != "meal_plan_order":
            return
        payment_intent_id = str(event_object.get("id") or "")
        if not payment_intent_id:
            raise MealPlanCheckoutError("Missing Stripe payment intent id.")
        attempt = self._payment_attempt_repository.get_by_provider_payment_intent_id(
            provider="stripe",
            provider_payment_intent_id=payment_intent_id,
        )
        if attempt is None or attempt.status == PaymentAttemptStatus.SUCCEEDED:
            return
        order = self._meal_order_repository.get_order(order_id=attempt.order_id)
        if order is None:
            raise MealPlanCheckoutError("Order not found for payment attempt.")
        self._payment_attempt_repository.mark_status(
            attempt_id=attempt.id,
            status=PaymentAttemptStatus.SUCCEEDED,
            provider_payload=event_object,
        )
        if attempt.wallet_capture_amount_minor > 0:
            self._billing_service.capture_wallet_hold(
                user_id=order.user_id,
                amount_minor=attempt.wallet_capture_amount_minor,
                currency=attempt.currency,
                reference_type="meal_order",
                reference_id=order.id,
                metadata={"order_id": order.id},
            )
        self._publish_draft_plan_if_needed(user_id=order.user_id, order_id=order.id)
        self._meal_order_repository.update_status(
            order_id=order.id,
            status=OrderStatus.CONFIRMED,
            note="Payment succeeded.",
            actor_user_id=order.user_id,
        )

    def handle_payment_intent_failed(self, *, event_object: dict[str, Any]) -> None:
        metadata = dict(event_object.get("metadata") or {})
        if str(metadata.get("purpose") or "") != "meal_plan_order":
            return
        payment_intent_id = str(event_object.get("id") or "")
        attempt = self._payment_attempt_repository.get_by_provider_payment_intent_id(
            provider="stripe",
            provider_payment_intent_id=payment_intent_id,
        )
        if attempt is None or attempt.status == PaymentAttemptStatus.FAILED:
            return
        order = self._meal_order_repository.get_order(order_id=attempt.order_id)
        if order is None:
            return
        self._payment_attempt_repository.mark_status(
            attempt_id=attempt.id,
            status=PaymentAttemptStatus.FAILED,
            provider_payload=event_object,
        )
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

    def _resolve_payment_split(
        self,
        *,
        current_user: User,
        reference_id: str,
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
                    reference_type="saved_meal_plan",
                    reference_id=reference_id,
                    metadata={},
                ),
            )
            if evaluation.wallet_available_minor < total_minor:
                raise MealPlanCheckoutError("Wallet balance is insufficient for this payment method.")
            return total_minor, 0

        raise MealPlanCheckoutError("Selected payment method is not available yet.")

    def _resolve_plan(
        self,
        *,
        user_id: str,
        effective_date: date,
        view: str,
    ) -> SavedMealPlan | None:
        if view == "week":
            week_start, week_end = self._week_bounds(effective_date)
            for statuses in (["draft"], ["saved", "missing_groceries"]):
                plan = self._saved_meal_plan_repository.get_saved_weekly_plan_for_week(
                    user_id=user_id,
                    week_start=week_start,
                    week_end=week_end,
                    allowed_statuses=statuses,
                )
                if plan is not None:
                    return plan
                plan = self._saved_meal_plan_repository.get_saved_weekly_plan_covering_date(
                    user_id=user_id,
                    target_date=effective_date,
                    allowed_statuses=statuses,
                )
                if plan is not None:
                    return plan
        for statuses in (["draft"], ["saved", "missing_groceries"]):
            plan = self._saved_meal_plan_repository.get_saved_day_plan_for_date(
                user_id=user_id,
                effective_date=effective_date,
                allowed_statuses=statuses,
            )
            if plan is not None:
                return plan
        return None

    def _publish_draft_plan_if_needed(self, *, user_id: str, order_id: str) -> None:
        order = self._meal_order_repository.get_order(order_id=order_id)
        if order is None:
            return
        saved_plan_id = str(order.metadata.get("saved_plan_id") or "").strip()
        if saved_plan_id:
            return
        source_saved_plan_id = str(order.metadata.get("source_saved_plan_id") or "").strip()
        if not source_saved_plan_id:
            return
        try:
            published_plan = self._saved_meal_plan_service.publish_saved_plan(
                user_id=user_id,
                saved_plan_id=source_saved_plan_id,
            )
        except SavedMealPlanNotFoundError:
            return
        self._meal_order_repository.update_metadata(
            order_id=order_id,
            metadata={
                **order.metadata,
                "saved_plan_id": published_plan.id,
                "source_saved_plan_id": source_saved_plan_id,
            },
        )

    @staticmethod
    def _week_bounds(selected_date: date) -> tuple[date, date]:
        week_start = selected_date - timedelta(days=selected_date.weekday())
        return week_start, week_start + timedelta(days=6)

    @staticmethod
    def _extract_plan_line_items(plan: SavedMealPlan) -> list[dict[str, Any]]:
        line_items: list[dict[str, Any]] = []
        payload = plan.plan_payload or {}
        if plan.view_mode == "week":
            for day in list(payload.get("days") or []):
                if not isinstance(day, dict):
                    continue
                day_date_raw = str(day.get("date") or "")
                if not day_date_raw:
                    continue
                try:
                    day_date = date.fromisoformat(day_date_raw)
                except ValueError:
                    continue
                for section in list(day.get("sections") or []):
                    if not isinstance(section, dict):
                        continue
                    slot = str(section.get("slot") or "")
                    for item in list(section.get("items") or []):
                        if not isinstance(item, dict) or not item.get("meal_id"):
                            continue
                        line_items.append({**item, "delivery_date": day_date, "slot": slot})
        else:
            day_date = plan.effective_date
            if day_date is None:
                return []
            for section in list(payload.get("sections") or []):
                if not isinstance(section, dict):
                    continue
                slot = str(section.get("slot") or "")
                for item in list(section.get("items") or []):
                    if not isinstance(item, dict) or not item.get("meal_id"):
                        continue
                    line_items.append({**item, "delivery_date": day_date, "slot": slot})
        return line_items

    @staticmethod
    def _new_order_number() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"MPO-{timestamp}-{uuid4().hex[:6].upper()}"

    def _to_confirm_response(self, *, order, attempt) -> MealPlanCheckoutConfirmResponse:
        requires_payment_action = (
            attempt.card_amount_minor > 0 and attempt.status == PaymentAttemptStatus.REQUIRES_ACTION
        )
        return MealPlanCheckoutConfirmResponse(
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
