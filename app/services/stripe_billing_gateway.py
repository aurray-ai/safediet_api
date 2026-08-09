from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class StripePaymentIntentResult:
    payment_intent_id: str
    client_secret: str
    amount_minor: int
    currency: str
    status: str


@dataclass(frozen=True, slots=True)
class StripeSubscriptionSetupIntentResult:
    setup_intent_id: str
    setup_intent_client_secret: str
    customer_id: str
    currency: str
    status: str


@dataclass(frozen=True, slots=True)
class StripeSubscriptionResult:
    subscription_id: str
    status: str
    price_minor: int
    currency: str
    customer_id: str
    latest_invoice_id: str | None
    started_at: datetime | None
    expires_at: datetime | None
    renewal_at: datetime | None


@dataclass(frozen=True, slots=True)
class StripePaymentMethodDetails:
    payment_method_id: str
    payment_method_type: str
    brand: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None


class StripeBillingGateway:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    @property
    def publishable_key(self) -> str | None:
        return self._settings.stripe_publishable_key

    def create_wallet_topup_intent(
        self,
        *,
        user_id: str,
        amount_minor: int,
        currency: str,
        funding_method: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> StripePaymentIntentResult:
        api_key = self._require_api_key()
        normalized_currency = str(currency).strip().lower()
        payload = {
            "amount": int(amount_minor),
            "currency": normalized_currency,
            "automatic_payment_methods[enabled]": "true",
            "metadata[user_id]": user_id,
            "metadata[amount_minor]": str(int(amount_minor)),
            "metadata[currency]": str(currency).strip().upper(),
            "metadata[funding_method]": funding_method,
            "metadata[idempotency_key]": idempotency_key,
            "metadata[purpose]": "wallet_topup",
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Idempotency-Key": idempotency_key,
        }
        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/payment_intents",
            data=payload,
            headers=headers,
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        client_secret = str(data.get("client_secret") or "")
        payment_intent_id = str(data.get("id") or "")
        if not client_secret or not payment_intent_id:
            raise RuntimeError("Stripe did not return a payment intent client secret.")
        return StripePaymentIntentResult(
            payment_intent_id=payment_intent_id,
            client_secret=client_secret,
            amount_minor=int(data.get("amount") or amount_minor),
            currency=str(data.get("currency") or normalized_currency).upper(),
            status=str(data.get("status") or "requires_payment_method"),
        )

    def create_grocery_payment_intent(
        self,
        *,
        user_id: str,
        order_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> StripePaymentIntentResult:
        api_key = self._require_api_key()
        normalized_currency = str(currency).strip().lower()
        payload = {
            "amount": int(amount_minor),
            "currency": normalized_currency,
            "automatic_payment_methods[enabled]": "true",
            "metadata[user_id]": user_id,
            "metadata[order_id]": order_id,
            "metadata[currency]": str(currency).strip().upper(),
            "metadata[idempotency_key]": idempotency_key,
            "metadata[purpose]": "grocery_order",
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)

        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/payment_intents",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        client_secret = str(data.get("client_secret") or "")
        payment_intent_id = str(data.get("id") or "")
        if not payment_intent_id:
            raise RuntimeError("Stripe did not return a payment intent id.")
        return StripePaymentIntentResult(
            payment_intent_id=payment_intent_id,
            client_secret=client_secret,
            amount_minor=int(data.get("amount") or amount_minor),
            currency=str(data.get("currency") or normalized_currency).upper(),
            status=str(data.get("status") or "requires_payment_method"),
        )

    def create_meal_payment_intent(
        self,
        *,
        user_id: str,
        order_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> StripePaymentIntentResult:
        api_key = self._require_api_key()
        normalized_currency = str(currency).strip().lower()
        payload = {
            "amount": int(amount_minor),
            "currency": normalized_currency,
            "automatic_payment_methods[enabled]": "true",
            "metadata[user_id]": user_id,
            "metadata[order_id]": order_id,
            "metadata[currency]": str(currency).strip().upper(),
            "metadata[idempotency_key]": idempotency_key,
            "metadata[purpose]": "meal_order",
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)

        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/payment_intents",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        client_secret = str(data.get("client_secret") or "")
        payment_intent_id = str(data.get("id") or "")
        if not payment_intent_id:
            raise RuntimeError("Stripe did not return a payment intent id.")
        return StripePaymentIntentResult(
            payment_intent_id=payment_intent_id,
            client_secret=client_secret,
            amount_minor=int(data.get("amount") or amount_minor),
            currency=str(data.get("currency") or normalized_currency).upper(),
            status=str(data.get("status") or "requires_payment_method"),
        )

    def refund_payment_intent(
        self,
        *,
        payment_intent_id: str,
        amount_minor: int,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> str:
        api_key = self._require_api_key()
        payload = {
            "payment_intent": payment_intent_id,
            "amount": int(amount_minor),
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)
        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/refunds",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        refund_id = str(data.get("id") or "")
        if not refund_id:
            raise RuntimeError("Stripe did not return a refund id.")
        return refund_id

    def create_subscription_setup_intent(
        self,
        *,
        user_id: str,
        customer_name: str,
        customer_email: str,
        plan_code: str,
        price_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> StripeSubscriptionSetupIntentResult:
        api_key = self._require_api_key()
        normalized_currency = str(currency).strip().lower()
        customer = self._create_customer(
            api_key=api_key,
            user_id=user_id,
            customer_name=customer_name,
            customer_email=customer_email,
            idempotency_key=f"{idempotency_key}:customer",
            metadata={
                **metadata,
                "user_id": user_id,
                "plan_code": plan_code,
                "purpose": "subscription_setup",
            },
        )
        payload = {
            "customer": customer["id"],
            "usage": "off_session",
            "automatic_payment_methods[enabled]": "true",
            "metadata[user_id]": user_id,
            "metadata[plan_code]": plan_code,
            "metadata[price_minor]": str(int(price_minor)),
            "metadata[currency]": str(currency).strip().upper(),
            "metadata[idempotency_key]": idempotency_key,
            "metadata[purpose]": "subscription_setup",
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)

        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/setup_intents",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        client_secret = str(data.get("client_secret") or "")
        setup_intent_id = str(data.get("id") or "")
        if not client_secret or not setup_intent_id:
            raise RuntimeError("Stripe did not return a setup intent client secret.")
        return StripeSubscriptionSetupIntentResult(
            setup_intent_id=setup_intent_id,
            setup_intent_client_secret=client_secret,
            customer_id=str(customer.get("id") or ""),
            currency=str(data.get("currency") or normalized_currency).upper(),
            status=str(data.get("status") or "requires_payment_method"),
        )

    def create_subscription_from_setup_intent(
        self,
        *,
        user_id: str,
        customer_id: str,
        payment_method_id: str,
        plan_code: str,
        price_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> StripeSubscriptionResult:
        api_key = self._require_api_key()
        normalized_currency = str(currency).strip().lower()
        payload: dict[str, Any] = {
            "customer": customer_id,
            "default_payment_method": payment_method_id,
            "collection_method": "charge_automatically",
            "payment_behavior": "allow_incomplete",
            "payment_settings[save_default_payment_method]": "on_subscription",
            "metadata[user_id]": user_id,
            "metadata[plan_code]": plan_code,
            "metadata[price_minor]": str(int(price_minor)),
            "metadata[currency]": str(currency).strip().upper(),
            "metadata[idempotency_key]": idempotency_key,
            "metadata[purpose]": "subscription",
            "items[0][price_data][currency]": normalized_currency,
            "items[0][price_data][product_data][name]": "Safediet Premium",
            "items[0][price_data][unit_amount]": str(int(price_minor)),
            "items[0][price_data][recurring][interval]": "month",
            "items[0][price_data][recurring][interval_count]": "1",
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)

        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/subscriptions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        return StripeSubscriptionResult(
            subscription_id=str(data.get("id") or ""),
            status=str(data.get("status") or "incomplete"),
            price_minor=int(
                ((data.get("items") or {}).get("data") or [{}])[0].get("price", {}).get("unit_amount")
                or price_minor
            ),
            currency=str(data.get("currency") or normalized_currency).upper(),
            customer_id=str(data.get("customer") or customer_id),
            latest_invoice_id=str(data.get("latest_invoice") or "") or None,
            started_at=self._epoch_to_datetime(data.get("start_date") or data.get("created")),
            expires_at=self._epoch_to_datetime(data.get("current_period_end")),
            renewal_at=self._epoch_to_datetime(data.get("current_period_end")),
        )

    def cancel_subscription(self, *, subscription_id: str) -> StripeSubscriptionResult:
        api_key = self._require_api_key()
        response = httpx.delete(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        return StripeSubscriptionResult(
            subscription_id=str(data.get("id") or subscription_id),
            status=str(data.get("status") or "canceled"),
            price_minor=int(
                ((data.get("items") or {}).get("data") or [{}])[0].get("price", {}).get("unit_amount") or 0
            ),
            currency=str(data.get("currency") or "gbp").upper(),
            customer_id=str(data.get("customer") or ""),
            latest_invoice_id=str(data.get("latest_invoice") or "") or None,
            started_at=self._epoch_to_datetime(data.get("start_date") or data.get("created")),
            expires_at=self._epoch_to_datetime(data.get("current_period_end") or data.get("canceled_at")),
            renewal_at=None,
        )

    def retrieve_payment_method(
        self,
        *,
        payment_method_id: str,
        customer_id: str | None = None,
    ) -> StripePaymentMethodDetails:
        api_key = self._require_api_key()
        response = httpx.get(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/payment_methods/{payment_method_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        returned_customer_id = str(data.get("customer") or "")
        if customer_id and returned_customer_id and returned_customer_id != customer_id:
            raise RuntimeError("Stripe payment method does not belong to the expected customer.")
        card_payload = dict(data.get("card") or {})
        return StripePaymentMethodDetails(
            payment_method_id=str(data.get("id") or payment_method_id),
            payment_method_type=str(data.get("type") or "card"),
            brand=str(card_payload.get("brand") or "") or None,
            last4=str(card_payload.get("last4") or "") or None,
            exp_month=int(card_payload["exp_month"]) if card_payload.get("exp_month") is not None else None,
            exp_year=int(card_payload["exp_year"]) if card_payload.get("exp_year") is not None else None,
        )

    def verify_and_decode_event(self, *, raw_body: bytes, signature_header: str | None) -> dict[str, Any]:
        secret = self._require_webhook_secret()
        if signature_header is None or not signature_header.strip():
            raise ValueError("Missing Stripe-Signature header.")

        timestamp, signature = self._parse_signature_header(signature_header)
        signed_payload = f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            raise ValueError("Invalid Stripe webhook signature.")

        event_timestamp = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        if (datetime.now(timezone.utc) - event_timestamp).total_seconds() > float(
            self._settings.stripe_webhook_tolerance_seconds
        ):
            raise ValueError("Stripe webhook timestamp is too old.")

        return json.loads(raw_body.decode("utf-8"))

    def _require_api_key(self) -> str:
        if self._settings.stripe_api_key is None:
            raise RuntimeError("Stripe API key is not configured.")
        return self._settings.stripe_api_key.get_secret_value()

    def _require_webhook_secret(self) -> str:
        if self._settings.stripe_webhook_secret is None:
            raise RuntimeError("Stripe webhook secret is not configured.")
        return self._settings.stripe_webhook_secret.get_secret_value()

    def _create_customer(
        self,
        *,
        api_key: str,
        user_id: str,
        customer_name: str,
        customer_email: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "name": customer_name,
            "email": customer_email,
            "metadata[user_id]": user_id,
            "metadata[purpose]": "subscription_setup",
        }
        for key, value in dict(metadata or {}).items():
            payload[f"metadata[{key}]"] = self._stringify_metadata_value(value)

        response = httpx.post(
            f"{self._settings.stripe_api_base_url.rstrip('/')}/v1/customers",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": idempotency_key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        if not str(data.get("id") or ""):
            raise RuntimeError("Stripe did not return a customer id.")
        return data

    @staticmethod
    def _parse_signature_header(signature_header: str) -> tuple[str, str]:
        timestamp: str | None = None
        signature: str | None = None
        for item in signature_header.split(","):
            key, _, value = item.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "t":
                timestamp = value
            elif key == "v1":
                signature = value
        if timestamp is None or signature is None:
            raise ValueError("Malformed Stripe-Signature header.")
        return timestamp, signature

    @staticmethod
    def _stringify_metadata_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        return str(value)

    @staticmethod
    def _epoch_to_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def minor_from_decimal_amount(amount: Decimal | str | float | int) -> int:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))
