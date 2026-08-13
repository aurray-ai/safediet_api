from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.user import User, UserType
from app.services.email_service import EmailSender, EmailService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RecordingEmailSender(EmailSender):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        html: str,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.calls.append(
            {
                "to_email": to_email,
                "subject": subject,
                "html": html,
                "tags": tags or {},
            }
        )


class EmailServiceTests(unittest.TestCase):
    def test_grocery_order_tracking_url_uses_mobile_link_domain(self) -> None:
        service = EmailService(
            sender=RecordingEmailSender(),
            web_app_base_url="https://www.safediet.com",
            mobile_app_link_base_url="https://www.safediet.org",
        )

        self.assertEqual(
            "https://www.safediet.org/orders/order-123/tracking",
            service.grocery_order_tracking_url(order_id="order-123"),
        )

    def test_grocery_order_status_email_points_cta_to_mobile_tracking_link(self) -> None:
        sender = RecordingEmailSender()
        service = EmailService(
            sender=sender,
            web_app_base_url="https://www.safediet.com",
            mobile_app_link_base_url="https://www.safediet.org",
        )
        user = User(
            id="user-1",
            name="Ada",
            email="ada@example.com",
            password_hash="hash",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )

        service.send_grocery_order_status_email(
            user=user,
            order_id="order-123",
            order_number="GSO-123",
            subject="Your order is confirmed",
            title="Order confirmed",
            body="your order is confirmed.",
            status="confirmed",
        )

        self.assertEqual(1, len(sender.calls))
        self.assertIn(
            'href="https://www.safediet.org/orders/order-123/tracking"',
            str(sender.calls[0]["html"]),
        )


if __name__ == "__main__":
    unittest.main()
