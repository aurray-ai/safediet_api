from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING
from pymongo.collection import Collection

from app.models.meal import MealType
from app.models.user_meal_usage import UserMealUsageEntry


class UserMealUsageRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def replace_day_entries(
        self,
        *,
        user_id: str,
        effective_date: date,
        saved_plan_id: str,
        source_snapshot_id: str,
        source_conversation_id: str,
        entries: list[dict[str, Any]],
    ) -> list[UserMealUsageEntry]:
        self._collection.delete_many(
            {
                "user_id": user_id,
                "effective_date": effective_date.isoformat(),
            }
        )

        if not entries:
            return []

        now = datetime.now(timezone.utc)
        week_start = effective_date - timedelta(days=effective_date.weekday())
        week_end = week_start + timedelta(days=6)
        documents: list[dict[str, Any]] = []
        for entry in entries:
            documents.append(
                {
                    "_id": uuid4().hex,
                    "user_id": user_id,
                    "saved_plan_id": saved_plan_id,
                    "source_snapshot_id": source_snapshot_id,
                    "source_conversation_id": source_conversation_id,
                    "effective_date": effective_date.isoformat(),
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "view_mode": str(entry.get("view_mode") or "day"),
                    "meal_slot": str(entry["meal_slot"]),
                    "meal_name": str(entry.get("meal_name") or ""),
                    "meal_source": entry.get("meal_source"),
                    "calories": int(entry.get("calories") or 0),
                    "protein_g": float(entry.get("protein_g") or 0),
                    "carbs_g": float(entry.get("carbs_g") or 0),
                    "fat_g": float(entry.get("fat_g") or 0),
                    "estimated_cost": (
                        float(entry["estimated_cost"])
                        if entry.get("estimated_cost") is not None
                        else None
                    ),
                    "currency_code": entry.get("currency_code"),
                    "status": str(entry.get("status") or "planned"),
                    "created_at": now,
                    "updated_at": now,
                }
            )

        self._collection.insert_many(documents)
        return [self._to_model(document) for document in documents]

    def list_entries_between(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> list[UserMealUsageEntry]:
        documents = list(
            self._collection.find(
                {
                    "user_id": user_id,
                    "effective_date": {
                        "$gte": start_date.isoformat(),
                        "$lte": end_date.isoformat(),
                    },
                }
            ).sort(
                [
                    ("effective_date", ASCENDING),
                    ("meal_slot", ASCENDING),
                    ("updated_at", ASCENDING),
                ]
            )
        )
        return [self._to_model(document) for document in documents]

    @staticmethod
    def _to_model(document: dict[str, Any]) -> UserMealUsageEntry:
        return UserMealUsageEntry(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            saved_plan_id=str(document["saved_plan_id"]),
            source_snapshot_id=str(document["source_snapshot_id"]),
            source_conversation_id=str(document["source_conversation_id"]),
            effective_date=date.fromisoformat(str(document["effective_date"])),
            week_start=date.fromisoformat(str(document["week_start"])),
            week_end=date.fromisoformat(str(document["week_end"])),
            view_mode=str(document.get("view_mode") or "day"),
            meal_slot=MealType(str(document["meal_slot"])),
            meal_name=str(document.get("meal_name") or ""),
            meal_source=str(document["meal_source"]) if document.get("meal_source") else None,
            calories=int(document.get("calories") or 0),
            protein_g=float(document.get("protein_g") or 0),
            carbs_g=float(document.get("carbs_g") or 0),
            fat_g=float(document.get("fat_g") or 0),
            estimated_cost=(
                float(document["estimated_cost"])
                if document.get("estimated_cost") is not None
                else None
            ),
            currency_code=str(document["currency_code"]) if document.get("currency_code") else None,
            status=str(document.get("status") or "planned"),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
