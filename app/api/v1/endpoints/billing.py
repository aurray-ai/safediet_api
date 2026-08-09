from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import (
    get_billing_service,
    get_checkout_service,
    get_current_user,
    get_meal_checkout_service,
    get_meal_plan_checkout_service,
    get_stripe_billing_gateway,
)
from app.models.user import User
from app.models.billing import SubscriptionPlanCode, SubscriptionStatus, WalletFundingMethod
from app.schemas.billing import (
    BillingOverviewResponse,
    CheckoutEvaluationRequest,
    CheckoutEvaluationResponse,
    PaymentMethodsListResponse,
    SubscriptionSnapshotResponse,
    SubscriptionSyncRequest,
    StripeSubscriptionSetupIntentRequest,
    StripeSubscriptionSetupIntentResponse,
    StripeWalletTopupIntentRequest,
    StripeWalletTopupIntentResponse,
    StripeWebhookResponse,
    WalletSnapshotResponse,
    WalletTopupConfirmationRequest,
    WalletTopupRequest,
    WalletTopupResponse,
    WalletTransactionsListResponse,
)
from app.services.billing_service import (
    BillingService,
    CheckoutEvaluationInput,
    SubscriptionSyncInput,
    WalletTopupConfirmationInput,
)
from app.services.checkout_service import CheckoutService
from app.services.meal_checkout_service import MealCheckoutService
from app.services.meal_plan_checkout_service import MealPlanCheckoutService
from app.services.stripe_billing_gateway import StripeBillingGateway

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/overview", response_model=BillingOverviewResponse, status_code=status.HTTP_200_OK)
def get_billing_overview(
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> BillingOverviewResponse:
    return billing_service.get_overview(current_user=current_user)


@router.get("/subscription", response_model=SubscriptionSnapshotResponse, status_code=status.HTTP_200_OK)
def get_subscription_status(
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> SubscriptionSnapshotResponse:
    return billing_service.get_subscription(current_user=current_user)


@router.get("/wallet", response_model=WalletSnapshotResponse, status_code=status.HTTP_200_OK)
def get_wallet(
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> WalletSnapshotResponse:
    return billing_service.get_wallet(current_user=current_user)


@router.get("/payment-methods", response_model=PaymentMethodsListResponse, status_code=status.HTTP_200_OK)
def list_payment_methods(
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
) -> PaymentMethodsListResponse:
    return billing_service.list_payment_methods(current_user=current_user, stripe_gateway=stripe_gateway)


@router.get("/wallet/transactions", response_model=WalletTransactionsListResponse, status_code=status.HTTP_200_OK)
def list_wallet_transactions(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> WalletTransactionsListResponse:
    return billing_service.list_wallet_transactions(
        current_user=current_user,
        before=before,
        limit=limit,
    )


@router.post("/wallet/topups", response_model=WalletTopupResponse, status_code=status.HTTP_200_OK)
def topup_wallet(
    payload: WalletTopupRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> WalletTopupResponse:
    try:
        return billing_service.topup_wallet(
            current_user=current_user,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            funding_method=payload.funding_method,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/wallet/topups/stripe/payment-intents", response_model=StripeWalletTopupIntentResponse, status_code=status.HTTP_200_OK)
def create_stripe_wallet_topup_intent(
    payload: StripeWalletTopupIntentRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
) -> StripeWalletTopupIntentResponse:
    billing_service.get_wallet(current_user=current_user)
    try:
        result = stripe_gateway.create_wallet_topup_intent(
            user_id=current_user.id,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            funding_method=payload.funding_method.value,
            idempotency_key=payload.idempotency_key,
            metadata={
                "purpose": "wallet_topup",
                "user_id": current_user.id,
                "amount_minor": payload.amount_minor,
                "currency": payload.currency,
                "funding_method": payload.funding_method.value,
                "idempotency_key": payload.idempotency_key,
            },
        )
        return StripeWalletTopupIntentResponse(
            payment_intent_id=result.payment_intent_id,
            client_secret=result.client_secret,
            amount_minor=result.amount_minor,
            currency=result.currency,
            publishable_key=stripe_gateway.publishable_key,
            message="Stripe payment intent created.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/subscriptions/stripe/setup-intents", response_model=StripeSubscriptionSetupIntentResponse, status_code=status.HTTP_200_OK)
def create_stripe_subscription_setup_intent(
    payload: StripeSubscriptionSetupIntentRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
) -> StripeSubscriptionSetupIntentResponse:
    current_subscription = billing_service.get_subscription(current_user=current_user)
    if current_subscription.is_premium:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Subscription is already active.")

    try:
        result = stripe_gateway.create_subscription_setup_intent(
            user_id=current_user.id,
            customer_name=current_user.name,
            customer_email=current_user.email,
            plan_code=payload.plan_code.value,
            price_minor=current_subscription.price_minor,
            currency=payload.currency,
            idempotency_key=payload.idempotency_key,
            metadata={
                "user_id": current_user.id,
                "plan_code": payload.plan_code.value,
                "price_minor": current_subscription.price_minor,
                "currency": payload.currency,
                "idempotency_key": payload.idempotency_key,
            },
        )
        return StripeSubscriptionSetupIntentResponse(
            setup_intent_id=result.setup_intent_id,
            setup_intent_client_secret=result.setup_intent_client_secret,
            customer_id=result.customer_id,
            currency=result.currency,
            publishable_key=stripe_gateway.publishable_key,
            message="Stripe subscription setup intent created.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/wallet/topups/confirm", response_model=WalletTopupResponse, status_code=status.HTTP_200_OK)
def confirm_wallet_topup(
    payload: WalletTopupConfirmationRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> WalletTopupResponse:
    try:
        return billing_service.confirm_wallet_topup(
            current_user=current_user,
            payload=WalletTopupConfirmationInput(
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                funding_method=payload.funding_method,
                provider=payload.provider,
                provider_reference_id=payload.provider_reference_id,
                idempotency_key=payload.idempotency_key,
                metadata=payload.metadata,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/stripe/webhooks", response_model=StripeWebhookResponse, status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
    checkout_service: CheckoutService = Depends(get_checkout_service),
    meal_checkout_service: MealCheckoutService = Depends(get_meal_checkout_service),
    meal_plan_checkout_service: MealPlanCheckoutService = Depends(get_meal_plan_checkout_service),
    stripe_gateway: StripeBillingGateway = Depends(get_stripe_billing_gateway),
) -> StripeWebhookResponse:
    raw_body = await request.body()
    signature_header = request.headers.get("Stripe-Signature")
    try:
        event = stripe_gateway.verify_and_decode_event(
            raw_body=raw_body,
            signature_header=signature_header,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    event_type = str(event.get("type") or "")
    event_object = dict(event.get("data", {}).get("object") or {})
    if event_type == "payment_intent.succeeded":
        _handle_stripe_payment_intent_succeeded(
            billing_service=billing_service,
            checkout_service=checkout_service,
            meal_checkout_service=meal_checkout_service,
            meal_plan_checkout_service=meal_plan_checkout_service,
            event_object=event_object,
        )
    elif event_type == "payment_intent.payment_failed":
        checkout_service.handle_payment_intent_failed(event_object=event_object)
        meal_checkout_service.handle_payment_intent_failed(event_object=event_object)
        meal_plan_checkout_service.handle_payment_intent_failed(event_object=event_object)
    elif event_type == "setup_intent.succeeded":
        _handle_stripe_setup_intent_succeeded(
            billing_service=billing_service,
            stripe_gateway=stripe_gateway,
            event_object=event_object,
        )
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        _handle_stripe_subscription_event(billing_service=billing_service, event_object=event_object)

    return StripeWebhookResponse(received=True)


@router.post("/checkout/evaluate", response_model=CheckoutEvaluationResponse, status_code=status.HTTP_200_OK)
def evaluate_checkout(
    payload: CheckoutEvaluationRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> CheckoutEvaluationResponse:
    return billing_service.evaluate_checkout(
        current_user=current_user,
        payload=CheckoutEvaluationInput(
            charge_type=payload.charge_type,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            reference_type=payload.reference_type,
            reference_id=payload.reference_id,
            metadata=payload.metadata,
        ),
    )


@router.post("/subscription/sync", response_model=SubscriptionSnapshotResponse, status_code=status.HTTP_200_OK)
def sync_subscription(
    payload: SubscriptionSyncRequest,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> SubscriptionSnapshotResponse:
    try:
        return billing_service.sync_subscription(
            current_user=current_user,
            payload=SubscriptionSyncInput(
                plan_code=payload.plan_code,
                status=payload.status,
                provider=payload.provider,
                price_minor=payload.price_minor,
                currency=payload.currency,
                is_premium=payload.is_premium,
                started_at=payload.started_at,
                expires_at=payload.expires_at,
                renewal_at=payload.renewal_at,
                original_transaction_id=payload.original_transaction_id,
                latest_transaction_id=payload.latest_transaction_id,
                provider_payload=payload.provider_payload,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _handle_stripe_payment_intent_succeeded(
    *,
    billing_service: BillingService,
    checkout_service: CheckoutService,
    meal_checkout_service: MealCheckoutService,
    meal_plan_checkout_service: MealPlanCheckoutService,
    event_object: dict[str, Any],
) -> None:
    metadata = dict(event_object.get("metadata") or {})
    purpose = str(metadata.get("purpose") or "")
    if purpose == "grocery_order":
        checkout_service.handle_payment_intent_succeeded(event_object=event_object)
        return
    if purpose == "meal_order":
        meal_checkout_service.handle_payment_intent_succeeded(event_object=event_object)
        return
    if purpose == "meal_plan_order":
        meal_plan_checkout_service.handle_payment_intent_succeeded(event_object=event_object)
        return
    if purpose != "wallet_topup":
        return

    user_id = str(metadata.get("user_id") or "")
    if not user_id:
        raise ValueError("Stripe payment intent is missing user metadata.")

    funding_method = WalletFundingMethod(str(metadata.get("funding_method") or WalletFundingMethod.CARD.value))
    billing_service.confirm_wallet_topup_for_user_id(
        user_id=user_id,
        payload=WalletTopupConfirmationInput(
            amount_minor=int(metadata.get("amount_minor") or event_object.get("amount") or 0),
            currency=str(metadata.get("currency") or event_object.get("currency") or "GBP").upper(),
            funding_method=funding_method,
            provider="stripe",
            provider_reference_id=str(event_object.get("id") or ""),
            idempotency_key=str(metadata.get("idempotency_key") or event_object.get("id") or ""),
            metadata={
                **metadata,
                "stripe_payment_intent_status": str(event_object.get("status") or ""),
            },
        ),
    )


def _handle_stripe_subscription_event(
    *,
    billing_service: BillingService,
    event_object: dict[str, Any],
) -> None:
    metadata = dict(event_object.get("metadata") or {})
    user_id = str(metadata.get("user_id") or "")
    if not user_id:
        return

    status_raw = str(event_object.get("status") or "inactive").lower()
    if status_raw in {"active", "trialing"}:
        mapped_status = SubscriptionStatus.ACTIVE
        is_premium = True
    elif status_raw == "past_due":
        mapped_status = SubscriptionStatus.PAST_DUE
        is_premium = True
    elif status_raw == "canceled":
        mapped_status = SubscriptionStatus.CANCELED
        is_premium = False
    else:
        mapped_status = SubscriptionStatus.EXPIRED
        is_premium = False

    items = list((event_object.get("items") or {}).get("data") or [])
    first_item = dict(items[0]) if items else {}
    price = dict(first_item.get("price") or {})
    currency = str(
        event_object.get("currency")
        or price.get("currency")
        or metadata.get("currency")
        or "GBP"
    ).upper()

    billing_service.sync_subscription_for_user_id(
        user_id=user_id,
        payload=SubscriptionSyncInput(
            plan_code=SubscriptionPlanCode.PREMIUM_MONTHLY if is_premium else SubscriptionPlanCode.FREE,
            status=mapped_status,
            provider="stripe",
            price_minor=int(price.get("unit_amount") or metadata.get("price_minor") or 0),
            currency=currency,
            is_premium=is_premium,
            started_at=_stripe_timestamp(
                event_object.get("current_period_start")
                or event_object.get("start_date")
                or event_object.get("created")
            ),
            expires_at=_stripe_timestamp(event_object.get("current_period_end")),
            renewal_at=_stripe_timestamp(event_object.get("current_period_end")),
            original_transaction_id=str(event_object.get("latest_invoice") or event_object.get("id") or ""),
            latest_transaction_id=str(event_object.get("latest_invoice") or event_object.get("id") or ""),
            provider_payload=event_object,
        ),
    )


def _handle_stripe_setup_intent_succeeded(
    *,
    billing_service: BillingService,
    stripe_gateway: StripeBillingGateway,
    event_object: dict[str, Any],
) -> None:
    metadata = dict(event_object.get("metadata") or {})
    user_id = str(metadata.get("user_id") or "")
    customer_id = str(event_object.get("customer") or "")
    payment_method_id = str(event_object.get("payment_method") or "")
    if not user_id or not customer_id or not payment_method_id:
        return

    plan_code_raw = str(metadata.get("plan_code") or SubscriptionPlanCode.PREMIUM_MONTHLY.value)
    try:
        plan_code = SubscriptionPlanCode(plan_code_raw)
    except ValueError:
        plan_code = SubscriptionPlanCode.PREMIUM_MONTHLY

    price_minor = int(metadata.get("price_minor") or 900)
    currency = str(metadata.get("currency") or event_object.get("currency") or "GBP").upper()
    payment_method_details = None
    try:
        payment_method_details = stripe_gateway.retrieve_payment_method(
            payment_method_id=payment_method_id,
            customer_id=customer_id,
        )
    except RuntimeError:
        payment_method_details = None
    subscription_result = stripe_gateway.create_subscription_from_setup_intent(
        user_id=user_id,
        customer_id=customer_id,
        payment_method_id=payment_method_id,
        plan_code=plan_code.value,
        price_minor=price_minor,
        currency=currency,
        idempotency_key=f"stripe-subscription:{event_object.get('id') or customer_id}",
        metadata={
            **metadata,
            "stripe_setup_intent_id": str(event_object.get("id") or ""),
            "stripe_customer_id": customer_id,
            "stripe_payment_method_id": payment_method_id,
        },
    )

    mapped_status = _map_stripe_subscription_status(subscription_result.status)
    billing_service.sync_subscription_for_user_id(
        user_id=user_id,
        payload=SubscriptionSyncInput(
            plan_code=plan_code if mapped_status[1] else SubscriptionPlanCode.FREE,
            status=mapped_status[0],
            provider="stripe",
            price_minor=subscription_result.price_minor,
            currency=subscription_result.currency,
            is_premium=mapped_status[1],
            started_at=subscription_result.started_at,
            expires_at=subscription_result.expires_at,
            renewal_at=subscription_result.renewal_at,
            original_transaction_id=subscription_result.latest_invoice_id,
            latest_transaction_id=subscription_result.subscription_id,
            provider_payload={
                **metadata,
                "stripe_setup_intent_id": str(event_object.get("id") or ""),
                "stripe_customer_id": customer_id,
                "stripe_payment_method_id": payment_method_id,
                "stripe_subscription_id": subscription_result.subscription_id,
                "stripe_subscription_status": subscription_result.status,
                "stripe_payment_method_type": (
                    payment_method_details.payment_method_type
                    if payment_method_details is not None
                    else "card"
                ),
                "stripe_payment_method_brand": (
                    payment_method_details.brand
                    if payment_method_details is not None
                    else None
                ),
                "stripe_payment_method_last4": (
                    payment_method_details.last4
                    if payment_method_details is not None
                    else None
                ),
                "stripe_payment_method_exp_month": (
                    payment_method_details.exp_month
                    if payment_method_details is not None
                    else None
                ),
                "stripe_payment_method_exp_year": (
                    payment_method_details.exp_year
                    if payment_method_details is not None
                    else None
                ),
            },
        ),
    )


def _map_stripe_subscription_status(status_raw: str) -> tuple[SubscriptionStatus, bool]:
    normalized = str(status_raw or "").lower()
    if normalized in {"active", "trialing"}:
        return SubscriptionStatus.ACTIVE, True
    if normalized == "past_due":
        return SubscriptionStatus.PAST_DUE, True
    if normalized == "canceled":
        return SubscriptionStatus.CANCELED, False
    return SubscriptionStatus.EXPIRED, False


def _stripe_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
