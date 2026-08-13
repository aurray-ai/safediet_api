from __future__ import annotations

import logging
from dataclasses import dataclass

from pymongo.errors import DuplicateKeyError

from app.models.notification import NotificationCategory, NotificationNavigationMode, NotificationType
from app.models.order import Order, OrderStatus
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.push_notification_service import PushNotificationService

logger = logging.getLogger(__name__)

_NOTIFICATION_LOCATION = "ios.notifications"
_ORDER_TRACKING_LOCATION = "ios.grocery"


@dataclass(frozen=True, slots=True)
class OrderStatusCustomerMessage:
    subject: str
    title: str
    message: str
    email_body: str


@dataclass(frozen=True, slots=True)
class OrderStatusCommunicationService:
    notification_repository: NotificationRepository
    user_repository: UserRepository
    email_service: EmailService
    push_notification_service: PushNotificationService
    web_app_base_url: str

    def notify_customer_order_status_changed(self, *, order: Order, idempotency_key: str) -> None:
        user = self.user_repository.find_by_id(order.user_id)
        if user is None:
            return

        copy = self._copy_for_status(order_number=order.order_number, status=order.status)
        target = {
            "location": _ORDER_TRACKING_LOCATION,
            "tab": "orders",
            "target_kind": "grocery_order_tracking",
            "order_id": order.id,
            "order_number": order.order_number,
            "notification_focus": "order_tracking",
            "focus": order.status.value,
        }
        details = {
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status.value,
        }
        metadata = {
            "source": "order_status",
            "order_id": order.id,
            "status": order.status.value,
        }

        item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            try:
                item = self.notification_repository.create_notification(
                    category=NotificationCategory.ORDER,
                    notification_type=NotificationType.ORDER_STATUS_UPDATE,
                    title=copy.title,
                    message=copy.message,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                    recipient_user_ids=[user.id],
                    target=target,
                    details=details,
                    metadata=metadata,
                    idempotency_key=idempotency_key,
                )
            except DuplicateKeyError:
                item = self.notification_repository.get_by_idempotency_key(idempotency_key)
        if item is not None:
            item = self.notification_repository.update_notification_content(
                notification_id=item.id,
                title=copy.title,
                message=copy.message,
                target=target,
                details=details,
                metadata=metadata,
                navigation_mode=NotificationNavigationMode.DIRECT,
            )

        try:
            self.push_notification_service.send(
                user_id=user.id,
                delivery_type="notification",
                location=_NOTIFICATION_LOCATION,
                payload={
                    "notification_id": item.id if item is not None else None,
                    "target": target,
                    "category": NotificationCategory.ORDER.value,
                    "notification_type": NotificationType.ORDER_STATUS_UPDATE.value,
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "status": order.status.value,
                    "title": copy.title,
                    "message": copy.message,
                },
                alert_title=copy.title,
                alert_body=copy.message,
            )
        except Exception:
            logger.exception(
                "order_status.communication.push_failed user_id=%s order_id=%s status=%s",
                user.id,
                order.id,
                order.status.value,
            )

        try:
            self.email_service.send_grocery_order_status_email(
                user=user,
                order_id=order.id,
                order_number=order.order_number,
                subject=copy.subject,
                title=copy.title,
                body=copy.email_body,
                status=order.status.value,
            )
        except Exception:
            logger.exception(
                "order_status.communication.email_failed user_id=%s order_id=%s status=%s",
                user.id,
                order.id,
                order.status.value,
            )

    @staticmethod
    def _copy_for_status(*, order_number: str, status: OrderStatus) -> OrderStatusCustomerMessage:
        if status == OrderStatus.PENDING_PAYMENT:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} is awaiting payment",
                title="Payment still needed",
                message=f"{order_number} is waiting for payment before we can start processing it.",
                email_body=f"your order {order_number} is waiting for payment before we can start processing it.",
            )
        if status == OrderStatus.PAYMENT_PROCESSING:
            return OrderStatusCustomerMessage(
                subject=f"We’re processing payment for {order_number}",
                title="Payment is processing",
                message=f"We’re currently processing payment for {order_number}.",
                email_body=f"we’re currently processing payment for {order_number}. We’ll update you again once the order is confirmed.",
            )
        if status == OrderStatus.CONFIRMED:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} is confirmed",
                title="Order confirmed",
                message=f"{order_number} is confirmed and queued for shopping.",
                email_body=f"your order {order_number} is confirmed and queued for shopping.",
            )
        if status == OrderStatus.PICKING:
            return OrderStatusCustomerMessage(
                subject=f"We’ve started shopping {order_number}",
                title="Shopping has started",
                message=f"We’ve started picking items for {order_number}.",
                email_body=f"we’ve started picking items for {order_number}. If substitutions are needed, we’ll use your selected preferences.",
            )
        if status == OrderStatus.PACKED:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} has been packed",
                title="Order packed",
                message=f"{order_number} has been packed and is ready for dispatch.",
                email_body=f"your order {order_number} has been packed and is ready for dispatch.",
            )
        if status == OrderStatus.OUT_FOR_DELIVERY:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} is on the way",
                title="Out for delivery",
                message=f"{order_number} is now on the way to you.",
                email_body=f"your order {order_number} is now on the way to you.",
            )
        if status == OrderStatus.DELIVERED:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} was delivered",
                title="Order delivered",
                message=f"{order_number} has been marked as delivered.",
                email_body=f"your order {order_number} has been marked as delivered. If anything looks wrong, please contact support from the app.",
            )
        if status == OrderStatus.PARTIALLY_REFUNDED:
            return OrderStatusCustomerMessage(
                subject=f"A partial refund was processed for {order_number}",
                title="Partial refund processed",
                message=f"A partial refund has been processed for {order_number}.",
                email_body=f"a partial refund has been processed for your order {order_number}. Open Safediet to review the latest order and refund details.",
            )
        if status == OrderStatus.REFUNDED:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} was refunded",
                title="Order refunded",
                message=f"{order_number} has been refunded.",
                email_body=f"your order {order_number} has been refunded. Open Safediet to review the latest refund details.",
            )
        if status == OrderStatus.CANCELED:
            return OrderStatusCustomerMessage(
                subject=f"Your Safediet order {order_number} was canceled",
                title="Order canceled",
                message=f"{order_number} has been canceled.",
                email_body=f"your order {order_number} has been canceled.",
            )
        return OrderStatusCustomerMessage(
            subject=f"There was a payment issue with {order_number}",
            title="Payment issue",
            message=f"There was a payment issue with {order_number}.",
            email_body=f"there was a payment issue with your order {order_number}. Please open Safediet to review the order and try again if needed.",
        )
