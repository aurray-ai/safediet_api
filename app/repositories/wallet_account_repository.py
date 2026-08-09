from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.billing import WalletAccount, WalletAccountStatus


class WalletAccountRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def get_by_user_id(self, *, user_id: str) -> WalletAccount | None:
        document = self._collection.find_one({"user_id": user_id})
        return None if document is None else self._to_model(document)

    def ensure_default_for_user(self, *, user_id: str, currency: str = "GBP") -> WalletAccount:
        existing = self.get_by_user_id(user_id=user_id)
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "currency": currency,
            "status": WalletAccountStatus.ACTIVE.value,
            "available_balance_minor": 0,
            "held_balance_minor": 0,
            "lifetime_credited_minor": 0,
            "lifetime_debited_minor": 0,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def apply_balance_delta(
        self,
        *,
        wallet_account_id: str,
        available_delta_minor: int = 0,
        held_delta_minor: int = 0,
        credited_delta_minor: int = 0,
        debited_delta_minor: int = 0,
    ) -> WalletAccount:
        now = datetime.now(timezone.utc)
        self._collection.update_one(
            {"_id": wallet_account_id},
            {
                "$inc": {
                    "available_balance_minor": int(available_delta_minor),
                    "held_balance_minor": int(held_delta_minor),
                    "lifetime_credited_minor": int(credited_delta_minor),
                    "lifetime_debited_minor": int(debited_delta_minor),
                },
                "$set": {"updated_at": now},
            },
        )
        document = self._collection.find_one({"_id": wallet_account_id})
        if document is None:
            raise RuntimeError("Wallet account not found after balance update.")
        return self._to_model(document)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> WalletAccount:
        return WalletAccount(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            currency=str(document.get("currency") or "GBP"),
            status=WalletAccountStatus(
                str(document.get("status") or WalletAccountStatus.ACTIVE.value)
            ),
            available_balance_minor=int(document.get("available_balance_minor") or 0),
            held_balance_minor=int(document.get("held_balance_minor") or 0),
            lifetime_credited_minor=int(document.get("lifetime_credited_minor") or 0),
            lifetime_debited_minor=int(document.get("lifetime_debited_minor") or 0),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

