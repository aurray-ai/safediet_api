from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pymongo.errors import DuplicateKeyError

from app.models.notification import NotificationCategory, NotificationNavigationMode, NotificationType
from app.models.user import UserType
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.notification_copy_service import NotificationCopyService
from app.services.push_notification_service import PushNotificationService
from app.services.realtime_delivery_service import realtime_delivery_service

logger = logging.getLogger(__name__)

FulfillmentTrack = Literal["chef", "shopper"]

_TRACK_LABELS: dict[FulfillmentTrack, str] = {
    "chef": "meal order",
    "shopper": "grocery order",
}
_WORKER_LOCATIONS: dict[FulfillmentTrack, str] = {
    "chef": "chef.orders",
    "shopper": "shopper.orders",
}
_ADMIN_LOCATIONS: dict[FulfillmentTrack, str] = {
    "chef": "admin.meal_orders",
    "shopper": "admin.grocery_orders",
}
_WORKER_DASHBOARD_PATHS: dict[FulfillmentTrack, str] = {
    "chef": "/dashboard/chef/my-orders",
    "shopper": "/dashboard/shopper/my-orders",
}
_ADMIN_DASHBOARD_PATHS: dict[FulfillmentTrack, str] = {
    "chef": "/dashboard/admin/meal-orders",
    "shopper": "/dashboard/admin/orders",
}


