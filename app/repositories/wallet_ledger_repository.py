from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.billing import (
    WalletFundingMethod,
    WalletLedgerDirection,
    WalletLedgerEntry,
    WalletLedgerEntryType,
)


class WalletLedgerRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_entry(
        self,
        *,
        wallet_account_id: str,
        user_id: str,
        entry_type: WalletLedgerEntryType,
        direction: WalletLedgerDirection,
        amount_minor: int,
        currency: str,
        reference_type: str,
        reference_id: str,
        funding_method: WalletFundingMethod | None,
        idempotency_key: str | None,
        metadata: dict[str, Any],
    ) -> WalletLedgerEntry:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "wallet_account_id": wallet_account_id,
            "user_id": user_id,
            "entry_type": entry_type.value,
            "direction": direction.value,
            "amount_minor": int(amount_minor),
            "currency": currency,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "funding_method": funding_method.value if funding_method is not None else None,
            "metadata": dict(metadata or {}),
            "created_at": now,
        }
        if idempotency_key is not None:
            document["idempotency_key"] = str(idempotency_key)
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_idempotency_key(self, *, idempotency_key: str) -> WalletLedgerEntry | None:
        document = self._collection.find_one({"idempotency_key": idempotency_key})
        return None if document is None else self._to_model(document)

    def get_by_reference_id(
        self,
        *,
        reference_type: str,
        reference_id: str,
    ) -> WalletLedgerEntry | None:
        document = self._collection.find_one(
            {
                "reference_type": reference_type,
                "reference_id": reference_id,
            }
        )
        return None if document is None else self._to_model(document)

    def list_for_user(
        self,
        *,
        user_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[WalletLedgerEntry], str | None]:
        query: dict[str, Any] = {"user_id": user_id}
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]

        documents = list(
            self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return [self._to_model(document) for document in page], next_cursor

    @staticmethod
    def _encode_cursor(document: dict[str, Any]) -> str:
        created_at = document["created_at"]
        created_at_iso = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return f"{created_at_iso}|{document['_id']}"

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        created_at_raw, entry_id = cursor.split("|", 1)
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        return created_at, entry_id

    @staticmethod
    def _to_model(document: dict[str, Any]) -> WalletLedgerEntry:
        raw_funding_method = document.get("funding_method")
        return WalletLedgerEntry(
            id=str(document["_id"]),
            wallet_account_id=str(document["wallet_account_id"]),
            user_id=str(document["user_id"]),
            entry_type=WalletLedgerEntryType(
                str(document.get("entry_type") or WalletLedgerEntryType.TOPUP_CREDIT.value)
            ),
            direction=WalletLedgerDirection(
                str(document.get("direction") or WalletLedgerDirection.CREDIT.value)
            ),
            amount_minor=int(document.get("amount_minor") or 0),
            currency=str(document.get("currency") or "GBP"),
            reference_type=str(document.get("reference_type") or ""),
            reference_id=str(document.get("reference_id") or ""),
            funding_method=(
                WalletFundingMethod(str(raw_funding_method))
                if raw_funding_method in WalletFundingMethod._value2member_map_
                else None
            ),
            idempotency_key=(
                str(document["idempotency_key"])
                if document.get("idempotency_key") is not None
                else None
            ),
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
        )
