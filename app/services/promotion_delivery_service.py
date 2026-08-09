from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.models.notification import (
    AppNotification,
    NotificationCategory,
    NotificationNavigationMode,
    NotificationType,
)
from app.models.user import User
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.promotion_campaign_repository import PromotionCampaignRepository
from app.repositories.promotion_delivery_repository import PromotionDeliveryRepository
from app.repositories.promotion_draft_repository import PromotionDraftRepository
from app.schemas.admin_promotion import (
    PromotionAuditLogListResponse,
    PromotionAuditLogResponse,
    PromotionDeliverResponse,
    PromotionDeliveryListResponse,
    PromotionDeliveryResponse,
)
from app.schemas.notification import NotificationResponse
from app.services.realtime_delivery_service import realtime_delivery_service


class PromotionDeliveryError(Exception):
    pass


class PromotionDeliveryService:
    def __init__(
        self,
        *,
        campaign_repository: PromotionCampaignRepository,
        draft_repository: PromotionDraftRepository,
        delivery_repository: PromotionDeliveryRepository,
        meal_conversation_repository: MealConversationRepository,
        notification_repository: NotificationRepository,
    ) -> None:
        self._campaign_repository = campaign_repository
        self._draft_repository = draft_repository
        self._delivery_repository = delivery_repository
        self._meal_conversation_repository = meal_conversation_repository
        self._notification_repository = notification_repository

    async def deliver_campaign(
        self,
        *,
        campaign_id: str,
        current_admin: User,
    ) -> PromotionDeliverResponse:
        campaign = self._campaign_repository.get_campaign(campaign_id)
        if campaign is None:
            raise PromotionDeliveryError("Campaign not found.")

        approved_drafts = self._draft_repository.list_campaign_drafts_by_status(
            campaign_id=campaign_id,
            status="approved",
        )
        queued_count = len(approved_drafts)
        delivered_count = 0
        failed_count = 0

        self._campaign_repository.update_campaign(campaign_id, {"status": "delivering"})
        for draft in approved_drafts:
            try:
                await self._deliver_draft(campaign=campaign, draft=draft)
                delivered_count += 1
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                self._campaign_repository.update_campaign_user(
                    campaign_id=campaign_id,
                    user_id=str(draft["user_id"]),
                    updates={"delivery_status": "failed"},
                )
                self._campaign_repository.append_audit_log(
                    campaign_id=campaign_id,
                    actor_admin_id=current_admin.id,
                    action="delivery_failed",
                    draft_id=str(draft["_id"]),
                    user_id=str(draft["user_id"]),
                    metadata={"error": str(exc)},
                )

        self._campaign_repository.update_campaign(
            campaign_id,
            {"status": "completed" if delivered_count else "approved_for_delivery"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="campaign_delivered",
            metadata={
                "queued_count": queued_count,
                "delivered_count": delivered_count,
                "failed_count": failed_count,
            },
        )
        return PromotionDeliverResponse(
            campaign_id=campaign_id,
            queued_count=queued_count,
            delivered_count=delivered_count,
            failed_count=failed_count,
        )

    def list_deliveries(self, *, campaign_id: str) -> PromotionDeliveryListResponse:
        if self._campaign_repository.get_campaign(campaign_id) is None:
            raise PromotionDeliveryError("Campaign not found.")
        items, total = self._delivery_repository.list_campaign_deliveries(campaign_id=campaign_id)
        return PromotionDeliveryListResponse(
            items=[self._to_delivery_response(item) for item in items],
            total=total,
        )

    def list_audit_logs(self, *, campaign_id: str) -> PromotionAuditLogListResponse:
        if self._campaign_repository.get_campaign(campaign_id) is None:
            raise PromotionDeliveryError("Campaign not found.")
        items, total = self._campaign_repository.list_audit_logs(campaign_id=campaign_id)
        return PromotionAuditLogListResponse(
            items=[
                PromotionAuditLogResponse(
                    id=str(item["_id"]),
                    campaign_id=str(item["campaign_id"]),
                    draft_id=item.get("draft_id"),
                    user_id=item.get("user_id"),
                    actor_admin_id=str(item.get("actor_admin_id") or ""),
                    action=str(item.get("action") or ""),
                    before_payload=item.get("before_payload"),
                    after_payload=item.get("after_payload"),
                    metadata=dict(item.get("metadata") or {}),
                    created_at=item["created_at"],
                )
                for item in items
            ],
            total=total,
        )

    async def _deliver_draft(self, *, campaign: dict[str, Any], draft: dict[str, Any]) -> None:
        payload = dict(draft.get("approved_payload") or {})
        delivery_type = str(payload.get("delivery_type") or campaign.get("delivery_type") or "notification")
        location = str(payload.get("location") or campaign.get("target_location") or "ios.home")
        delivery = self._delivery_repository.create_delivery(
            campaign_id=str(campaign["_id"]),
            draft_id=str(draft["_id"]),
            user_id=str(draft["user_id"]),
            delivery_type=delivery_type,
            location=location,
            payload_sent=payload,
        )
        trace_id = uuid4().hex

        chat_message_id: str | None = None
        if delivery_type == "conversation":
            conversation, assistant_message = self._persist_to_conversation(
                user_id=str(draft["user_id"]),
                payload=payload,
                campaign_id=str(campaign["_id"]),
            )
            chat_message_id = str(assistant_message["_id"])
            await realtime_delivery_service.deliver(
                user_id=str(draft["user_id"]),
                delivery_type="conversation",
                location=location,
                payload={
                    "conversation": self._serialize_conversation(conversation),
                    "assistant_message": self._serialize_message(assistant_message),
                },
                push_payload={
                    "conversation_id": str(conversation["_id"]),
                    "trace_id": trace_id,
                    "status": "completed",
                    "delivery_type": "conversation",
                    "location": location,
                },
                trace_id=trace_id,
                conversation_id=str(conversation["_id"]),
                status="completed",
                channels=["websocket", "push"],
                push_alert_title=str(payload.get("title") or "New message"),
                push_alert_body=str(payload.get("short_message") or payload.get("full_message") or "A new update is ready."),
                metadata={"source": "admin_promotions", "campaign_id": str(campaign["_id"])},
            )
        else:
            await self._deliver_persisted_notification(
                campaign=campaign,
                draft=draft,
                payload=payload,
                trace_id=trace_id,
                location=location,
            )

        self._delivery_repository.update_delivery(
            str(delivery["_id"]),
            {
                "delivery_status": "sent",
                "trace_id": trace_id,
                "chat_message_id": chat_message_id,
                "sent_at": datetime.now(timezone.utc),
            },
        )
        self._campaign_repository.update_campaign_user(
            campaign_id=str(campaign["_id"]),
            user_id=str(draft["user_id"]),
            updates={"delivery_status": "sent"},
        )

    async def _deliver_persisted_notification(
        self,
        *,
        campaign: dict[str, Any],
        draft: dict[str, Any],
        payload: dict[str, Any],
        trace_id: str,
        location: str,
    ) -> None:
        user_id = str(draft["user_id"])
        notification = self._get_or_create_notification(
            campaign=campaign,
            draft=draft,
            payload=payload,
            location=location,
        )
        unread_count = self._notification_repository.unread_count_for_user(user_id=user_id)
        notification_payload = {
            "notification": self._notification_to_response(
                item=notification,
                current_user_id=user_id,
            ).model_dump(mode="json"),
            "unread_count": unread_count,
        }
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="notification",
            location="ios.notifications",
            payload=notification_payload,
            push_payload={
                "notification_id": notification.id,
                "location": "ios.notifications",
                "target": notification.target,
                "title": notification.title,
                "message": notification.message,
            },
            trace_id=trace_id,
            status="completed",
            channels=["websocket", "push"],
            push_alert_title=notification.title,
            push_alert_body=notification.message,
            metadata={
                "source": "admin_promotions",
                "campaign_id": str(campaign["_id"]),
                "notification_id": notification.id,
            },
        )

    def _get_or_create_notification(
        self,
        *,
        campaign: dict[str, Any],
        draft: dict[str, Any],
        payload: dict[str, Any],
        location: str,
    ) -> AppNotification:
        idempotency_key = f"promotion_notification:{campaign['_id']}:{draft['_id']}:{draft['user_id']}"
        notification = self._notification_repository.get_by_idempotency_key(idempotency_key)
        if notification is not None:
            return notification

        navigation_mode = NotificationNavigationMode.DIRECT if location else NotificationNavigationMode.DETAIL
        target = self._build_notification_target(
            location=location,
            draft=draft,
            campaign=campaign,
            payload=payload,
        )
        details = {
            "campaign_id": str(campaign["_id"]),
            "draft_id": str(draft["_id"]),
            "delivery_type": str(payload.get("delivery_type") or ""),
            "location": location,
            "summary": str(payload.get("summary") or ""),
            "highlights": list(payload.get("highlights") or []),
            "cta_primary": str(payload.get("cta_primary") or ""),
            "cta_secondary": str(payload.get("cta_secondary") or ""),
            "image_urls": list(payload.get("image_urls") or []),
            "meal_data": dict(payload.get("meal_data") or {}),
            "grocery_data": dict(payload.get("grocery_data") or {}),
        }
        metadata = {
            "source": "promotion_campaign",
            "campaign_id": str(campaign["_id"]),
            "draft_id": str(draft["_id"]),
            "payload_metadata": dict(payload.get("metadata") or {}),
        }

        try:
            return self._notification_repository.create_notification(
                category=NotificationCategory.SYSTEM,
                notification_type=NotificationType.GENERAL,
                title=str(payload.get("title") or "New update"),
                message=str(payload.get("short_message") or payload.get("full_message") or ""),
                navigation_mode=navigation_mode,
                recipient_user_ids=[str(draft["user_id"])],
                target=target,
                details=details,
                metadata=metadata,
                idempotency_key=idempotency_key,
            )
        except DuplicateKeyError:
            existing = self._notification_repository.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            return existing

    @staticmethod
    def _build_notification_target(
        *,
        location: str,
        draft: dict[str, Any],
        campaign: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        target = {
            "location": location or "ios.home",
            "campaign_id": str(campaign["_id"]),
            "draft_id": str(draft["_id"]),
        }
        for key in ("conversation_id", "message_id", "ui_block_id", "snapshot_id", "saved_plan_id", "tab"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                target[key] = value
        return target

    @staticmethod
    def _notification_to_response(*, item: AppNotification, current_user_id: str) -> NotificationResponse:
        return NotificationResponse(
            id=item.id,
            category=item.category,
            notification_type=item.notification_type,
            title=item.title,
            message=item.message,
            navigation_mode=item.navigation_mode,
            is_read=current_user_id in item.read_by_user_ids,
            target=item.target,
            details=item.details,
            metadata=item.metadata,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    def _persist_to_conversation(
        self,
        *,
        user_id: str,
        payload: dict[str, Any],
        campaign_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        conversation = self._meal_conversation_repository.get_current_conversation(user_id=user_id)
        if conversation is None:
            conversation = self._meal_conversation_repository.create_conversation(
                user_id=user_id,
                user_goal=None,
                agent_type="promotion_delivery",
                status="active",
                current_summary={
                    "user_goal": None,
                    "agent_type": "promotion_delivery",
                    "meal_type": None,
                    "planned_meals": [],
                    "selected_meal_id": None,
                    "selected_meal_name": None,
                    "meal_source": None,
                    "requested_culture": None,
                    "last_user_intent": "promotion_delivery",
                    "last_assistant_preview": None,
                    "latest_ui_blocks": [],
                    "latest_quick_actions": [],
                    "latest_message_id": None,
                    "message_count": 0,
                    "last_message_at": None,
                },
            )

        assistant_message = self._meal_conversation_repository.append_message(
            conversation_id=str(conversation["_id"]),
            role="assistant",
            text=str(payload.get("full_message") or payload.get("short_message") or payload.get("title") or ""),
            ui_blocks=[],
            quick_actions=[],
            metadata={
                "source": "promotion_campaign",
                "campaign_id": campaign_id,
                "delivery_type": payload.get("delivery_type"),
                "location": payload.get("location"),
                "promotion_title": payload.get("title"),
            },
        )
        refreshed = self._meal_conversation_repository.get_conversation(str(conversation["_id"])) or conversation
        summary = dict(refreshed.get("current_summary") or {})
        summary["agent_type"] = str(refreshed.get("agent_type") or summary.get("agent_type") or "promotion_delivery")
        summary["last_assistant_preview"] = str(payload.get("short_message") or payload.get("title") or "")[:240] or None
        summary["latest_message_id"] = str(assistant_message["_id"])
        summary["message_count"] = int(refreshed.get("message_count") or 0)
        summary["last_message_at"] = refreshed.get("last_message_at") or assistant_message.get("created_at")
        updated_conversation = self._meal_conversation_repository.update_conversation_summary(
            conversation_id=str(refreshed["_id"]),
            user_goal=None,
            agent_type=str(refreshed.get("agent_type") or "promotion_delivery"),
            status="active",
            current_summary=summary,
        )
        return updated_conversation or refreshed, assistant_message

    @staticmethod
    def _serialize_message(message: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(message["_id"]),
            "conversation_id": str(message["conversation_id"]),
            "role": str(message.get("role") or ""),
            "text": str(message.get("text") or ""),
            "ui_blocks": list(message.get("ui_blocks") or []),
            "quick_actions": list(message.get("quick_actions") or []),
            "metadata": dict(message.get("metadata") or {}),
            "created_at": message.get("created_at"),
        }

    @staticmethod
    def _serialize_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
        summary = dict(conversation.get("current_summary") or {})
        return {
            "conversation_id": str(conversation["_id"]),
            "agent_type": str(conversation.get("agent_type") or summary.get("agent_type") or "promotion_delivery"),
            "status": str(conversation.get("status") or "active"),
            "meal_type": summary.get("meal_type"),
            "planned_meals": list(summary.get("planned_meals") or []),
            "selected_meal_id": summary.get("selected_meal_id"),
            "selected_meal_name": summary.get("selected_meal_name"),
            "meal_source": summary.get("meal_source"),
            "last_user_intent": summary.get("last_user_intent"),
            "country_code": summary.get("country_code"),
            "requested_culture": summary.get("requested_culture"),
            "last_assistant_preview": summary.get("last_assistant_preview"),
            "latest_ui_blocks": list(summary.get("latest_ui_blocks") or []),
            "latest_quick_actions": list(summary.get("latest_quick_actions") or []),
            "latest_message_id": summary.get("latest_message_id") or conversation.get("latest_message_id"),
            "message_count": int(summary.get("message_count") or conversation.get("message_count") or 0),
            "last_message_at": conversation.get("last_message_at") or summary.get("last_message_at"),
            "updated_at": conversation.get("updated_at"),
            "created_at": conversation.get("created_at"),
        }

    @staticmethod
    def _to_delivery_response(item: dict[str, Any]) -> PromotionDeliveryResponse:
        return PromotionDeliveryResponse(
            id=str(item["_id"]),
            campaign_id=str(item["campaign_id"]),
            draft_id=str(item["draft_id"]),
            user_id=str(item["user_id"]),
            delivery_type=str(item.get("delivery_type") or ""),
            location=str(item.get("location") or ""),
            payload_sent=dict(item.get("payload_sent") or {}),
            delivery_status=str(item.get("delivery_status") or "queued"),
            trace_id=item.get("trace_id"),
            chat_message_id=item.get("chat_message_id"),
            sent_at=item.get("sent_at"),
            failure_reason=item.get("failure_reason"),
            created_at=item["created_at"],
            updated_at=item["updated_at"],
        )
