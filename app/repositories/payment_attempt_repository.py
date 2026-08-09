from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.order import PaymentAttempt, PaymentAttemptStatus


class PaymentAttemptRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_attempt(
        self,
        *,
        order_id: str,
        user_id: str,
        quote_id: str,
        status: PaymentAttemptStatus,
        currency: str,
        wallet_hold_amount_minor: int,
        wallet_capture_amount_minor: int,
        card_amount_minor: int,
        provider: str,
        provider_payment_intent_id: str | None,
        client_secret: str | None,
        idempotency_key: str,
        provider_payload: dict[str, Any],
    ) -> PaymentAttempt:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "order_id": order_id,
            "user_id": user_id,
            "quote_id": quote_id,
            "status": status.value,
            "currency": currency,
            "wallet_hold_amount_minor": int(wallet_hold_amount_minor),
            "wallet_capture_amount_minor": int(wallet_capture_amount_minor),
            "card_amount_minor": int(card_amount_minor),
            "provider": provider,
            "client_secret": client_secret,
            "idempotency_key": idempotency_key,
            "provider_payload": dict(provider_payload or {}),
            "created_at": now,
            "updated_at": now,
        }
        if provider_payment_intent_id is not None:
            document["provider_payment_intent_id"] = str(provider_payment_intent_id)
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_id(self, *, attempt_id: str) -> PaymentAttempt | None:
        document = self._collection.find_one({"_id": attempt_id})
        return None if document is None else self._to_model(document)

    def get_by_idempotency_key(self, *, idempotency_key: str) -> PaymentAttempt | None:
        document = self._collection.find_one({"idempotency_key": idempotency_key})
        return None if document is None else self._to_model(document)

    def get_by_provider_payment_intent_id(
        self,
        *,
        provider: str,
        provider_payment_intent_id: str,
    ) -> PaymentAttempt | None:
        document = self._collection.find_one(
            {
                "provider": provider,
                "provider_payment_intent_id": provider_payment_intent_id,
            }
        )
        return None if document is None else self._to_model(document)

    def mark_status(
        self,
        *,
        attempt_id: str,
        status: PaymentAttemptStatus,
        provider_payload: dict[str, Any] | None = None,
    ) -> PaymentAttempt | None:
        self._collection.update_one(
            {"_id": attempt_id},
            {
                "$set": {
                    "status": status.value,
                    "provider_payload": dict(provider_payload or {}),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        document = self._collection.find_one({"_id": attempt_id})
        return None if document is None else self._to_model(document)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> PaymentAttempt:
        return PaymentAttempt(
            id=str(document["_id"]),
            order_id=str(document["order_id"]),
            user_id=str(document["user_id"]),
            quote_id=str(document.get("quote_id") or ""),
            status=PaymentAttemptStatus(str(document.get("status") or PaymentAttemptStatus.PENDING.value)),
            currency=str(document.get("currency") or "GBP"),
            wallet_hold_amount_minor=int(document.get("wallet_hold_amount_minor") or 0),
            wallet_capture_amount_minor=int(document.get("wallet_capture_amount_minor") or 0),
            card_amount_minor=int(document.get("card_amount_minor") or 0),
            provider=str(document.get("provider") or "stripe"),
            provider_payment_intent_id=(
                str(document["provider_payment_intent_id"])
                if document.get("provider_payment_intent_id")
                else None
            ),
            client_secret=str(document["client_secret"]) if document.get("client_secret") else None,
            idempotency_key=str(document.get("idempotency_key") or ""),
            provider_payload=dict(document.get("provider_payload") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
