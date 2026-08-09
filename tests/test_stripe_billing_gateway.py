from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from decimal import Decimal
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import SecretStr

from app.core.config import Settings
from app.services.stripe_billing_gateway import StripeBillingGateway


class StripeBillingGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            stripe_api_key=SecretStr("sk_test_123"),
            stripe_publishable_key="pk_test_123",
            stripe_webhook_secret=SecretStr("whsec_test"),
        )
        self.gateway = StripeBillingGateway(settings=self.settings)

    def test_create_wallet_topup_intent_posts_expected_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "id": "pi_test",
                    "client_secret": "pi_test_secret",
                    "amount": 2500,
                    "currency": "gbp",
                    "status": "requires_payment_method",
                },
            )

        with patch("app.services.stripe_billing_gateway.httpx.post", side_effect=fake_post):
            result = self.gateway.create_wallet_topup_intent(
                user_id="user-1",
                amount_minor=2500,
                currency="GBP",
                funding_method="card",
                idempotency_key="topup-user-1-2500",
                metadata={"note": "wallet"},
            )

        self.assertEqual(result.payment_intent_id, "pi_test")
        self.assertEqual(result.client_secret, "pi_test_secret")
        self.assertEqual(result.currency, "GBP")
        self.assertEqual(captured["args"][0], "https://api.stripe.com/v1/payment_intents")
        self.assertEqual(captured["kwargs"]["headers"]["Idempotency-Key"], "topup-user-1-2500")
        self.assertEqual(captured["kwargs"]["data"]["metadata[user_id]"], "user-1")

    def test_create_subscription_setup_intent_posts_expected_payload(self) -> None:
        captured: dict[str, dict[str, object]] = {}

        def fake_post(*args, **kwargs):
            url = args[0]
            captured[url] = {"args": args, "kwargs": kwargs}
            if url.endswith("/customers"):
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"id": "cus_test_1"},
                )
            if url.endswith("/setup_intents"):
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {
                        "id": "seti_test_1",
                        "client_secret": "seti_test_secret",
                        "currency": "gbp",
                        "status": "requires_payment_method",
                    },
                )
            raise AssertionError(url)

        with patch("app.services.stripe_billing_gateway.httpx.post", side_effect=fake_post):
            result = self.gateway.create_subscription_setup_intent(
                user_id="user-1",
                customer_name="Favour",
                customer_email="favour@example.com",
                plan_code="premium_monthly",
                price_minor=900,
                currency="GBP",
                idempotency_key="subscription-setup-user-1",
                metadata={"source": "profile"},
            )

        self.assertEqual(result.setup_intent_id, "seti_test_1")
        self.assertEqual(result.setup_intent_client_secret, "seti_test_secret")
        self.assertEqual(result.customer_id, "cus_test_1")
        self.assertEqual(captured["https://api.stripe.com/v1/customers"]["kwargs"]["headers"]["Idempotency-Key"], "subscription-setup-user-1:customer")
        self.assertEqual(captured["https://api.stripe.com/v1/setup_intents"]["kwargs"]["data"]["metadata[plan_code]"], "premium_monthly")
        self.assertEqual(captured["https://api.stripe.com/v1/setup_intents"]["kwargs"]["data"]["customer"], "cus_test_1")

    def test_create_subscription_from_setup_intent_posts_expected_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "id": "sub_test_1",
                    "status": "active",
                    "currency": "gbp",
                    "customer": "cus_test_1",
                    "latest_invoice": "in_test_1",
                    "start_date": 1719000000,
                    "current_period_end": 1719003600,
                    "items": {
                        "data": [
                            {
                                "price": {
                                    "unit_amount": 900,
                                }
                            }
                        ]
                    },
                },
            )

        with patch("app.services.stripe_billing_gateway.httpx.post", side_effect=fake_post):
            result = self.gateway.create_subscription_from_setup_intent(
                user_id="user-1",
                customer_id="cus_test_1",
                payment_method_id="pm_test_1",
                plan_code="premium_monthly",
                price_minor=900,
                currency="GBP",
                idempotency_key="stripe-subscription:seti_test_1",
                metadata={"source": "profile"},
            )

        self.assertEqual(result.subscription_id, "sub_test_1")
        self.assertEqual(result.customer_id, "cus_test_1")
        self.assertEqual(result.price_minor, 900)
        self.assertEqual(captured["args"][0], "https://api.stripe.com/v1/subscriptions")
        self.assertEqual(captured["kwargs"]["data"]["default_payment_method"], "pm_test_1")
        self.assertEqual(captured["kwargs"]["data"]["items[0][price_data][recurring][interval]"], "month")
        self.assertEqual(captured["kwargs"]["data"]["metadata[plan_code]"], "premium_monthly")

    def test_verify_and_decode_event_accepts_valid_signature(self) -> None:
        body = json.dumps({"id": "evt_1", "type": "payment_intent.succeeded"}).encode("utf-8")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signed_payload = f"{timestamp}.{body.decode('utf-8')}".encode("utf-8")
        signature = hmac.new(
            self.settings.stripe_webhook_secret.get_secret_value().encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        event = self.gateway.verify_and_decode_event(
            raw_body=body,
            signature_header=f"t={timestamp},v1={signature}",
        )

        self.assertEqual(event["id"], "evt_1")
        self.assertEqual(event["type"], "payment_intent.succeeded")

    def test_minor_from_decimal_amount_rounds_half_up(self) -> None:
        self.assertEqual(self.gateway.minor_from_decimal_amount(Decimal("12.345")), 1235)


if __name__ == "__main__":
    unittest.main()
