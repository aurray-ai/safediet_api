from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.billing import SubscriptionAccount, SubscriptionPlanCode, SubscriptionStatus


class SubscriptionAccountRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def get_by_user_id(self, *, user_id: str) -> SubscriptionAccount | None:
        document = self._collection.find_one({"user_id": user_id})
        return None if document is None else self._to_model(document)

    def ensure_default_for_user(self, *, user_id: str, currency: str = "GBP") -> SubscriptionAccount:
        existing = self.get_by_user_id(user_id=user_id)
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "plan_code": SubscriptionPlanCode.FREE.value,
            "status": SubscriptionStatus.INACTIVE.value,
            "provider": "stripe",
            "price_minor": 900,
            "currency": currency,
            "is_premium": False,
            "started_at": None,
            "expires_at": None,
            "renewal_at": None,
            "original_transaction_id": None,
            "latest_transaction_id": None,
            "provider_payload": {},
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def upsert_subscription(
        self,
        *,
        user_id: str,
        plan_code: SubscriptionPlanCode,
        status: SubscriptionStatus,
        provider: str,
        price_minor: int,
        currency: str,
        is_premium: bool,
        started_at: datetime | None,
        expires_at: datetime | None,
        renewal_at: datetime | None,
        original_transaction_id: str | None,
        latest_transaction_id: str | None,
        provider_payload: dict[str, Any],
    ) -> SubscriptionAccount:
        now = datetime.now(timezone.utc)
        existing = self._collection.find_one({"user_id": user_id})
        base_id = str(existing["_id"]) if existing is not None else uuid4().hex
        merged_provider_payload = dict(existing.get("provider_payload") or {}) if existing is not None else {}
        merged_provider_payload.update(dict(provider_payload or {}))
        document = {
            "_id": base_id,
            "user_id": user_id,
            "plan_code": plan_code.value,
            "status": status.value,
            "provider": provider,
            "price_minor": int(price_minor),
            "currency": currency,
            "is_premium": bool(is_premium),
            "started_at": started_at,
            "expires_at": expires_at,
            "renewal_at": renewal_at,
            "original_transaction_id": original_transaction_id,
            "latest_transaction_id": latest_transaction_id,
            "provider_payload": merged_provider_payload,
            "created_at": existing.get("created_at", now) if existing is not None else now,
            "updated_at": now,
        }
        self._collection.replace_one({"user_id": user_id}, document, upsert=True)
        return self._to_model(document)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> SubscriptionAccount:
        return SubscriptionAccount(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            plan_code=SubscriptionPlanCode(
                str(document.get("plan_code") or SubscriptionPlanCode.FREE.value)
            ),
            status=SubscriptionStatus(
                str(document.get("status") or SubscriptionStatus.INACTIVE.value)
            ),
            provider=str(document.get("provider") or "stripe"),
            price_minor=int(document.get("price_minor") or 0),
            currency=str(document.get("currency") or "GBP"),
            is_premium=bool(document.get("is_premium")),
            started_at=document.get("started_at"),
            expires_at=document.get("expires_at"),
            renewal_at=document.get("renewal_at"),
            original_transaction_id=(
                str(document["original_transaction_id"])
                if document.get("original_transaction_id") is not None
                else None
            ),
            latest_transaction_id=(
                str(document["latest_transaction_id"])
                if document.get("latest_transaction_id") is not None
                else None
            ),
            provider_payload=dict(document.get("provider_payload") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
