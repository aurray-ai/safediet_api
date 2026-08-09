from __future__ import annotations

import logging
from dataclasses import dataclass

from pymongo.errors import DuplicateKeyError

from app.models.notification import NotificationCategory, NotificationNavigationMode, NotificationType
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.notification_copy_service import NotificationCopyService
from app.services.push_notification_service import PushNotificationService

logger = logging.getLogger(__name__)

_NOTIFICATION_LOCATION = "ios.home"


@dataclass(frozen=True, slots=True)
class SubscriptionCommunicationService:
    notification_repository: NotificationRepository
    user_repository: UserRepository
    email_service: EmailService
    push_notification_service: PushNotificationService
    notification_copy_service: NotificationCopyService

    def notify_subscription_started(self, *, user_id: str, plan_name: str, idempotency_key: str) -> None:
        user = self.user_repository.find_by_id(user_id)
        if user is None:
            return

        copy = self.notification_copy_service.for_subscription_started(plan_name=plan_name)

        self._upsert_notification(
            notification_type=NotificationType.SUBSCRIPTION_STARTED,
            idempotency_key=idempotency_key,
            recipient_user_id=user.id,
            title=copy.title,
            message=copy.message,
        )
        self._send_push(
            user_id=user.id,
            notification_type=NotificationType.SUBSCRIPTION_STARTED,
            title=copy.title,
            message=copy.message,
        )

        try:
            self.email_service.send_subscription_started_email(user=user, plan_name=plan_name)
        except Exception:
            logger.exception("subscription.communication.email_failed user_id=%s event=started", user_id)

    def notify_subscription_canceled(self, *, user_id: str, plan_name: str, idempotency_key: str) -> None:
        user = self.user_repository.find_by_id(user_id)
        if user is None:
            return

        copy = self.notification_copy_service.for_subscription_canceled(plan_name=plan_name)

        self._upsert_notification(
            notification_type=NotificationType.SUBSCRIPTION_CANCELED,
            idempotency_key=idempotency_key,
            recipient_user_id=user.id,
            title=copy.title,
            message=copy.message,
        )
        self._send_push(
            user_id=user.id,
            notification_type=NotificationType.SUBSCRIPTION_CANCELED,
            title=copy.title,
            message=copy.message,
        )

        try:
            self.email_service.send_subscription_canceled_email(user=user)
        except Exception:
            logger.exception("subscription.communication.email_failed user_id=%s event=canceled", user_id)

    def _upsert_notification(
        self,
        *,
        notification_type: NotificationType,
        idempotency_key: str,
        recipient_user_id: str,
        title: str,
        message: str,
    ) -> None:
        target = {"location": _NOTIFICATION_LOCATION, "target_kind": "subscription"}
        details: dict = {}
        metadata = {"source": "billing"}

        item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            try:
                item = self.notification_repository.create_notification(
                    category=NotificationCategory.BILLING,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                    recipient_user_ids=[recipient_user_id],
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

    def _send_push(
        self,
        *,
        user_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
    ) -> None:
        try:
            self.push_notification_service.send(
                user_id=user_id,
                delivery_type="notification",
                location=_NOTIFICATION_LOCATION,
                payload={"category": "billing", "notification_type": notification_type.value},
                alert_title=title,
                alert_body=message,
            )
        except Exception:
            logger.exception(
                "subscription.communication.push_failed user_id=%s notification_type=%s",
                user_id,
                notification_type,
            )
