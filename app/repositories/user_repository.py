from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING
from pymongo.collection import Collection

from app.models.user import StaffType, User, UserType


class UserRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def find_by_email(self, email: str) -> User | None:
        document = self._collection.find_one({"email": email})
        if document is None:
            return None
        return self._to_model(document)

    def find_by_id(self, user_id: str) -> User | None:
        lookup_candidates: list[object] = [user_id]

        if ObjectId.is_valid(user_id):
            lookup_candidates.insert(0, ObjectId(user_id))

        document = self._collection.find_one({"_id": {"$in": lookup_candidates}})
        if document is None:
            return None
        return self._to_model(document)

    def create(
        self,
        *,
        name: str,
        email: str,
        password_hash: str,
        user_types: list[UserType],
        user_configuration: dict[str, Any],
        staff_type: StaffType | None = None,
    ) -> User:
        payload = {
            "name": name,
            "email": email,
            "password_hash": password_hash,
            "user_types": [user_type.value for user_type in user_types],
            "user_configuration": user_configuration,
            "created_at": datetime.now(timezone.utc),
            "staff_type": staff_type.value if staff_type is not None else None,
        }
        result = self._collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return self._to_model(payload)

    def list_users(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        user_type: UserType | None = None,
    ) -> tuple[list[User], int]:
        query: dict[str, Any] = {}
        if user_type is not None:
            query["user_types"] = user_type.value
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
            ]

        skip = (page - 1) * page_size
        documents = list(
            self._collection.find(query)
            .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
            .skip(skip)
            .limit(page_size)
        )
        total = self._collection.count_documents(query)
        return [self._to_model(document) for document in documents], total

    def list_by_ids(self, user_ids: list[str]) -> list[User]:
        if not user_ids:
            return []

        lookup_candidates: list[object] = list(user_ids)
        for user_id in user_ids:
            if ObjectId.is_valid(user_id):
                lookup_candidates.append(ObjectId(user_id))

        documents = list(self._collection.find({"_id": {"$in": lookup_candidates}}))
        return [self._to_model(document) for document in documents]

    def update_user_configuration(
        self,
        *,
        user_id: str,
        user_configuration: dict[str, Any],
    ) -> User | None:
        lookup_candidates: list[object] = [user_id]
        if ObjectId.is_valid(user_id):
            lookup_candidates.insert(0, ObjectId(user_id))

        self._collection.update_one(
            {"_id": {"$in": lookup_candidates}},
            {
                "$set": {
                    "user_configuration": dict(user_configuration),
                }
            },
        )
        return self.find_by_id(user_id)

    def update_user_types(
        self,
        *,
        user_id: str,
        user_types: list[UserType],
    ) -> User | None:
        lookup_candidates: list[object] = [user_id]
        if ObjectId.is_valid(user_id):
            lookup_candidates.insert(0, ObjectId(user_id))

        self._collection.update_one(
            {"_id": {"$in": lookup_candidates}},
            {"$set": {"user_types": [user_type.value for user_type in user_types]}},
        )
        return self.find_by_id(user_id)

    def update_staff_profile(
        self,
        *,
        user_id: str,
        user_types: list[UserType],
        staff_type: StaffType | None,
    ) -> User | None:
        lookup_candidates: list[object] = [user_id]
        if ObjectId.is_valid(user_id):
            lookup_candidates.insert(0, ObjectId(user_id))

        self._collection.update_one(
            {"_id": {"$in": lookup_candidates}},
            {
                "$set": {
                    "user_types": [user_type.value for user_type in user_types],
                    "staff_type": staff_type.value if staff_type is not None else None,
                }
            },
        )
        return self.find_by_id(user_id)

    def update_password_hash(
        self,
        *,
        user_id: str,
        password_hash: str,
    ) -> User | None:
        lookup_candidates: list[object] = [user_id]
        if ObjectId.is_valid(user_id):
            lookup_candidates.insert(0, ObjectId(user_id))

        self._collection.update_one(
            {"_id": {"$in": lookup_candidates}},
            {"$set": {"password_hash": password_hash}},
        )
        return self.find_by_id(user_id)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> User:
        raw_id = document.get("_id")
        user_id = str(raw_id) if isinstance(raw_id, ObjectId) else str(raw_id)
        return User(
            id=user_id,
            name=str(document.get("name", "")),
            email=str(document["email"]),
            password_hash=str(document["password_hash"]),
            user_types=[
                UserType(raw_user_type)
                for raw_user_type in document.get("user_types", [UserType.CUSTOMER.value])
            ],
            user_configuration=dict(document.get("user_configuration", {})),
            created_at=document["created_at"],
            staff_type=(
                StaffType(document["staff_type"]) if document.get("staff_type") is not None else None
            ),
        )
