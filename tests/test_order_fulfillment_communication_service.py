from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.notification import AppNotification, NotificationCategory, NotificationNavigationMode, NotificationType
from app.models.user import User, UserType
from app.services import order_fulfillment_communication_service as communication_module
from app.services.notification_copy_service import NotificationCopyService
from app.services.order_fulfillment_communication_service import OrderFulfillmentCommunicationService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_user(*, user_id: str, user_types: list[UserType], email: str | None = None) -> User:
    return User(
        id=user_id,
        name=f"User {user_id}",
        email=email or f"{user_id}@example.com",
        password_hash="x",
        user_types=user_types,
        user_configuration={},
        created_at=utc_now(),
    )


class StubNotificationRepository:
    def __init__(self) -> None:
        self.notifications_by_key: dict[str, AppNotification] = {}
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    def get_by_idempotency_key(self, idempotency_key: str) -> AppNotification | None:
        return self.notifications_by_key.get(idempotency_key)

    def create_notification(self, **kwargs) -> AppNotification:
        self.create_calls.append(kwargs)
        now = utc_now()
        item = AppNotification(
            id=f"notif-{len(self.create_calls)}",
            category=kwargs["category"],
            notification_type=kwargs["notification_type"],
            title=kwargs["title"],
            message=kwargs["message"],
            navigation_mode=kwargs["navigation_mode"],
            recipient_user_ids=list(kwargs["recipient_user_ids"]),
            read_by_user_ids=[],
            target=dict(kwargs["target"]),
            details=dict(kwargs["details"]),
            metadata=dict(kwargs["metadata"]),
            idempotency_key=kwargs.get("idempotency_key"),
            created_at=now,
            updated_at=now,
        )
        self.notifications_by_key[kwargs["idempotency_key"]] = item
        return item

    def update_notification_content(self, **kwargs) -> AppNotification | None:
        self.update_calls.append(kwargs)
        for item in self.notifications_by_key.values():
            if item.id == kwargs["notification_id"]:
                return item
        return None


class StubUserRepository:
    def __init__(self, users: dict[str, User] | None = None) -> None:
        self.users: dict[str, User] = dict(users or {})

    def find_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def list_users(self, *, page, page_size, search=None, user_type=None):
        items = [user for user in self.users.values() if user_type is None or user_type in user.user_types]
        return items, len(items)


