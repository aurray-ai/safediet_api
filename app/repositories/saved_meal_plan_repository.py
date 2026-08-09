from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.saved_meal_plan import SavedMealPlan


class SavedMealPlanRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def upsert_saved_plan(
        self,
        *,
        user_id: str,
        title: str,
        status: str = "saved",
        view_mode: str,
        effective_date: date | None,
        meal_type: str | None,
        country_code: str | None,
        planned_meals: list[dict[str, Any]],
        plan_payload: dict[str, Any],
        requested_culture: str | None,
        user_goal: str | None,
        source_snapshot_id: str,
        source_conversation_id: str,
        agent_type: str,
        plan_scope: str | None = None,
        week_start: date | None = None,
        week_end: date | None = None,
        day_index: int | None = None,
        parent_saved_plan_id: str | None = None,
        source_saved_plan_id: str | None = None,
        linked_day_plan_ids: list[str] | None = None,
    ) -> SavedMealPlan:
        now = datetime.now(timezone.utc)
        query = {
            "user_id": user_id,
            "source_snapshot_id": source_snapshot_id,
        }
        document_id = uuid4().hex
        self._collection.update_one(
            query,
            {
                "$set": {
                    "user_id": user_id,
                    "source_snapshot_id": source_snapshot_id,
                    "title": title,
                    "status": str(status or "saved"),
                    "view_mode": view_mode,
                    "plan_scope": plan_scope,
                    "effective_date": effective_date.isoformat() if effective_date else None,
                    "week_start": week_start.isoformat() if week_start else None,
                    "week_end": week_end.isoformat() if week_end else None,
                    "day_index": day_index,
                    "parent_saved_plan_id": parent_saved_plan_id,
                    "source_saved_plan_id": source_saved_plan_id,
                    "linked_day_plan_ids": list(linked_day_plan_ids or []),
                    "meal_type": meal_type,
                    "country_code": country_code,
                    "planned_meals": planned_meals,
                    "plan_payload": plan_payload,
                    "requested_culture": requested_culture,
                    "user_goal": user_goal,
                    "source_conversation_id": source_conversation_id,
                    "agent_type": agent_type,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "_id": document_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        document = self._collection.find_one(query)
        if document is None:
            raise RuntimeError("Saved meal plan upsert did not return a document.")
        return self._to_model(document)

    def list_saved_plans(
        self,
        *,
        user_id: str | None = None,
        view_mode: str | None = None,
        effective_date: date | None = None,
        status: str | None = None,
        updated_before: datetime | None = None,
        limit: int = 20,
    ) -> tuple[list[SavedMealPlan], int]:
        query: dict[str, Any] = {}
        if user_id is not None:
            query["user_id"] = user_id
        if view_mode:
            query["view_mode"] = view_mode
        if effective_date is not None:
            query["effective_date"] = effective_date.isoformat()
        if status is not None:
            query["status"] = status
        if updated_before is not None:
            query["updated_at"] = {"$lt": updated_before}
        total = self._collection.count_documents(query)
        documents = list(
            self._collection.find(query)
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return [self._to_model(document) for document in documents], total

    def get_saved_plan(self, *, user_id: str, saved_plan_id: str) -> SavedMealPlan | None:
        document = self._collection.find_one({"_id": saved_plan_id, "user_id": user_id})
        return None if document is None else self._to_model(document)

    def get_latest_draft_derived_from_saved_plan(
        self,
        *,
        user_id: str,
        source_saved_plan_id: str,
        view_mode: str,
        effective_date: date | None = None,
        week_start: date | None = None,
        week_end: date | None = None,
    ) -> SavedMealPlan | None:
        query: dict[str, Any] = {
            "user_id": user_id,
            "status": "draft",
            "source_saved_plan_id": source_saved_plan_id,
            "view_mode": view_mode,
        }
        if effective_date is not None:
            query["effective_date"] = effective_date.isoformat()
        if week_start is not None:
            query["week_start"] = week_start.isoformat()
        if week_end is not None:
            query["week_end"] = week_end.isoformat()
        document = self._collection.find_one(query, sort=[("updated_at", DESCENDING), ("_id", DESCENDING)])
        return None if document is None else self._to_model(document)

    def get_saved_day_plan_for_date(
        self,
        *,
        user_id: str,
        effective_date: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        query: dict[str, Any] = {
            "user_id": user_id,
            "view_mode": "day",
            "effective_date": effective_date.isoformat(),
        }
        if allowed_statuses:
            query["status"] = {"$in": [str(item) for item in allowed_statuses]}
        document = self._collection.find_one(query, sort=[("updated_at", DESCENDING), ("_id", DESCENDING)])
        return None if document is None else self._to_model(document)

    def get_saved_weekly_plan_for_week(
        self,
        *,
        user_id: str,
        week_start: date,
        week_end: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        query: dict[str, Any] = {
            "user_id": user_id,
            "view_mode": "week",
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
        }
        if allowed_statuses:
            query["status"] = {"$in": [str(item) for item in allowed_statuses]}
        document = self._collection.find_one(query, sort=[("updated_at", DESCENDING), ("_id", DESCENDING)])
        return None if document is None else self._to_model(document)

    def get_saved_weekly_plan_covering_date(
        self,
        *,
        user_id: str,
        target_date: date,
        allowed_statuses: list[str] | None = None,
    ) -> SavedMealPlan | None:
        target = target_date.isoformat()
        query: dict[str, Any] = {
            "user_id": user_id,
            "view_mode": "week",
            "week_start": {"$lte": target},
            "week_end": {"$gte": target},
        }
        if allowed_statuses:
            query["status"] = {"$in": [str(item) for item in allowed_statuses]}
        document = self._collection.find_one(query, sort=[("updated_at", DESCENDING), ("_id", DESCENDING)])
        return None if document is None else self._to_model(document)

    def list_saved_weekly_plans_overlapping_range(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
        limit: int = 100,
    ) -> list[SavedMealPlan]:
        start = start_date.isoformat()
        end = end_date.isoformat()
        documents = list(
            self._collection.find(
                {
                    "user_id": user_id,
                    "view_mode": "week",
                    "week_start": {"$lte": end},
                    "week_end": {"$gte": start},
                }
            )
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return [self._to_model(document) for document in documents]

    def list_saved_day_plans_for_effective_dates(
        self,
        *,
        effective_dates: list[date],
        limit: int = 500,
    ) -> list[SavedMealPlan]:
        normalized_dates = [item.isoformat() for item in effective_dates]
        if not normalized_dates:
            return []

        documents = list(
            self._collection.find(
                {
                    "view_mode": "day",
                    "effective_date": {"$in": normalized_dates},
                }
            )
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return [self._to_model(document) for document in documents]

    def list_saved_day_plans_in_range(
        self,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
        limit: int = 500,
        allowed_statuses: list[str] | None = None,
    ) -> list[SavedMealPlan]:
        query: dict[str, Any] = {
            "user_id": user_id,
            "view_mode": "day",
            "effective_date": {
                "$gte": start_date.isoformat(),
                "$lte": end_date.isoformat(),
            },
        }
        if allowed_statuses:
            query["status"] = {"$in": [str(item) for item in allowed_statuses]}
        documents = list(
            self._collection.find(query)
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return [self._to_model(document) for document in documents]

    def get_by_user_snapshot(self, *, user_id: str, source_snapshot_id: str) -> SavedMealPlan | None:
        document = self._collection.find_one(
            {
                "user_id": user_id,
                "source_snapshot_id": source_snapshot_id,
            }
        )
        return None if document is None else self._to_model(document)

    def exists_for_user_snapshot(self, *, user_id: str, source_snapshot_id: str) -> bool:
        return (
            self._collection.count_documents(
                {
                    "user_id": user_id,
                    "source_snapshot_id": source_snapshot_id,
                },
                limit=1,
            )
            > 0
        )

    @staticmethod
    def _to_model(document: dict[str, Any]) -> SavedMealPlan:
        meal_type = document.get("meal_type")
        country_code = document.get("country_code")
        effective_date = document.get("effective_date")
        week_start = document.get("week_start")
        week_end = document.get("week_end")
        payload = dict(document.get("plan_payload") or {})
        return SavedMealPlan(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            title=str(document.get("title") or "Meal Plan"),
            status=str(document.get("status") or payload.get("state") or "saved"),
            view_mode=str(document.get("view_mode") or "day"),
            plan_scope=str(document["plan_scope"]) if document.get("plan_scope") else None,
            effective_date=date.fromisoformat(str(effective_date)) if effective_date else None,
            week_start=date.fromisoformat(str(week_start)) if week_start else None,
            week_end=date.fromisoformat(str(week_end)) if week_end else None,
            day_index=int(document["day_index"]) if document.get("day_index") is not None else None,
            parent_saved_plan_id=(
                str(document["parent_saved_plan_id"])
                if document.get("parent_saved_plan_id")
                else None
            ),
            source_saved_plan_id=(
                str(document["source_saved_plan_id"])
                if document.get("source_saved_plan_id")
                else None
            ),
            linked_day_plan_ids=[str(item) for item in list(document.get("linked_day_plan_ids") or [])],
            meal_type=MealType(str(meal_type)) if meal_type else None,
            country_code=CountryCode(str(country_code)) if country_code else None,
            planned_meals=list(document.get("planned_meals") or []),
            plan_payload=dict(document.get("plan_payload") or {}),
            requested_culture=str(document["requested_culture"]) if document.get("requested_culture") else None,
            user_goal=str(document["user_goal"]) if document.get("user_goal") else None,
            source_snapshot_id=str(document["source_snapshot_id"]),
            source_conversation_id=str(document["source_conversation_id"]),
            agent_type=str(document.get("agent_type") or "meal_coordinator"),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
