from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.models.invitation import Invitation, InvitationStatus, InvitationType


class InvitationRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create(
        self,
        *,
        invitation_type: InvitationType,
        invited_by_user_id: str,
        invitee_email: str,
        invitee_user_id: str | None,
        display_name: str,
        token_hash: str,
        expires_at: datetime,
        context: dict[str, Any],
    ) -> Invitation:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "invitation_type": invitation_type.value,
            "invited_by_user_id": invited_by_user_id,
            "invitee_email": invitee_email,
            "invitee_user_id": invitee_user_id,
            "display_name": display_name,
            "status": InvitationStatus.PENDING.value,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "accepted_at": None,
            "accepted_by_user_id": None,
            "context": dict(context),
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_id(self, *, invitation_id: str) -> Invitation | None:
        document = self._collection.find_one({"_id": invitation_id})
        return None if document is None else self._to_model(document)

    def list_by_type(
        self,
        *,
        invitation_type: InvitationType,
        context_filters: dict[str, Any] | None = None,
        statuses: list[InvitationStatus] | None = None,
    ) -> list[Invitation]:
        query: dict[str, Any] = {"invitation_type": invitation_type.value}
        for key, value in (context_filters or {}).items():
            query[f"context.{key}"] = value
        if statuses:
            query["status"] = {"$in": [status.value for status in statuses]}
        documents = list(
            self._collection.find(query).sort([("created_at", DESCENDING), ("_id", ASCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def get_pending_by_type_and_email(
        self,
        *,
        invitation_type: InvitationType,
        invitee_email: str,
        context_filters: dict[str, Any] | None,
        now: datetime,
    ) -> Invitation | None:
        query: dict[str, Any] = {
            "invitation_type": invitation_type.value,
            "invitee_email": invitee_email,
            "status": InvitationStatus.PENDING.value,
            "expires_at": {"$gt": now},
        }
        for key, value in (context_filters or {}).items():
            query[f"context.{key}"] = value
        document = self._collection.find_one(query)
        return None if document is None else self._to_model(document)

    def find_active_by_token_hash(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> Invitation | None:
        document = self._collection.find_one(
            {
                "token_hash": token_hash,
                "status": InvitationStatus.PENDING.value,
                "expires_at": {"$gt": now},
            }
        )
        return None if document is None else self._to_model(document)

    def mark_accepted(
        self,
        *,
        invitation_id: str,
        accepted_by_user_id: str,
    ) -> Invitation | None:
        now = datetime.now(timezone.utc)
        self._collection.update_one(
            {"_id": invitation_id},
            {
                "$set": {
                    "status": InvitationStatus.ACCEPTED.value,
                    "accepted_at": now,
                    "accepted_by_user_id": accepted_by_user_id,
                    "updated_at": now,
                }
            },
        )
        return self.get_by_id(invitation_id=invitation_id)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> Invitation:
        return Invitation(
            id=str(document["_id"]),
            invitation_type=InvitationType(str(document["invitation_type"])),
            invited_by_user_id=str(document["invited_by_user_id"]),
            invitee_email=str(document["invitee_email"]),
            invitee_user_id=(
                str(document["invitee_user_id"])
                if document.get("invitee_user_id") is not None
                else None
            ),
            display_name=str(document.get("display_name") or ""),
            status=InvitationStatus(str(document.get("status") or InvitationStatus.PENDING.value)),
            token_hash=str(document["token_hash"]),
            expires_at=document["expires_at"],
            accepted_at=document.get("accepted_at"),
            accepted_by_user_id=(
                str(document["accepted_by_user_id"])
                if document.get("accepted_by_user_id") is not None
                else None
            ),
            context=dict(document.get("context") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
