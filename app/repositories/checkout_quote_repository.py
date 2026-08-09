from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class CheckoutQuoteRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_quote(
        self,
        *,
        user_id: str,
        cart_id: str,
        store_id: str,
        currency: str,
        quote_status: str,
        line_items: list[dict[str, Any]],
        pricing_summary: dict[str, Any],
        wallet_contribution_minor: int,
        card_contribution_minor: int,
        address_snapshot: dict[str, Any],
        delivery_window_snapshot: dict[str, Any],
        route: str,
        message: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "cart_id": cart_id,
            "store_id": store_id,
            "currency": currency,
            "quote_status": quote_status,
            "line_items": line_items,
            "pricing_summary": pricing_summary,
            "wallet_contribution_minor": wallet_contribution_minor,
            "card_contribution_minor": card_contribution_minor,
            "address_snapshot": address_snapshot,
            "delivery_window_snapshot": delivery_window_snapshot,
            "route": route,
            "message": message,
            "expires_at": now + timedelta(seconds=ttl_seconds),
            "created_at": now,
        }
        self._collection.insert_one(document)
        return document

    def get_quote_for_user(self, *, user_id: str, quote_id: str) -> dict[str, Any] | None:
        return self._collection.find_one({"_id": quote_id, "user_id": user_id})

    def list_recent_for_user(self, *, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return list(self._collection.find({"user_id": user_id}).sort("created_at", DESCENDING).limit(limit))
