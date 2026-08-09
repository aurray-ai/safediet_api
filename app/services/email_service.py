from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import Settings
from app.models.user import User, UserType

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    pass


class EmailSender:
    def send(
        self,
        *,
        to_email: str,
        subject: str,
        html: str,
        tags: dict[str, str] | None = None,
    ) -> None:
        raise NotImplementedError


class LoggingEmailSender(EmailSender):
    def __init__(self, *, from_address: str, from_name: str) -> None:
        self._from_address = from_address
        self._from_name = from_name

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        html: str,
        tags: dict[str, str] | None = None,
    ) -> None:
        logger.info(
            "email.send simulated from=%s <%s> to=%s subject=%s tags=%s html_preview=%s",
            self._from_name,
            self._from_address,
            to_email,
            subject,
            tags or {},
            html[:160],
        )


class ResendEmailSender(EmailSender):
    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        from_name: str,
        api_base_url: str,
        timeout_seconds: float,
        reply_to: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._from_address = from_address
        self._from_name = from_name
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reply_to = reply_to

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        html: str,
        tags: dict[str, str] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "from": f"{self._from_name} <{self._from_address}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to
        if tags:
            payload["tags"] = [{"name": key, "value": value} for key, value in tags.items()]

        try:
            response = httpx.post(
                f"{self._api_base_url}/emails",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
            if response.is_error:
                preview = response.text[:240].strip()
                raise EmailDeliveryError(
                    f"Email delivery failed with status {response.status_code}. {preview}"
                )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(f"Email delivery failed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class EmailService:
    sender: EmailSender
    web_app_base_url: str

    def send_registration_email(self, *, user: User) -> None:
        self.sender.send(
            to_email=user.email,
            subject="Your Safediet account is ready",
            html=self._wrap_html(
                title="Your Safediet account is ready",
                body=(
                    f"Hi {self._safe_name(user.name)}, your account is live. "
                    "You can sign in, continue planning meals, and install the mobile app anytime."
                ),
                cta_label="Open Safediet",
                cta_url=self.web_app_base_url,
            ),
            tags={"category": "registration"},
        )

    def send_password_reset_email(
        self,
        *,
        user: User,
        reset_token: str,
        expires_at: datetime,
    ) -> None:
        reset_url = f"{self.web_app_base_url.rstrip('/')}/reset-password?token={reset_token}"
        expiry_text = expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.sender.send(
            to_email=user.email,
            subject="Reset your Safediet password",
            html=self._wrap_html(
                title="Reset your password",
                body=(
                    f"Hi {self._safe_name(user.name)}, we received a request to reset your Safediet password. "
                    f"This secure link expires on {expiry_text}."
                ),
                cta_label="Reset password",
                cta_url=reset_url,
                footer="If you did not request this, you can safely ignore this email.",
            ),
            tags={"category": "password_reset"},
        )

    def send_password_reset_success_email(self, *, user: User) -> None:
        self.sender.send(
            to_email=user.email,
            subject="Your Safediet password was changed",
            html=self._wrap_html(
                title="Your password was changed",
                body=(
                    f"Hi {self._safe_name(user.name)}, your Safediet password has been updated successfully."
                ),
                cta_label="Open Safediet",
                cta_url=self.web_app_base_url,
                footer="If this was not you, contact support and reset your password immediately.",
            ),
            tags={"category": "password_reset_success"},
        )

    def send_household_event_email(
        self,
        *,
        user: User,
        subject: str,
        title: str,
        body: str,
        focus: str,
    ) -> None:
        self.sender.send(
            to_email=user.email,
            subject=subject,
            html=self._wrap_html(
                title=title,
                body=f"Hi {self._safe_name(user.name)}, {body}",
                cta_label="Open Shared Budget",
                cta_url=self.web_app_base_url,
                footer="You are receiving this because you are part of a Safediet household.",
            ),
            tags={"category": "household", "focus": focus},
        )

    def send_household_invitation_email(
        self,
        *,
        to_email: str,
        recipient_name: str | None,
        subject: str,
        title: str,
        body: str,
        focus: str,
        action_url: str,
        footer: str | None = None,
    ) -> None:
        self.sender.send(
            to_email=to_email,
            subject=subject,
            html=self._wrap_html(
                title=title,
                body=f"Hi {self._safe_name(recipient_name or '')}, {body}",
                cta_label="Review invitation",
                cta_url=action_url,
                footer=footer or "Open the link above to review and accept your household invitation.",
            ),
            tags={"category": "household_invitation", "focus": focus},
        )

    def send_staff_invitation_email(
        self,
        *,
        user: User,
        user_types: list[UserType],
        setup_token: str,
        expires_at: datetime,
    ) -> None:
        setup_url = f"{self.web_app_base_url.rstrip('/')}/staff-invite/{setup_token}"
        expiry_text = expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        role_labels = ", ".join(user_type.value.replace("_", " ") for user_type in user_types) or "team member"
        self.sender.send(
            to_email=user.email,
            subject="You've been added to the Safediet team",
            html=self._wrap_html(
                title="Welcome to the team",
                body=(
                    f"Hi {self._safe_name(user.name)}, you've been added to the Safediet team as a "
                    f"{role_labels}. Set your password to get started. This secure link expires on {expiry_text}."
                ),
                cta_label="Set up your account",
                cta_url=setup_url,
                footer="If you weren't expecting this, you can safely ignore this email.",
            ),
            tags={"category": "staff_invitation"},
        )

    def send_subscription_started_email(self, *, user: User, plan_name: str) -> None:
        self.sender.send(
            to_email=user.email,
            subject="Welcome to Safediet Premium",
            html=self._wrap_html(
                title="You're a Premium member",
                body=(
                    f"Hi {self._safe_name(user.name)}, your {plan_name} subscription is now active. "
                    "Enjoy member pricing on groceries, full meal planning, and everything else Premium unlocks."
                ),
                cta_label="Open Safediet",
                cta_url=self.web_app_base_url,
            ),
            tags={"category": "subscription_started"},
        )

    def send_subscription_canceled_email(self, *, user: User) -> None:
        self.sender.send(
            to_email=user.email,
            subject="Your Safediet Premium subscription ended",
            html=self._wrap_html(
                title="Your subscription has ended",
                body=(
                    f"Hi {self._safe_name(user.name)}, your Safediet Premium subscription is no longer active. "
                    "You can resubscribe anytime to get member pricing and full access back."
                ),
                cta_label="Resubscribe",
                cta_url=self.web_app_base_url,
                footer="If this was unexpected, check your subscription status in the App Store or contact support.",
            ),
            tags={"category": "subscription_canceled"},
        )

    def send_order_fulfillment_event_email(
        self,
        *,
        user: User,
        subject: str,
        title: str,
        body: str,
        cta_label: str,
        cta_url: str,
        focus: str,
    ) -> None:
        self.sender.send(
            to_email=user.email,
            subject=subject,
            html=self._wrap_html(
                title=title,
                body=f"Hi {self._safe_name(user.name)}, {body}",
                cta_label=cta_label,
                cta_url=cta_url,
                footer="You are receiving this because you are part of the Safediet fulfillment team.",
            ),
            tags={"category": "order_fulfillment", "focus": focus},
        )

    @staticmethod
    def _safe_name(name: str) -> str:
        normalized = str(name or "").strip()
        return normalized or "there"

    @staticmethod
    def _wrap_html(
        *,
        title: str,
        body: str,
        cta_label: str,
        cta_url: str,
        footer: str | None = None,
    ) -> str:
        footer_markup = (
            f'<p style="margin:24px 0 0;color:#7a6d5f;font-size:14px;line-height:1.7;">{footer}</p>'
            if footer
            else ""
        )
        return f"""
        <div style="background:#f7f0e2;padding:32px;font-family:Arial,sans-serif;color:#17110d;">
          <div style="max-width:560px;margin:0 auto;background:#fffaf0;border-radius:20px;padding:36px;border:1px solid rgba(141,109,73,0.12);">
            <p style="margin:0 0 12px;color:#8e6a44;font-size:12px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;">Safediet</p>
            <h1 style="margin:0 0 16px;font-size:32px;line-height:1.1;">{title}</h1>
            <p style="margin:0;color:#5f5446;font-size:16px;line-height:1.8;">{body}</p>
            <div style="margin-top:28px;">
              <a href="{cta_url}" style="display:inline-block;background:#dcca87;color:#17110d;text-decoration:none;padding:14px 22px;border-radius:10px;font-weight:700;">{cta_label}</a>
            </div>
            {footer_markup}
          </div>
        </div>
        """.strip()


def build_email_sender(settings: Settings) -> EmailSender:
    from_address = str(settings.email_from_address or "").strip()
    from_name = str(settings.email_from_name or "").strip() or "Safediet"
    api_key = (
        settings.resend_api_key.get_secret_value()
        if settings.resend_api_key is not None
        else ""
    )

    if not api_key or not from_address:
        logger.info("Email sender not fully configured; using logging email sender.")
        return LoggingEmailSender(
            from_address=from_address or "no-reply@example.com",
            from_name=from_name,
        )

    return ResendEmailSender(
        api_key=api_key,
        from_address=from_address,
        from_name=from_name,
        api_base_url=settings.resend_api_base_url,
        timeout_seconds=settings.resend_timeout_seconds,
        reply_to=settings.email_reply_to,
    )
