from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.models.notification import (
    NotificationCategory,
    NotificationNavigationMode,
    NotificationType,
)
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.push_notification_service import PushNotificationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HouseholdCommunicationService:
    notification_repository: NotificationRepository
    user_repository: UserRepository
    email_service: EmailService
    push_notification_service: PushNotificationService

    def notify(
        self,
        *,
        recipient_user_ids: list[str],
        title: str,
        message: str,
        household_id: str,
        focus: str,
        idempotency_key: str,
        email_subject: str | None = None,
        email_intro: str | None = None,
        details: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_recipient_user_ids = list(
            dict.fromkeys(str(user_id).strip() for user_id in recipient_user_ids if str(user_id).strip())
        )
        if not normalized_recipient_user_ids:
            return

        target = {
            "location": "ios.notifications",
            "tab": "shared_budget",
            "target_kind": "household_budget",
            "household_id": household_id,
            "focus": focus,
        }
        event_details = {
            "household_id": household_id,
            "focus": focus,
            **dict(details or {}),
        }
        event_metadata = {
            "source": "household_budgeting",
            "focus": focus,
            **dict(metadata or {}),
        }

        item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            try:
                item = self.notification_repository.create_notification(
                    category=NotificationCategory.SYSTEM,
                    notification_type=NotificationType.GENERAL,
                    title=title,
                    message=message,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                    recipient_user_ids=normalized_recipient_user_ids,
                    target=target,
                    details=event_details,
                    metadata=event_metadata,
                    idempotency_key=idempotency_key,
                )
            except DuplicateKeyError:
                item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is not None:
            item = self.notification_repository.update_notification_content(
                notification_id=item.id,
                title=title,
                message=message,
                target=target,
                details=event_details,
                metadata=event_metadata,
                navigation_mode=NotificationNavigationMode.DIRECT,
            )

        for recipient_user_id in normalized_recipient_user_ids:
            try:
                self.push_notification_service.send(
                    user_id=recipient_user_id,
                    delivery_type="notification",
                    location="ios.notifications",
                    payload={
                        "notification_id": item.id if item is not None else None,
                        "target": target,
                        "title": title,
                        "message": message,
                    },
                    alert_title=title,
                    alert_body=message,
                )
            except Exception:
                logger.exception(
                    "household.communication.push_failed user_id=%s household_id=%s focus=%s",
                    recipient_user_id,
                    household_id,
                    focus,
                )

        users = self.user_repository.list_by_ids(normalized_recipient_user_ids)
        for user in users:
            try:
                self.email_service.send_household_event_email(
                    user=user,
                    subject=email_subject or title,
                    title=title,
                    body=email_intro or message,
                    focus=focus,
                )
            except Exception:
                logger.exception(
                    "household.communication.email_failed user_id=%s household_id=%s focus=%s",
                    user.id,
                    household_id,
                    focus,
                )

    def notify_invitation(
        self,
        *,
        household_id: str,
        invitee_email: str,
        invitee_name: str | None,
        existing_user_id: str | None,
        title: str,
        message: str,
        focus: str,
        idempotency_key: str,
        email_subject: str,
        email_intro: str,
        action_url: str,
    ) -> None:
        existing_user: User | None = None
        if existing_user_id is not None:
            existing_user = self.user_repository.find_by_id(existing_user_id)

        if existing_user is not None:
            target = {
                "location": "ios.notifications",
                "tab": "shared_budget",
                "target_kind": "household_budget",
                "household_id": household_id,
                "focus": focus,
            }
            event_details = {
                "household_id": household_id,
                "focus": focus,
                "invitee_email": invitee_email,
                "action_url": action_url,
            }
            event_metadata = {
                "source": "household_budgeting",
                "focus": focus,
                "action_url": action_url,
            }

            item = self.notification_repository.get_by_idempotency_key(idempotency_key)
            if item is None:
                try:
                    item = self.notification_repository.create_notification(
                        category=NotificationCategory.SYSTEM,
                        notification_type=NotificationType.GENERAL,
                        title=title,
                        message=message,
                        navigation_mode=NotificationNavigationMode.DIRECT,
                        recipient_user_ids=[existing_user.id],
                        target=target,
                        details=event_details,
                        metadata=event_metadata,
                        idempotency_key=idempotency_key,
                    )
                except DuplicateKeyError:
                    item = self.notification_repository.get_by_idempotency_key(idempotency_key)
            if item is not None:
                item = self.notification_repository.update_notification_content(
                    notification_id=item.id,
                    title=title,
                    message=message,
                    target=target,
                    details=event_details,
                    metadata=event_metadata,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                )

            try:
                self.push_notification_service.send(
                    user_id=existing_user.id,
                    delivery_type="notification",
                    location="ios.notifications",
                    payload={
                        "notification_id": item.id if item is not None else None,
                        "target": target,
                        "title": title,
                        "message": message,
                    },
                    alert_title=title,
                    alert_body=message,
                )
            except Exception:
                logger.exception(
                    "household.communication.invitation_push_failed user_id=%s household_id=%s focus=%s",
                    existing_user.id,
                    household_id,
                    focus,
                )

        recipient_name = existing_user.name if existing_user is not None else invitee_name
        footer = (
            "Accept this invitation from the same Safediet account."
            if existing_user is not None
            else "Create your Safediet account, then accept the invitation from the same email address."
        )
        destination_email = existing_user.email if existing_user is not None else invitee_email
        try:
            self.email_service.send_household_invitation_email(
                to_email=destination_email,
                recipient_name=recipient_name,
                subject=email_subject,
                title=title,
                body=email_intro,
                focus=focus,
                action_url=action_url,
                footer=footer,
            )
        except Exception:
            logger.exception(
                "household.communication.invitation_email_failed email=%s household_id=%s focus=%s",
                destination_email,
                household_id,
                focus,
            )
            raise
