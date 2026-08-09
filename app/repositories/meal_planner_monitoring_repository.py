from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection


class MealPlannerMonitoringRepository:
    def __init__(
        self,
        runs_collection: Collection[dict[str, Any]],
        events_collection: Collection[dict[str, Any]],
    ) -> None:
        self._runs = runs_collection
        self._events = events_collection

    def create_run(
        self,
        *,
        run_id: str,
        user_id: str,
        trace_id: str | None,
        request_type: str | None,
        view_mode: str | None,
        effective_date: str | None,
        status: str,
        root_step_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "_id": run_id,
            "user_id": user_id,
            "trace_id": trace_id,
            "request_type": request_type,
            "view_mode": view_mode,
            "effective_date": effective_date,
            "status": status,
            "root_step_id": root_step_id,
            "metadata": dict(metadata or {}),
            "event_count": 0,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "last_event_at": None,
            "last_step_key": None,
            "last_step_status": None,
            "summary": {},
        }
        self._runs.update_one(
            {"_id": run_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        stored = self._runs.find_one({"_id": run_id})
        return stored or document

    def mark_run_status(
        self,
        *,
        run_id: str,
        status: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._runs.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": status,
                    "summary": dict(summary or {}),
                    "updated_at": now,
                    "completed_at": now if status in {"completed", "failed"} else None,
                }
            },
        )

    def append_event(self, document: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        stored = {
            "_id": str(document.get("_id") or uuid4().hex),
            **dict(document),
            "created_at": document.get("created_at") or now,
        }
        self._events.insert_one(stored)
        self._runs.update_one(
            {"_id": stored["run_id"]},
            {
                "$inc": {"event_count": 1},
                "$set": {
                    "updated_at": now,
                    "last_event_at": stored["created_at"],
                    "last_step_key": stored.get("step_key"),
                    "last_step_status": stored.get("status"),
                },
            },
        )
        return stored

    def get_run_for_user(self, *, run_id: str, user_id: str) -> dict[str, Any] | None:
        return self._runs.find_one({"_id": run_id, "user_id": user_id})

    def get_run(self, *, run_id: str) -> dict[str, Any] | None:
        return self._runs.find_one({"_id": run_id})

    def list_runs_for_user(
        self,
        *,
        user_id: str,
        trace_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"user_id": user_id}
        if trace_id:
            query["trace_id"] = trace_id
        return list(
            self._runs.find(query)
            .sort([("created_at", DESCENDING)])
            .limit(max(limit, 1))
        )

    def list_runs(
        self,
        *,
        trace_id: str | None,
        user_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if trace_id:
            query["trace_id"] = trace_id
        if user_id:
            query["user_id"] = user_id
        return list(
            self._runs.find(query)
            .sort([("created_at", DESCENDING)])
            .limit(max(limit, 1))
        )

    def list_events_for_run(
        self,
        *,
        run_id: str,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return list(
            self._events.find({"run_id": run_id, "user_id": user_id})
            .sort([("created_at", 1), ("_id", 1)])
            .limit(max(limit, 1))
        )

    def list_events(
        self,
        *,
        run_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return list(
            self._events.find({"run_id": run_id})
            .sort([("created_at", 1), ("_id", 1)])
            .limit(max(limit, 1))
        )
