from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING
from pymongo.collection import Collection

from app.models.household import HouseholdMember, HouseholdMemberRole, HouseholdMemberStatus


class HouseholdMemberRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create(
        self,
        *,
        household_id: str,
        user_id: str,
        display_name: str,
        role: HouseholdMemberRole,
        status: HouseholdMemberStatus = HouseholdMemberStatus.ACTIVE,
        share_weight: int = 1,
    ) -> HouseholdMember:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "household_id": household_id,
            "user_id": user_id,
            "display_name": display_name,
            "role": role.value,
            "status": status.value,
            "share_weight": int(share_weight),
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_id(self, *, member_id: str) -> HouseholdMember | None:
        document = self._collection.find_one({"_id": member_id})
        return None if document is None else self._to_model(document)

    def get_by_household_and_user_id(
        self,
        *,
        household_id: str,
        user_id: str,
    ) -> HouseholdMember | None:
        document = self._collection.find_one(
            {
                "household_id": household_id,
                "user_id": user_id,
            }
        )
        return None if document is None else self._to_model(document)

    def get_active_by_user_id(self, *, user_id: str) -> HouseholdMember | None:
        document = self._collection.find_one(
            {
                "user_id": user_id,
                "status": HouseholdMemberStatus.ACTIVE.value,
            }
        )
        return None if document is None else self._to_model(document)

    def get_active_by_user_id_and_household_id(
        self,
        *,
        user_id: str,
        household_id: str,
    ) -> HouseholdMember | None:
        document = self._collection.find_one(
            {
                "user_id": user_id,
                "household_id": household_id,
                "status": HouseholdMemberStatus.ACTIVE.value,
            }
        )
        return None if document is None else self._to_model(document)

    def list_active_by_user_id(self, *, user_id: str) -> list[HouseholdMember]:
        documents = list(
            self._collection.find(
                {
                    "user_id": user_id,
                    "status": HouseholdMemberStatus.ACTIVE.value,
                }
            ).sort([("created_at", ASCENDING), ("_id", ASCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def list_by_household_id(
        self,
        *,
        household_id: str,
        include_inactive: bool = False,
    ) -> list[HouseholdMember]:
        query: dict[str, Any] = {"household_id": household_id}
        if not include_inactive:
            query["status"] = HouseholdMemberStatus.ACTIVE.value
        documents = list(
            self._collection.find(query).sort([("created_at", ASCENDING), ("_id", ASCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def update_share_weight(
        self,
        *,
        member_id: str,
        share_weight: int,
    ) -> HouseholdMember | None:
        self._collection.update_one(
            {"_id": member_id},
            {
                "$set": {
                    "share_weight": int(share_weight),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return self.get_by_id(member_id=member_id)

    def deactivate(self, *, member_id: str) -> HouseholdMember | None:
        self._collection.update_one(
            {"_id": member_id},
            {
                "$set": {
                    "status": HouseholdMemberStatus.INACTIVE.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return self.get_by_id(member_id=member_id)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> HouseholdMember:
        return HouseholdMember(
            id=str(document["_id"]),
            household_id=str(document["household_id"]),
            user_id=str(document["user_id"]),
            display_name=str(document.get("display_name") or ""),
            role=HouseholdMemberRole(
                str(document.get("role") or HouseholdMemberRole.ADULT.value)
            ),
            status=HouseholdMemberStatus(
                str(document.get("status") or HouseholdMemberStatus.ACTIVE.value)
            ),
            share_weight=max(int(document.get("share_weight") or 1), 1),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
