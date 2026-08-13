from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.student_verification import (
    StudentClaimSource,
    StudentVerification,
    StudentVerificationStatus,
)


class StudentVerificationRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def get_by_user_id(self, *, user_id: str) -> StudentVerification | None:
        document = self._collection.find_one({"user_id": user_id})
        return None if document is None else self._to_model(document)

    def find_by_unidays_reference_id(self, *, unidays_reference_id: str) -> StudentVerification | None:
        document = self._collection.find_one({"unidays_reference_id": unidays_reference_id})
        return None if document is None else self._to_model(document)

    def list_expiring_before(self, *, cutoff: datetime) -> list[StudentVerification]:
        cursor = self._collection.find(
            {
                "status": StudentVerificationStatus.VERIFIED.value,
                "expires_at": {"$ne": None, "$lte": cutoff},
            }
        )
        return [self._to_model(document) for document in cursor]

    def upsert(
        self,
        *,
        user_id: str,
        claims_student: bool,
        status: StudentVerificationStatus,
        unidays_reference_id: str | None,
        verification_method: str | None,
        started_at: datetime | None,
        verified_at: datetime | None,
        expires_at: datetime | None,
        needs_reconciliation: bool,
        source: StudentClaimSource,
    ) -> StudentVerification:
        now = datetime.now(timezone.utc)
        existing = self._collection.find_one({"user_id": user_id})
        base_id = str(existing["_id"]) if existing is not None else uuid4().hex
        document = {
            "_id": base_id,
            "user_id": user_id,
            "claims_student": bool(claims_student),
            "status": status.value,
            "unidays_reference_id": unidays_reference_id,
            "verification_method": verification_method,
            "started_at": started_at,
            "verified_at": verified_at,
            "expires_at": expires_at,
            "needs_reconciliation": bool(needs_reconciliation),
            "source": source.value,
            "created_at": existing.get("created_at", now) if existing is not None else now,
            "updated_at": now,
        }
        self._collection.replace_one({"user_id": user_id}, document, upsert=True)
        return self._to_model(document)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> StudentVerification:
        return StudentVerification(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            claims_student=bool(document.get("claims_student")),
            status=StudentVerificationStatus(
                str(document.get("status") or StudentVerificationStatus.NONE.value)
            ),
            unidays_reference_id=(
                str(document["unidays_reference_id"])
                if document.get("unidays_reference_id") is not None
                else None
            ),
            verification_method=(
                str(document["verification_method"])
                if document.get("verification_method") is not None
                else None
            ),
            started_at=document.get("started_at"),
            verified_at=document.get("verified_at"),
            expires_at=document.get("expires_at"),
            needs_reconciliation=bool(document.get("needs_reconciliation")),
            source=StudentClaimSource(str(document.get("source") or StudentClaimSource.REGISTRATION.value)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
