from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from app.db.redis import redis_manager
from app.repositories.meal_planner_monitoring_repository import MealPlannerMonitoringRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MealPlannerMonitoringSubscription:
    user_id: str
    run_ids: frozenset[str]
    trace_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class MealPlannerMonitoringRecorder:
    service: "MealPlannerMonitoringService"
    run_id: str
    user_id: str
    trace_id: str | None
    root_step_id: str

    def start_step(
        self,
        *,
        step_key: str,
        parent_step_id: str | None = None,
        branch_key: str | None = None,
        step_type: str = "step",
        input_data: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> str:
        step_id = uuid4().hex
        self.service.record_event(
            run_id=self.run_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            event_kind="started",
            step_id=step_id,
            parent_step_id=parent_step_id or self.root_step_id,
            branch_key=branch_key,
            step_key=step_key,
            step_type=step_type,
            status="running",
            input_data=input_data,
            tags=tags,
        )
        return step_id

    def complete_step(
        self,
        *,
        step_id: str,
        step_key: str,
        parent_step_id: str | None = None,
        branch_key: str | None = None,
        step_type: str = "step",
        output_data: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
        status: str = "completed",
    ) -> None:
        self.service.record_event(
            run_id=self.run_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            event_kind="completed",
            step_id=step_id,
            parent_step_id=parent_step_id or self.root_step_id,
            branch_key=branch_key,
            step_key=step_key,
            step_type=step_type,
            status=status,
            output_data=output_data,
            metrics=metrics,
            tags=tags,
        )

    def fail_step(
        self,
        *,
        step_id: str,
        step_key: str,
        parent_step_id: str | None = None,
        branch_key: str | None = None,
        step_type: str = "step",
        error: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        self.service.record_event(
            run_id=self.run_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            event_kind="failed",
            step_id=step_id,
            parent_step_id=parent_step_id or self.root_step_id,
            branch_key=branch_key,
            step_key=step_key,
            step_type=step_type,
            status="failed",
            error=error,
            metrics=metrics,
            tags=tags,
        )

    def log(
        self,
        *,
        step_key: str,
        parent_step_id: str | None = None,
        branch_key: str | None = None,
        step_type: str = "log",
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
        status: str = "info",
    ) -> str:
        step_id = uuid4().hex
        self.service.record_event(
            run_id=self.run_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            event_kind="log",
            step_id=step_id,
            parent_step_id=parent_step_id or self.root_step_id,
            branch_key=branch_key,
            step_key=step_key,
            step_type=step_type,
            status=status,
            input_data=input_data,
            output_data=output_data,
            metrics=metrics,
            tags=tags,
        )
        return step_id

    def complete_run(self, *, summary: dict[str, Any] | None = None) -> None:
        self.service.record_event(
            run_id=self.run_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            event_kind="completed",
            step_id=self.root_step_id,
            parent_step_id=None,
            branch_key="root",
            step_key="planner.run",
            step_type="run",
            status="completed",
            output_data=summary,
        )
        self.service.mark_run_status(run_id=self.run_id, status="completed", summary=summary)

    def fail_run(self, *, error: dict[str, Any] | None = None) -> None:
        self.service.record_event(
            run_id=self.run_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            event_kind="failed",
            step_id=self.root_step_id,
            parent_step_id=None,
            branch_key="root",
            step_key="planner.run",
            step_type="run",
            status="failed",
            error=error,
        )
        self.service.mark_run_status(run_id=self.run_id, status="failed", summary={"error": error or {}})


class MealPlannerMonitoringService:
    CHANNEL = "meal_planner_monitoring_events"

    def __init__(self) -> None:
        self._enabled = False
        self._capture_payloads = True
        self._event_preview_limit = 40
        self._repository: MealPlannerMonitoringRepository | None = None
        self._subscriptions: dict[WebSocket, MealPlannerMonitoringSubscription] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._sync_lock = Lock()

    def configure(
        self,
        *,
        repository: MealPlannerMonitoringRepository,
        enabled: bool,
        capture_payloads: bool,
        event_preview_limit: int,
    ) -> None:
        self._repository = repository
        self._enabled = enabled
        self._capture_payloads = capture_payloads
        self._event_preview_limit = max(event_preview_limit, 1)

    def is_enabled(self) -> bool:
        return self._enabled and self._repository is not None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if not self.is_enabled():
            logger.info("Meal planner monitoring service is disabled.")
            return
        if self._listener_task is not None:
            return
        if redis_manager.client() is None:
            logger.info("Meal planner monitoring service started without Redis pubsub; using local dispatch.")
            return
        self._listener_task = asyncio.create_task(self._listen(), name="meal-planner-monitoring-listener")
        logger.info("Meal planner monitoring service subscribed to Redis channel '%s'.", self.CHANNEL)

    async def stop(self) -> None:
        if self._listener_task is None:
            return
        self._listener_task.cancel()
        try:
            await self._listener_task
        except asyncio.CancelledError:
            pass
        self._listener_task = None

    def start_run(
        self,
        *,
        user_id: str,
        trace_id: str | None,
        request_type: str | None,
        view_mode: str | None,
        effective_date: date | str | None,
        metadata: dict[str, Any] | None = None,
    ) -> MealPlannerMonitoringRecorder | None:
        if not self.is_enabled() or self._repository is None:
            return None

        run_id = str(trace_id or uuid4().hex)
        root_step_id = uuid4().hex
        effective_date_value = (
            effective_date.isoformat()
            if isinstance(effective_date, date)
            else (str(effective_date).strip() if effective_date else None)
        )
        self._repository.create_run(
            run_id=run_id,
            user_id=user_id,
            trace_id=trace_id,
            request_type=request_type,
            view_mode=view_mode,
            effective_date=effective_date_value,
            status="running",
            root_step_id=root_step_id,
            metadata=dict(metadata or {}),
        )
        self.record_event(
            run_id=run_id,
            user_id=user_id,
            trace_id=trace_id,
            event_kind="started",
            step_id=root_step_id,
            parent_step_id=None,
            branch_key="root",
            step_key="planner.run",
            step_type="run",
            status="running",
            input_data={
                "request_type": request_type,
                "view_mode": view_mode,
                "effective_date": effective_date_value,
                **dict(metadata or {}),
            },
        )
        return MealPlannerMonitoringRecorder(
            service=self,
            run_id=run_id,
            user_id=user_id,
            trace_id=trace_id,
            root_step_id=root_step_id,
        )

    def mark_run_status(self, *, run_id: str, status: str, summary: dict[str, Any] | None = None) -> None:
        if not self.is_enabled() or self._repository is None:
            return
        self._repository.mark_run_status(run_id=run_id, status=status, summary=summary)

    def record_event(
        self,
        *,
        run_id: str,
        user_id: str,
        trace_id: str | None,
        event_kind: str,
        step_id: str,
        parent_step_id: str | None,
        branch_key: str | None,
        step_key: str,
        step_type: str,
        status: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> None:
        if not self.is_enabled() or self._repository is None:
            return

        created_at = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "run_id": run_id,
            "user_id": user_id,
            "trace_id": trace_id,
            "event_kind": event_kind,
            "step_id": step_id,
            "parent_step_id": parent_step_id,
            "branch_key": branch_key,
            "step_key": step_key,
            "step_type": step_type,
            "status": status,
            "input": self._sanitize_payload(input_data),
            "output": self._sanitize_payload(output_data),
            "metrics": self._sanitize_payload(metrics),
            "error": self._sanitize_payload(error),
            "tags": self._sanitize_payload(tags),
            "created_at": created_at,
        }
        stored = self._repository.append_event(document)
        self._dispatch_threadsafe(stored)

    async def connect(
        self,
        *,
        user_id: str,
        websocket: WebSocket,
        run_ids: list[str] | None = None,
        trace_ids: list[str] | None = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._subscriptions[websocket] = MealPlannerMonitoringSubscription(
                user_id=user_id,
                run_ids=frozenset(item for item in (run_ids or []) if item),
                trace_ids=frozenset(item for item in (trace_ids or []) if item),
            )
        logger.info(
            "Meal planner monitoring websocket connected user_id=%s run_filters=%s trace_filters=%s active_connections=%s",
            user_id,
            ",".join(sorted(run_ids or [])) or "*",
            ",".join(sorted(trace_ids or [])) or "*",
            len(self._subscriptions),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            subscription = self._subscriptions.pop(websocket, None)
        if subscription is not None:
            logger.info("Meal planner monitoring websocket disconnected user_id=%s", subscription.user_id)

    def list_runs_for_user(
        self,
        *,
        user_id: str,
        trace_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled() or self._repository is None:
            return []
        return self._repository.list_runs_for_user(user_id=user_id, trace_id=trace_id, limit=limit)

    def get_run_for_user(self, *, run_id: str, user_id: str) -> dict[str, Any] | None:
        if not self.is_enabled() or self._repository is None:
            return None
        return self._repository.get_run_for_user(run_id=run_id, user_id=user_id)

    def get_run(self, *, run_id: str) -> dict[str, Any] | None:
        if not self.is_enabled() or self._repository is None:
            return None
        return self._repository.get_run(run_id=run_id)

    def list_events_for_run(
        self,
        *,
        run_id: str,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled() or self._repository is None:
            return []
        return self._repository.list_events_for_run(run_id=run_id, user_id=user_id, limit=limit)

    def list_runs(
        self,
        *,
        trace_id: str | None,
        user_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled() or self._repository is None:
            return []
        return self._repository.list_runs(trace_id=trace_id, user_id=user_id, limit=limit)

    def list_events(
        self,
        *,
        run_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled() or self._repository is None:
            return []
        return self._repository.list_events(run_id=run_id, limit=limit)

    def _dispatch_threadsafe(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._publish_or_dispatch(event), loop)
        except Exception:
            logger.exception("Failed to schedule meal planner monitoring event dispatch.")

    async def _publish_or_dispatch(self, event: dict[str, Any]) -> None:
        redis_client = redis_manager.client()
        if redis_client is None:
            await self._dispatch(event)
            return
        await asyncio.to_thread(
            redis_client.publish,
            self.CHANNEL,
            json.dumps(jsonable_encoder(event), default=str, sort_keys=True),
        )

    async def _listen(self) -> None:
        redis_client = redis_manager.client()
        if redis_client is None:
            return

        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        try:
            await asyncio.to_thread(pubsub.subscribe, self.CHANNEL)
            while True:
                message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
                if not message:
                    await asyncio.sleep(0.05)
                    continue
                raw_payload = message.get("data")
                if not raw_payload:
                    continue
                try:
                    event = json.loads(str(raw_payload))
                except Exception:
                    logger.exception("Meal planner monitoring service failed to decode Redis payload.")
                    continue
                await self._dispatch(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Meal planner monitoring service listener stopped unexpectedly.")
        finally:
            await asyncio.to_thread(pubsub.close)

    async def _dispatch(self, event: dict[str, Any]) -> None:
        encoded_event = jsonable_encoder(event)
        async with self._lock:
            subscriptions = list(self._subscriptions.items())

        stale: list[WebSocket] = []
        for websocket, subscription in subscriptions:
            if subscription.user_id != str(event.get("user_id") or ""):
                continue
            run_id = str(event.get("run_id") or "")
            trace_id = str(event.get("trace_id") or "")
            if subscription.run_ids and run_id not in subscription.run_ids:
                continue
            if subscription.trace_ids and trace_id not in subscription.trace_ids:
                continue
            try:
                await websocket.send_json(encoded_event)
            except Exception:
                stale.append(websocket)

        for websocket in stale:
            await self.disconnect(websocket)

    def _sanitize_payload(self, value: Any) -> Any:
        if value is None:
            return None
        if self._capture_payloads:
            return jsonable_encoder(value)
        return self._compact_preview(value)

    def _compact_preview(self, value: Any) -> Any:
        encoded = jsonable_encoder(value)
        if isinstance(encoded, dict):
            preview: dict[str, Any] = {}
            for index, (key, item) in enumerate(encoded.items()):
                if index >= self._event_preview_limit:
                    preview["__truncated__"] = True
                    break
                preview[str(key)] = self._compact_preview(item)
            return preview
        if isinstance(encoded, list):
            return [self._compact_preview(item) for item in encoded[: self._event_preview_limit]]
        if isinstance(encoded, str) and len(encoded) > 400:
            return encoded[:400] + "..."
        return encoded


meal_planner_monitoring_service = MealPlannerMonitoringService()
