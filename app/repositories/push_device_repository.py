from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.collection import Collection

from app.models.push_device import PushDevice, PushEnvironment, PushPlatform


class PushDeviceRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def upsert_device(
        self,
        *,
        user_id: str,
        platform: PushPlatform,
        device_token: str,
        environment: PushEnvironment,
        locations: list[str],
        delivery_types: list[str],
        app_version: str | None,
        build_number: str | None,
        device_name: str | None,
    ) -> PushDevice:
        now = datetime.now(timezone.utc)
        normalized_locations = list(dict.fromkeys(location.strip() for location in locations if location.strip()))
        normalized_delivery_types = list(
            dict.fromkeys(delivery_type.strip() for delivery_type in delivery_types if delivery_type.strip())
        )
        query = {
            "user_id": user_id,
            "platform": platform.value,
            "device_token": device_token,
        }
        update = {
            "$set": {
                "environment": environment.value,
                "locations": normalized_locations,
                "delivery_types": normalized_delivery_types,
                "app_version": app_version,
                "build_number": build_number,
                "device_name": device_name,
                "is_active": True,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }
        self._collection.update_one(query, update, upsert=True)
        document = self._collection.find_one(query)
        if document is None:
            raise RuntimeError("Push device upsert did not return a document.")
        return self._to_model(document)

    def deactivate_device(
        self,
        *,
        user_id: str,
        platform: PushPlatform,
        device_token: str,
    ) -> None:
        self._collection.update_one(
            {
                "user_id": user_id,
                "platform": platform.value,
                "device_token": device_token,
            },
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    def list_active_devices(
        self,
        *,
        user_id: str,
        platform: PushPlatform | None = None,
        location: str | None = None,
        delivery_type: str | None = None,
    ) -> list[PushDevice]:
        query: dict[str, Any] = {
            "user_id": user_id,
            "is_active": True,
        }
        if platform is not None:
            query["platform"] = platform.value
        if location:
            query["$or"] = [
                {"locations": {"$size": 0}},
                {"locations": location},
            ]
        if delivery_type:
            delivery_query = [
                {"delivery_types": {"$size": 0}},
                {"delivery_types": delivery_type},
            ]
            if "$or" in query:
                query = {"$and": [query, {"$or": delivery_query}]}
            else:
                query["$or"] = delivery_query
        documents = list(self._collection.find(query).sort("updated_at", -1))
        return [self._to_model(document) for document in documents]

    @staticmethod
    def _to_model(document: dict[str, Any]) -> PushDevice:
        raw_id = document.get("_id")
        device_id = str(raw_id) if isinstance(raw_id, ObjectId) else str(raw_id)
        return PushDevice(
            id=device_id,
            user_id=str(document["user_id"]),
            platform=PushPlatform(str(document["platform"])),
            device_token=str(document["device_token"]),
            environment=PushEnvironment(str(document.get("environment", PushEnvironment.SANDBOX.value))),
            locations=[str(item) for item in document.get("locations", [])],
            delivery_types=[str(item) for item in document.get("delivery_types", [])],
            app_version=str(document["app_version"]) if document.get("app_version") else None,
            build_number=str(document["build_number"]) if document.get("build_number") else None,
            device_name=str(document["device_name"]) if document.get("device_name") else None,
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