class RecordingEmailService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def send_order_fulfillment_event_email(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("email boom")


class RecordingPushNotificationService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("push boom")


class StubRealtimeDeliveryService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deliveries: list[dict] = []

    async def deliver(self, **kwargs) -> None:
        self.deliveries.append(kwargs)
        if self.fail:
            raise RuntimeError("websocket boom")


def build_service(
    *,
    users: dict[str, User] | None = None,
    email_service: RecordingEmailService | None = None,
    push_notification_service: RecordingPushNotificationService | None = None,
) -> tuple[OrderFulfillmentCommunicationService, StubNotificationRepository, RecordingEmailService, RecordingPushNotificationService]:
    notification_repository = StubNotificationRepository()
    user_repository = StubUserRepository(users)
    email = email_service or RecordingEmailService()
    push = push_notification_service or RecordingPushNotificationService()
    service = OrderFulfillmentCommunicationService(
        notification_repository=notification_repository,
        user_repository=user_repository,
        email_service=email,
        push_notification_service=push,
        notification_copy_service=NotificationCopyService(),
        web_app_base_url="https://app.safediet.example",
    )
    return service, notification_repository, email, push


class OrderFulfillmentCommunicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_worker_assigned_creates_notification_and_sends_all_channels(self) -> None:
        chef = build_user(user_id="chef-1", user_types=[UserType.CHEF])
        service, notification_repository, email, push = build_service(users={"chef-1": chef})
        realtime = StubRealtimeDeliveryService()

        with patch.object(communication_module, "realtime_delivery_service", realtime):
            await service.notify_worker_assigned(
                worker_user_id="chef-1",
                track="chef",
                order_id="order-1",
                order_number="MO-order-1",
                idempotency_key="key-1",
            )

        self.assertEqual(1, len(notification_repository.create_calls))
        self.assertEqual(NotificationCategory.FULFILLMENT, notification_repository.create_calls[0]["category"])
        self.assertEqual(NotificationType.ORDER_ASSIGNED_TO_WORKER, notification_repository.create_calls[0]["notification_type"])
        self.assertEqual(1, len(realtime.deliveries))
        self.assertEqual("fulfillment_update", realtime.deliveries[0]["delivery_type"])
        self.assertEqual(1, len(push.calls))
        self.assertEqual(1, len(email.calls))
        self.assertEqual("chef-1", email.calls[0]["user"].id)

    async def test_notify_worker_assigned_is_idempotent(self) -> None:
        chef = build_user(user_id="chef-1", user_types=[UserType.CHEF])
        service, notification_repository, _, _ = build_service(users={"chef-1": chef})
        realtime = StubRealtimeDeliveryService()

        with patch.object(communication_module, "realtime_delivery_service", realtime):
            await service.notify_worker_assigned(
                worker_user_id="chef-1", track="chef", order_id="order-1", order_number="MO-order-1", idempotency_key="key-1"
            )
            await service.notify_worker_assigned(
                worker_user_id="chef-1", track="chef", order_id="order-1", order_number="MO-order-1", idempotency_key="key-1"
            )

        self.assertEqual(1, len(notification_repository.create_calls))
        self.assertEqual(2, len(notification_repository.update_calls))

    async def test_notify_worker_assigned_email_failure_does_not_block_push(self) -> None:
        chef = build_user(user_id="chef-1", user_types=[UserType.CHEF])
        failing_email = RecordingEmailService(fail=True)
        service, _, email, push = build_service(users={"chef-1": chef}, email_service=failing_email)
        realtime = StubRealtimeDeliveryService()

        with patch.object(communication_module, "realtime_delivery_service", realtime):
            await service.notify_worker_assigned(
                worker_user_id="chef-1", track="chef", order_id="order-1", order_number="MO-order-1", idempotency_key="key-1"
            )

        self.assertEqual(1, len(email.calls))
        self.assertEqual(1, len(push.calls))

    async def test_notify_worker_assigned_websocket_failure_does_not_block_email(self) -> None:
        chef = build_user(user_id="chef-1", user_types=[UserType.CHEF])
        service, _, email, push = build_service(users={"chef-1": chef})
        realtime = StubRealtimeDeliveryService(fail=True)

        with patch.object(communication_module, "realtime_delivery_service", realtime):
            await service.notify_worker_assigned(
                worker_user_id="chef-1", track="chef", order_id="order-1", order_number="MO-order-1", idempotency_key="key-1"
            )

        self.assertEqual(1, len(realtime.deliveries))
        self.assertEqual(1, len(push.calls))
        self.assertEqual(1, len(email.calls))

    async def test_notify_worker_assigned_skips_unknown_worker(self) -> None:
        service, notification_repository, email, push = build_service(users={})
        realtime = StubRealtimeDeliveryService()

        with patch.object(communication_module, "realtime_delivery_service", realtime):
            await service.notify_worker_assigned(
                worker_user_id="ghost", track="chef", order_id="order-1", order_number="MO-order-1", idempotency_key="key-1"
            )

        self.assertEqual(0, len(notification_repository.create_calls))
        self.assertEqual(0, len(email.calls))
        self.assertEqual(0, len(push.calls))

    async def test_notify_admin_declined_fans_out_to_every_platform_user(self) -> None:
        admin_one = build_user(user_id="admin-1", user_types=[UserType.PLATFORM_USER])
        admin_two = build_user(user_id="admin-2", user_types=[UserType.PLATFORM_USER])
        chef = build_user(user_id="chef-1", user_types=[UserType.CHEF])
        service, notification_repository, email, push = build_service(
            users={"admin-1": admin_one, "admin-2": admin_two, "chef-1": chef}
        )
        realtime = StubRealtimeDeliveryService()

        with patch.object(communication_module, "realtime_delivery_service", realtime):
            await service.notify_admin_declined(
                track="chef",
                order_id="order-1",
                order_number="MO-order-1",
                worker_user_id="chef-1",
                reason_code="too_busy",
                idempotency_key="decline-key-1",
            )

        self.assertEqual(1, len(notification_repository.create_calls))
        self.assertEqual(2, len(notification_repository.create_calls[0]["recipient_user_ids"]))
        self.assertEqual(2, len(realtime.deliveries))
        self.assertEqual(2, len(push.calls))
        self.assertEqual(2, len(email.calls))


if __name__ == "__main__":
    unittest.main()
