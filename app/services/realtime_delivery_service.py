from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import WebSocket

from app.db.redis import redis_manager
from app.services.push_notification_service import PushNotificationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RealtimeConnectionSubscription:
    user_id: str
    locations: frozenset[str]


class RealtimeDeliveryService:
    CHANNEL = "realtime_delivery_events"

    def __init__(self) -> None:
        self._subscriptions: dict[WebSocket, RealtimeConnectionSubscription] = {}
        self._lock = asyncio.Lock()
        self._listener_task: asyncio.Task[None] | None = None
        self._push_notification_service: PushNotificationService | None = None

    async def start(self) -> None:
        if self._listener_task is not None:
            return
        if redis_manager.client() is None:
            logger.info("Realtime delivery service started without Redis pubsub; using local delivery only.")
            return
        self._listener_task = asyncio.create_task(self._listen(), name="realtime-delivery-listener")
        logger.info("Realtime delivery service subscribed to Redis channel '%s'.", self.CHANNEL)

    async def stop(self) -> None:
        if self._listener_task is None:
            return
        self._listener_task.cancel()
        try:
            await self._listener_task
        except asyncio.CancelledError:
            pass
        self._listener_task = None

    def configure_push_notifications(
        self,
        push_notification_service: PushNotificationService | None,
    ) -> None:
        self._push_notification_service = push_notification_service

    async def connect(
        self,
        *,
        user_id: str,
        websocket: WebSocket,
        locations: list[str] | None = None,
    ) -> None:
        await websocket.accept()
        normalized_locations = frozenset(location.strip() for location in (locations or []) if location.strip())
        async with self._lock:
            self._subscriptions[websocket] = RealtimeConnectionSubscription(
                user_id=user_id,
                locations=normalized_locations,
            )
        logger.info(
            "Realtime delivery websocket connected user_id=%s locations=%s active_connections=%s",
            user_id,
            ",".join(sorted(normalized_locations)) or "*",
            len(self._subscriptions),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            subscription = self._subscriptions.pop(websocket, None)
        if subscription is not None:
            logger.info("Realtime delivery websocket disconnected user_id=%s", subscription.user_id)

    async def deliver(
        self,
        *,
        user_id: str,
        delivery_type: str,
        location: str,
        payload: dict[str, Any],
        push_payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
        conversation_id: str | None = None,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
        channels: list[str] | None = None,
        push_alert_title: str | None = None,
        push_alert_body: str | None = None,
    ) -> None:
        requested_channels = [channel.strip().lower() for channel in (channels or ["websocket"]) if channel.strip()]
        if not requested_channels:
            requested_channels = ["websocket"]
        subscriber_count = 0
        if "websocket" in requested_channels:
            subscriber_count = await self.active_subscriber_count(user_id=user_id, location=location)
        logger.info(
            "Realtime delivery requested user_id=%s delivery_type=%s location=%s channels=%s subscribers=%s trace_id=%s conversation_id=%s status=%s",
            user_id,
            delivery_type,
            location,
            ",".join(requested_channels) or "-",
            subscriber_count,
            trace_id or "-",
            conversation_id or "-",
            status,
        )
        event = {
            "type": "delivery",
            "user_id": user_id,
            "delivery_type": delivery_type,
            "location": location,
            "status": status,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "payload": payload,
            "channels": requested_channels,
            "metadata": metadata or {},
        }
        if "websocket" in requested_channels:
            redis_client = redis_manager.client()
            if redis_client is None:
                logger.info(
                    "Realtime delivery websocket dispatch mode=local user_id=%s location=%s subscribers=%s",
                    user_id,
                    location,
                    subscriber_count,
                )
                await self._dispatch(event)
            else:
                logger.info(
                    "Realtime delivery websocket dispatch mode=redis user_id=%s location=%s subscribers=%s",
                    user_id,
                    location,
                    subscriber_count,
                )
                await asyncio.to_thread(
                    redis_client.publish,
                    self.CHANNEL,
                    json.dumps(event, default=str, sort_keys=True),
                )
        if "push" in requested_channels and self._push_notification_service is not None:
            result = await asyncio.to_thread(
                self._push_notification_service.send,
                user_id=user_id,
                delivery_type=delivery_type,
                location=location,
                payload=push_payload or payload,
                alert_title=push_alert_title,
                alert_body=push_alert_body,
            )
            logger.info(
                "Realtime delivery push dispatch user_id=%s delivery_type=%s location=%s attempted=%s sent=%s",
                user_id,
                delivery_type,
                location,
                result.attempted,
                result.sent,
            )

    async def active_subscriber_count(self, *, user_id: str, location: str) -> int:
        async with self._lock:
            subscriptions = list(self._subscriptions.values())
        return sum(
            1
            for subscription in subscriptions
            if subscription.user_id == user_id
            and (not subscription.locations or location in subscription.locations)
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
                    logger.exception("Realtime delivery service failed to decode Redis payload.")
                    continue
                await self._dispatch(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Realtime delivery service listener stopped unexpectedly.")
        finally:
            await asyncio.to_thread(pubsub.close)

    async def _dispatch(self, event: dict[str, Any]) -> None:
        user_id = str(event.get("user_id") or "").strip()
        location = str(event.get("location") or "").strip()
        if not user_id or not location:
            return
        encoded_event = jsonable_encoder(event)

        async with self._lock:
            subscriptions = list(self._subscriptions.items())

        matched_count = 0
        stale: list[WebSocket] = []
        for websocket, subscription in subscriptions:
            if subscription.user_id != user_id:
                continue
            if subscription.locations and location not in subscription.locations:
                continue
            matched_count += 1
            try:
                await websocket.send_json(encoded_event)
            except Exception:
                logger.exception(
                    "Realtime delivery websocket send failed user_id=%s location=%s trace_id=%s",
                    user_id,
                    location,
                    str(event.get("trace_id") or "-"),
                )
                stale.append(websocket)

        logger.info(
            "Realtime delivery websocket dispatched user_id=%s location=%s matched=%s stale=%s total_connections=%s trace_id=%s",
            user_id,
            location,
            matched_count,
            len(stale),
            len(subscriptions),
            str(event.get("trace_id") or "-"),
        )

        for websocket in stale:
            await self.disconnect(websocket)


realtime_delivery_service = RealtimeDeliveryService()