@dataclass(frozen=True, slots=True)
class OrderFulfillmentCommunicationService:
    notification_repository: NotificationRepository
    user_repository: UserRepository
    email_service: EmailService
    push_notification_service: PushNotificationService
    notification_copy_service: NotificationCopyService
    web_app_base_url: str

    async def notify_worker_assigned(
        self,
        *,
        worker_user_id: str,
        track: FulfillmentTrack,
        order_id: str,
        order_number: str,
        idempotency_key: str,
    ) -> None:
        worker = self.user_repository.find_by_id(worker_user_id)
        if worker is None:
            return

        track_label = _TRACK_LABELS[track]
        copy = self.notification_copy_service.for_order_assigned_to_worker(
            order_number=order_number,
            track_label=track_label,
        )
        target = {
            "location": _WORKER_LOCATIONS[track],
            "target_kind": "fulfillment_order",
            "track": track,
            "order_id": order_id,
        }
        details = {"track": track, "order_id": order_id, "order_number": order_number}
        metadata = {"source": "order_fulfillment", "track": track, "order_id": order_id}

        self._upsert_notification(
            notification_type=NotificationType.ORDER_ASSIGNED_TO_WORKER,
            idempotency_key=idempotency_key,
            recipient_user_ids=[worker.id],
            title=copy.title,
            message=copy.message,
            target=target,
            details=details,
            metadata=metadata,
        )

        try:
            await realtime_delivery_service.deliver(
                user_id=worker.id,
                delivery_type="fulfillment_update",
                location=_WORKER_LOCATIONS[track],
                payload={"order_id": order_id, "order_number": order_number, "track": track},
                channels=["websocket"],
            )
        except Exception:
            logger.exception(
                "order_fulfillment.communication.websocket_failed user_id=%s order_id=%s track=%s",
                worker.id,
                order_id,
                track,
            )

        try:
            self.push_notification_service.send(
                user_id=worker.id,
                delivery_type="fulfillment_update",
                location=_WORKER_LOCATIONS[track],
                payload={"order_id": order_id, "order_number": order_number, "track": track},
                alert_title=copy.title,
                alert_body=copy.message,
            )
        except Exception:
            logger.exception(
                "order_fulfillment.communication.push_failed user_id=%s order_id=%s track=%s",
                worker.id,
                order_id,
                track,
            )

        try:
            self.email_service.send_order_fulfillment_event_email(
                user=worker,
                subject=copy.title,
                title=copy.title,
                body=copy.message,
                cta_label="Open assignment",
                cta_url=f"{self.web_app_base_url.rstrip('/')}{_WORKER_DASHBOARD_PATHS[track]}/{order_id}",
                focus=f"{track}_assigned",
            )
        except Exception:
            logger.exception(
                "order_fulfillment.communication.email_failed user_id=%s order_id=%s track=%s",
                worker.id,
                order_id,
                track,
            )

    async def notify_admin_declined(
        self,
        *,
        track: FulfillmentTrack,
        order_id: str,
        order_number: str,
        worker_user_id: str,
        reason_code: str,
        idempotency_key: str,
    ) -> None:
        admins, _total = self.user_repository.list_users(page=1, page_size=200, user_type=UserType.PLATFORM_USER)
        if not admins:
            return

        track_label = _TRACK_LABELS[track]
        copy = self.notification_copy_service.for_order_declined_by_worker(
            order_number=order_number,
            track_label=track_label,
        )
        admin_ids = [admin.id for admin in admins]
        target = {
            "location": _ADMIN_LOCATIONS[track],
            "target_kind": "fulfillment_order",
            "track": track,
            "order_id": order_id,
        }
        details = {
            "track": track,
            "order_id": order_id,
            "order_number": order_number,
            "declined_by_user_id": worker_user_id,
            "reason_code": reason_code,
        }
        metadata = {"source": "order_fulfillment", "track": track, "order_id": order_id}

        self._upsert_notification(
            notification_type=NotificationType.ORDER_DECLINED_BY_WORKER,
            idempotency_key=idempotency_key,
            recipient_user_ids=admin_ids,
            title=copy.title,
            message=copy.message,
            target=target,
            details=details,
            metadata=metadata,
        )

        for admin in admins:
            try:
                await realtime_delivery_service.deliver(
                    user_id=admin.id,
                    delivery_type="fulfillment_update",
                    location=_ADMIN_LOCATIONS[track],
                    payload={"order_id": order_id, "order_number": order_number, "track": track},
                    channels=["websocket"],
                )
            except Exception:
                logger.exception(
                    "order_fulfillment.communication.admin_websocket_failed user_id=%s order_id=%s track=%s",
                    admin.id,
                    order_id,
                    track,
                )

            try:
                self.push_notification_service.send(
                    user_id=admin.id,
                    delivery_type="fulfillment_update",
                    location=_ADMIN_LOCATIONS[track],
                    payload={"order_id": order_id, "order_number": order_number, "track": track},
                    alert_title=copy.title,
                    alert_body=copy.message,
                )
            except Exception:
                logger.exception(
                    "order_fulfillment.communication.admin_push_failed user_id=%s order_id=%s track=%s",
                    admin.id,
                    order_id,
                    track,
                )

            try:
                self.email_service.send_order_fulfillment_event_email(
                    user=admin,
                    subject=copy.title,
                    title=copy.title,
                    body=copy.message,
                    cta_label="Reassign order",
                    cta_url=f"{self.web_app_base_url.rstrip('/')}{_ADMIN_DASHBOARD_PATHS[track]}/{order_id}",
                    focus=f"{track}_declined",
                )
            except Exception:
                logger.exception(
                    "order_fulfillment.communication.admin_email_failed user_id=%s order_id=%s track=%s",
                    admin.id,
                    order_id,
                    track,
                )

    def _upsert_notification(
        self,
        *,
        notification_type: NotificationType,
        idempotency_key: str,
        recipient_user_ids: list[str],
        title: str,
        message: str,
        target: dict,
        details: dict,
        metadata: dict,
    ) -> None:
        item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            try:
                item = self.notification_repository.create_notification(
                    category=NotificationCategory.FULFILLMENT,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                    recipient_user_ids=recipient_user_ids,
                    target=target,
                    details=details,
                    metadata=metadata,
                    idempotency_key=idempotency_key,
                )
            except DuplicateKeyError:
                item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is not None:
            self.notification_repository.update_notification_content(
                notification_id=item.id,
                title=title,
                message=message,
                target=target,
                details=details,
                metadata=metadata,
                navigation_mode=NotificationNavigationMode.DIRECT,
            )
