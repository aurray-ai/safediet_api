from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from jose import jwt

from app.core.config import Settings
from app.models.push_device import PushDevice, PushEnvironment, PushPlatform
from app.repositories.push_device_repository import PushDeviceRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PushNotificationDispatchResult:
    attempted: int
    sent: int


class PushNotificationSender:
    def send(
        self,
        *,
        device: PushDevice,
        payload: dict[str, Any],
        alert_title: str | None = None,
        alert_body: str | None = None,
    ) -> bool:
        raise NotImplementedError


class LoggingPushNotificationSender(PushNotificationSender):
    def send(
        self,
        *,
        device: PushDevice,
        payload: dict[str, Any],
        alert_title: str | None = None,
        alert_body: str | None = None,
    ) -> bool:
        logger.info(
            "push.notification.send simulated user_id=%s platform=%s environment=%s token_suffix=%s alert_title=%s alert_body=%s payload=%s",
            device.user_id,
            device.platform.value,
            device.environment.value,
            device.device_token[-8:],
            alert_title or "-",
            alert_body or "-",
            payload,
        )
        return True


class APNsPushNotificationSender(PushNotificationSender):
    SANDBOX_URL = "https://api.sandbox.push.apple.com"
    PRODUCTION_URL = "https://api.push.apple.com"

    def __init__(
        self,
        *,
        key_id: str,
        team_id: str,
        bundle_id: str,
        private_key: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
    ) -> None:
        self._key_id = key_id
        self._team_id = team_id
        self._bundle_id = bundle_id
        self._private_key = private_key
        self._client = httpx.Client(
            http2=True,
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=read_timeout_seconds,
                pool=read_timeout_seconds,
            ),
        )
        self._cached_bearer_token: str | None = None
        self._cached_bearer_token_issued_at: int = 0

    def send(
        self,
        *,
        device: PushDevice,
        payload: dict[str, Any],
        alert_title: str | None = None,
        alert_body: str | None = None,
    ) -> bool:
        aps_payload: dict[str, Any] = {}
        if alert_title or alert_body:
            aps_payload["alert"] = {
                "title": alert_title or "",
                "body": alert_body or "",
            }
            aps_payload["sound"] = "default"
            if str(payload.get("notification_image_url") or "").strip():
                aps_payload["mutable-content"] = 1
            push_type = "alert"
            priority = "10"
        else:
            aps_payload["content-available"] = 1
            push_type = "background"
            priority = "5"

        envelope = {
            "aps": aps_payload,
            **payload,
        }
        url = f"{self._base_url_for(device.environment)}/3/device/{device.device_token}"

        try:
            headers = {
                "authorization": f"bearer {self._bearer_token()}",
                "apns-topic": self._bundle_id,
                "apns-push-type": push_type,
                "apns-priority": priority,
            }
            response = self._client.post(url, headers=headers, json=envelope)
        except Exception:
            logger.exception(
                "push.notification.send failed transport user_id=%s token_suffix=%s",
                device.user_id,
                device.device_token[-8:],
            )
            return False

        if response.status_code == 200:
            logger.info(
                "push.notification.send completed user_id=%s platform=%s token_suffix=%s push_type=%s",
                device.user_id,
                device.platform.value,
                device.device_token[-8:],
                push_type,
            )
            return True

        try:
            response_payload = response.json()
        except Exception:
            response_payload = {"raw": response.text}

        logger.warning(
            "push.notification.send rejected user_id=%s token_suffix=%s status=%s response=%s",
            device.user_id,
            device.device_token[-8:],
            response.status_code,
            response_payload,
        )
        return False

    def _bearer_token(self) -> str:
        issued_at = int(time.time())
        if self._cached_bearer_token and issued_at - self._cached_bearer_token_issued_at < 50 * 60:
            return self._cached_bearer_token

        token = jwt.encode(
            {"iss": self._team_id, "iat": issued_at},
            self._private_key,
            algorithm="ES256",
            headers={"kid": self._key_id},
        )
        self._cached_bearer_token = token
        self._cached_bearer_token_issued_at = issued_at
        return token

    @classmethod
    def _base_url_for(cls, environment: PushEnvironment) -> str:
        if environment == PushEnvironment.PRODUCTION:
            return cls.PRODUCTION_URL
        return cls.SANDBOX_URL


@dataclass(frozen=True, slots=True)
class PushNotificationService:
    push_device_repository: PushDeviceRepository
    sender: PushNotificationSender

    def send(
        self,
        *,
        user_id: str,
        delivery_type: str,
        location: str,
        payload: dict[str, Any],
        alert_title: str | None = None,
        alert_body: str | None = None,
        platform: PushPlatform = PushPlatform.IOS,
    ) -> PushNotificationDispatchResult:
        devices = self.push_device_repository.list_active_devices(
            user_id=user_id,
            platform=platform,
            location=location,
            delivery_type=delivery_type,
        )
        sent = 0
        enriched_payload = {
            "delivery_type": delivery_type,
            "location": location,
            **payload,
        }
        for device in devices:
            if self.sender.send(
                device=device,
                payload=enriched_payload,
                alert_title=alert_title,
                alert_body=alert_body,
            ):
                sent += 1
        return PushNotificationDispatchResult(attempted=len(devices), sent=sent)


def build_push_notification_sender(settings: Settings) -> PushNotificationSender:
    if not settings.apns_key_id or not settings.apns_team_id or not settings.apns_bundle_id:
        logger.info("APNs sender not configured; using logging push sender.")
        return LoggingPushNotificationSender()

    private_key = _resolve_apns_private_key(settings)
    if not private_key:
        logger.info("APNs private key not configured; using logging push sender.")
        return LoggingPushNotificationSender()

    return APNsPushNotificationSender(
        key_id=settings.apns_key_id,
        team_id=settings.apns_team_id,
        bundle_id=settings.apns_bundle_id,
        private_key=private_key,
        connect_timeout_seconds=settings.apns_connect_timeout_seconds,
        read_timeout_seconds=settings.apns_read_timeout_seconds,
    )


def _resolve_apns_private_key(settings: Settings) -> str | None:
    if settings.apns_private_key is not None:
        value = settings.apns_private_key.get_secret_value().strip()
        if value:
            return value.replace("\\n", "\n")

    if settings.apns_private_key_path:
        path = Path(settings.apns_private_key_path)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()

    return None
