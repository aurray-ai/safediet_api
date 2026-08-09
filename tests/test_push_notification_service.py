from __future__ import annotations

from datetime import datetime, timezone
import unittest

from app.models.push_device import PushDevice, PushEnvironment, PushPlatform
from app.services.push_notification_service import APNsPushNotificationSender


class _StubResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = ""

    def json(self):
        return {}


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _StubResponse()


class APNsPushNotificationSenderTests(unittest.TestCase):
    def test_alert_payload_enables_mutable_content_when_notification_has_image(self) -> None:
        sender = APNsPushNotificationSender(
            key_id="key-id",
            team_id="team-id",
            bundle_id="com.safediet.app",
            private_key="unused",
            connect_timeout_seconds=5,
            read_timeout_seconds=5,
        )
        sender._client = _StubClient()
        sender._bearer_token = lambda: "test-token"

        result = sender.send(
            device=PushDevice(
                id="device-1",
                user_id="user-1",
                platform=PushPlatform.IOS,
                device_token="abc123token",
                environment=PushEnvironment.SANDBOX,
                delivery_types=["notification"],
                locations=["ios.notifications"],
                app_version=None,
                build_number=None,
                device_name=None,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            payload={"notification_image_url": "https://example.com/meal.jpg"},
            alert_title="Meal reminder",
            alert_body="Your meal is ready.",
        )

        self.assertTrue(result)
        self.assertEqual(1, len(sender._client.calls))
        self.assertEqual(1, sender._client.calls[0]["json"]["aps"]["mutable-content"])

    def test_alert_payload_omits_mutable_content_without_notification_image(self) -> None:
        sender = APNsPushNotificationSender(
            key_id="key-id",
            team_id="team-id",
            bundle_id="com.safediet.app",
            private_key="unused",
            connect_timeout_seconds=5,
            read_timeout_seconds=5,
        )
        sender._client = _StubClient()
        sender._bearer_token = lambda: "test-token"

        result = sender.send(
            device=PushDevice(
                id="device-1",
                user_id="user-1",
                platform=PushPlatform.IOS,
                device_token="abc123token",
                environment=PushEnvironment.SANDBOX,
                delivery_types=["notification"],
                locations=["ios.notifications"],
                app_version=None,
                build_number=None,
                device_name=None,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            payload={},
            alert_title="Meal reminder",
            alert_body="Your meal is ready.",
        )

        self.assertTrue(result)
        self.assertEqual(1, len(sender._client.calls))
        self.assertNotIn("mutable-content", sender._client.calls[0]["json"]["aps"])
