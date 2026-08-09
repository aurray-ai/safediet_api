from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        request_ip: str | None,
        user_agent: str | None,
    ) -> PasswordResetToken:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "used_at": None,
            "created_at": now,
            "request_ip": request_ip,
            "user_agent": user_agent,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def find_active_by_token_hash(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> PasswordResetToken | None:
        document = self._collection.find_one(
            {
                "token_hash": token_hash,
                "used_at": None,
                "expires_at": {"$gt": now},
            }
        )
        return None if document is None else self._to_model(document)

    def mark_used(self, *, token_id: str) -> None:
        self._collection.update_one(
            {"_id": token_id},
            {"$set": {"used_at": datetime.now(timezone.utc)}},
        )

    def invalidate_for_user(self, *, user_id: str) -> None:
        self._collection.update_many(
            {
                "user_id": user_id,
                "used_at": None,
            },
            {"$set": {"used_at": datetime.now(timezone.utc)}},
        )

    @staticmethod
    def _to_model(document: dict[str, Any]) -> PasswordResetToken:
        return PasswordResetToken(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            token_hash=str(document["token_hash"]),
            expires_at=document["expires_at"],
            used_at=document.get("used_at"),
            created_at=document["created_at"],
            request_ip=(
                str(document["request_ip"])
                if document.get("request_ip") is not None
                else None
            ),
            user_agent=(
                str(document["user_agent"])
                if document.get("user_agent") is not None
                else None
            ),
        )
