from __future__ import annotations

import unittest

from app.models.order import PaymentAttemptStatus
from app.repositories.payment_attempt_repository import PaymentAttemptRepository


class CapturingCollection:
    def __init__(self) -> None:
        self.inserted: list[dict] = []

    def insert_one(self, document: dict) -> None:
        self.inserted.append(document)


class PaymentAttemptRepositoryTests(unittest.TestCase):
    def test_create_attempt_omits_null_provider_payment_intent_id(self) -> None:
        collection = CapturingCollection()
        repository = PaymentAttemptRepository(collection)  # type: ignore[arg-type]

        attempt = repository.create_attempt(
            order_id="order-1",
            user_id="user-1",
            quote_id="quote-1",
            status=PaymentAttemptStatus.SUCCEEDED,
            currency="GBP",
            wallet_hold_amount_minor=2500,
            wallet_capture_amount_minor=2500,
            card_amount_minor=0,
            provider="wallet",
            provider_payment_intent_id=None,
            client_secret=None,
            idempotency_key="idem-1",
            provider_payload={"status": "succeeded"},
        )

        self.assertIsNone(attempt.provider_payment_intent_id)
        self.assertEqual(len(collection.inserted), 1)
        self.assertNotIn("provider_payment_intent_id", collection.inserted[0])


if __name__ == "__main__":
    unittest.main()
