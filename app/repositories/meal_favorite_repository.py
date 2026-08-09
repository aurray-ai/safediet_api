from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from app.models.meal_favorite import MealFavorite


class MealFavoriteRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def add(self, *, user_id: str, meal_id: str) -> MealFavorite:
        existing = self._collection.find_one({"user_id": user_id, "meal_id": meal_id})
        if existing is not None:
            return self._to_model(existing)
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "meal_id": meal_id,
            "created_at": now,
        }
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError:
            existing = self._collection.find_one({"user_id": user_id, "meal_id": meal_id})
            if existing is not None:
                return self._to_model(existing)
            raise
        return self._to_model(document)

    def remove(self, *, user_id: str, meal_id: str) -> None:
        self._collection.delete_one({"user_id": user_id, "meal_id": meal_id})

    def is_favorited(self, *, user_id: str, meal_id: str) -> bool:
        return self._collection.find_one({"user_id": user_id, "meal_id": meal_id}) is not None

    def list_favorited_meal_ids(self, *, user_id: str) -> set[str]:
        documents = self._collection.find({"user_id": user_id}, {"meal_id": 1})
        return {str(document["meal_id"]) for document in documents}

    @staticmethod
    def _to_model(document: dict[str, Any]) -> MealFavorite:
        return MealFavorite(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            meal_id=str(document["meal_id"]),
            created_at=document["created_at"],
        )
