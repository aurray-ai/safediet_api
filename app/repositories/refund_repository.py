from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.order import Refund, RefundStatus


class RefundRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_refund(
        self,
        *,
        order_id: str,
        user_id: str,
        status: RefundStatus,
        currency: str,
        refund_type: str,
        reason: str,
        wallet_refund_minor: int,
        card_refund_minor: int,
        line_items: list[dict[str, Any]],
        provider: str | None,
        provider_refund_id: str | None,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> Refund:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "order_id": order_id,
            "user_id": user_id,
            "status": status.value,
            "currency": currency,
            "refund_type": refund_type,
            "reason": reason,
            "wallet_refund_minor": int(wallet_refund_minor),
            "card_refund_minor": int(card_refund_minor),
            "line_items": line_items,
            "provider": provider,
            "provider_refund_id": provider_refund_id,
            "idempotency_key": idempotency_key,
            "metadata": dict(metadata or {}),
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_id(self, *, refund_id: str) -> Refund | None:
        document = self._collection.find_one({"_id": refund_id})
        return None if document is None else self._to_model(document)

    def get_by_idempotency_key(self, *, idempotency_key: str) -> Refund | None:
        document = self._collection.find_one({"idempotency_key": idempotency_key})
        return None if document is None else self._to_model(document)

    def list_for_order(self, *, order_id: str) -> list[Refund]:
        documents = list(self._collection.find({"order_id": order_id}).sort("created_at", DESCENDING))
        return [self._to_model(document) for document in documents]

    def list_for_user_order(self, *, user_id: str, order_id: str) -> list[Refund]:
        documents = list(
            self._collection.find({"user_id": user_id, "order_id": order_id}).sort("created_at", DESCENDING)
        )
        return [self._to_model(document) for document in documents]

    def mark_status(
        self,
        *,
        refund_id: str,
        status: RefundStatus,
        provider_refund_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Refund | None:
        payload: dict[str, Any] = {"status": status.value, "updated_at": datetime.now(timezone.utc)}
        if provider_refund_id is not None:
            payload["provider_refund_id"] = provider_refund_id
        if metadata is not None:
            payload["metadata"] = dict(metadata)
        self._collection.update_one({"_id": refund_id}, {"$set": payload})
        document = self._collection.find_one({"_id": refund_id})
        return None if document is None else self._to_model(document)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> Refund:
        return Refund(
            id=str(document["_id"]),
            order_id=str(document["order_id"]),
            user_id=str(document["user_id"]),
            status=RefundStatus(str(document.get("status") or RefundStatus.PENDING.value)),
            currency=str(document.get("currency") or "GBP"),
            refund_type=str(document.get("refund_type") or "full"),
            reason=str(document.get("reason") or ""),
            wallet_refund_minor=int(document.get("wallet_refund_minor") or 0),
            card_refund_minor=int(document.get("card_refund_minor") or 0),
            line_items=list(document.get("line_items") or []),
            provider=str(document["provider"]) if document.get("provider") else None,
            provider_refund_id=(
                str(document["provider_refund_id"])
                if document.get("provider_refund_id")
                else None
            ),
            idempotency_key=str(document.get("idempotency_key") or ""),
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
