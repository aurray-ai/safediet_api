from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.address import UserDeliveryAddress


class AddressRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def list_for_user(self, *, user_id: str) -> list[UserDeliveryAddress]:
        documents = list(
            self._collection.find({"user_id": user_id}).sort(
                [("is_default", DESCENDING), ("updated_at", DESCENDING)]
            )
        )
        return [self._to_model(document) for document in documents]

    def get_for_user(self, *, user_id: str, address_id: str) -> UserDeliveryAddress | None:
        document = self._collection.find_one({"_id": address_id, "user_id": user_id})
        return None if document is None else self._to_model(document)

    def create_for_user(
        self,
        *,
        user_id: str,
        label: str,
        recipient_name: str,
        phone_number: str,
        line1: str,
        line2: str,
        city: str,
        state: str,
        postal_code: str,
        country: str,
        delivery_notes: str,
        is_default: bool,
    ) -> UserDeliveryAddress:
        now = datetime.now(timezone.utc)
        if is_default:
            self._collection.update_many({"user_id": user_id}, {"$set": {"is_default": False}})
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "label": label,
            "recipient_name": recipient_name,
            "phone_number": phone_number,
            "line1": line1,
            "line2": line2,
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country": country,
            "delivery_notes": delivery_notes,
            "is_default": is_default,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def update_for_user(
        self,
        *,
        user_id: str,
        address_id: str,
        payload: dict[str, Any],
    ) -> UserDeliveryAddress | None:
        existing = self._collection.find_one({"_id": address_id, "user_id": user_id})
        if existing is None:
            return None
        if bool(payload.get("is_default")):
            self._collection.update_many({"user_id": user_id}, {"$set": {"is_default": False}})
        self._collection.update_one(
            {"_id": address_id, "user_id": user_id},
            {
                "$set": {
                    **payload,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        updated = self._collection.find_one({"_id": address_id, "user_id": user_id})
        return None if updated is None else self._to_model(updated)

    def delete_for_user(self, *, user_id: str, address_id: str) -> bool:
        result = self._collection.delete_one({"_id": address_id, "user_id": user_id})
        return result.deleted_count > 0

    def set_default(self, *, user_id: str, address_id: str) -> UserDeliveryAddress | None:
        existing = self._collection.find_one({"_id": address_id, "user_id": user_id})
        if existing is None:
            return None
        self._collection.update_many({"user_id": user_id}, {"$set": {"is_default": False}})
        self._collection.update_one(
            {"_id": address_id, "user_id": user_id},
            {"$set": {"is_default": True, "updated_at": datetime.now(timezone.utc)}},
        )
        updated = self._collection.find_one({"_id": address_id, "user_id": user_id})
        return None if updated is None else self._to_model(updated)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> UserDeliveryAddress:
        return UserDeliveryAddress(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            label=str(document.get("label") or ""),
            recipient_name=str(document.get("recipient_name") or ""),
            phone_number=str(document.get("phone_number") or ""),
            line1=str(document.get("line1") or ""),
            line2=str(document.get("line2") or ""),
            city=str(document.get("city") or ""),
            state=str(document.get("state") or ""),
            postal_code=str(document.get("postal_code") or ""),
            country=AddressRepository._resolved_country(document),
            delivery_notes=str(document.get("delivery_notes") or ""),
            is_default=bool(document.get("is_default", False)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _resolved_country(document: dict[str, Any]) -> str:
        value = str(document.get("country") or "").strip()
        if value:
            return value

        legacy_value = str(document.get("country_code") or "").strip().upper()
        if legacy_value == "GB":
            return "United Kingdom"
        if legacy_value == "NG":
            return "Nigeria"
        if legacy_value == "IN":
            return "India"
        if legacy_value:
            return legacy_value
        return "United Kingdom"
