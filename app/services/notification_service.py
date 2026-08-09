from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.models.notification import (
    AppNotification,
    NotificationCategory,
    NotificationNavigationMode,
    NotificationType,
)
from app.models.saved_meal_plan import SavedMealPlan
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.schemas.notification import (
    NotificationListResponse,
    NotificationReadResponse,
    NotificationResponse,
)
from app.services.notification_copy_service import NotificationCopy, NotificationCopyService
from app.services.realtime_delivery_service import realtime_delivery_service


class NotificationNotFoundError(Exception):
    pass


class NotificationService:
    def __init__(
        self,
        *,
        notification_repository: NotificationRepository,
        saved_meal_plan_repository: SavedMealPlanRepository,
        notification_copy_service: NotificationCopyService | None = None,
    ) -> None:
        self._notification_repository = notification_repository
        self._saved_meal_plan_repository = saved_meal_plan_repository
        self._notification_copy_service = notification_copy_service or NotificationCopyService()

    def list_notifications(
        self,
        *,
        current_user: User,
        before: str | None,
        limit: int,
    ) -> NotificationListResponse:
        items, next_cursor = self._notification_repository.list_for_user(
            user_id=current_user.id,
            before=before,
            limit=limit,
        )
        unread_count = self._notification_repository.unread_count_for_user(user_id=current_user.id)
        return NotificationListResponse(
            items=[self._to_response(item=item, current_user_id=current_user.id) for item in items],
            next_cursor=next_cursor,
            unread_count=unread_count,
        )

    def mark_read(
        self,
        *,
        current_user: User,
        notification_id: str,
    ) -> NotificationReadResponse:
        item = self._notification_repository.mark_read(notification_id=notification_id, user_id=current_user.id)
        if item is None:
            raise NotificationNotFoundError
        unread_count = self._notification_repository.unread_count_for_user(user_id=current_user.id)
        return NotificationReadResponse(
            notification=self._to_response(item=item, current_user_id=current_user.id),
            unread_count=unread_count,
        )

    async def scan_and_deliver_unsaved_plan_reminders(self, *, scan_limit: int = 500) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        plans, _ = self._saved_meal_plan_repository.list_saved_plans(
            status="draft",
            updated_before=cutoff,
            limit=scan_limit,
        )
        for plan in plans:
            if plan.parent_saved_plan_id is not None:
                continue
            await self._create_and_deliver_unsaved_plan_notification(saved_plan=plan)

    async def _create_and_deliver_unsaved_plan_notification(
        self,
        *,
        saved_plan: SavedMealPlan,
    ) -> None:
        user_id = str(saved_plan.user_id or "").strip()
        if not user_id:
            return

        payload = dict(saved_plan.plan_payload or {})
        view_mode = str(payload.get("view_mode") or saved_plan.view_mode or "day").lower()
        period_label = str(payload.get("period_label") or payload.get("effective_date") or saved_plan.title or "").strip()
        snapshot_id = str(payload.get("snapshot_id") or saved_plan.source_snapshot_id or saved_plan.id).strip()
        copy = self.unsaved_meal_plan_reminder_copy(
            period_label=period_label or None,
            view_mode=view_mode,
        )
        target = {
            "location": "ios.home",
            "tab": "plan",
            "saved_plan_id": saved_plan.id,
            "snapshot_id": snapshot_id,
            "view_mode": view_mode,
        }
        details = {
            "saved_plan_id": saved_plan.id,
            "snapshot_id": snapshot_id,
            "period_label": payload.get("period_label"),
            "view_mode": view_mode,
            "status": saved_plan.status,
        }
        metadata = {
            "source": "unsaved_meal_plan_reminder",
            "saved_plan_id": saved_plan.id,
            "snapshot_id": snapshot_id,
        }
        notification_image_url = self._notification_image_url_for_saved_plan(saved_plan)
        idempotency_key = f"unsaved_plan:{user_id}:{snapshot_id}"

        item = self._notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            try:
                item = self._notification_repository.create_notification(
                    category=NotificationCategory.PLANNER,
                    notification_type=NotificationType.UNSAVED_MEAL_PLAN_REMINDER,
                    title=copy.title,
                    message=copy.message,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                    recipient_user_ids=[user_id],
                    target=target,
                    details=details,
                    metadata=metadata,
                    idempotency_key=idempotency_key,
                )
            except DuplicateKeyError:
                item = self._notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            return

        unread_count = self._notification_repository.unread_count_for_user(user_id=user_id)
        payload_data = {
            "notification": self._to_response(item=item, current_user_id=user_id).model_dump(mode="json"),
            "unread_count": unread_count,
        }
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="notification",
            location="ios.notifications",
            payload=payload_data,
            push_payload={
                "notification_id": item.id,
                "location": "ios.notifications",
                "target": target,
                "title": item.title,
                "message": item.message,
                "notification_image_url": notification_image_url,
            },
            trace_id=uuid4().hex,
            status="completed",
            channels=["websocket", "push"],
            push_alert_title=item.title,
            push_alert_body=item.message,
            metadata={"source": "notification_service", "notification_id": item.id},
        )

    async def create_and_deliver_meal_plan_approved_notification(
        self,
        *,
        user_id: str,
        conversation_id: str,
        saved_plan_id: str,
        snapshot_id: str,
        view_mode: str,
        period_label: str | None,
        message_id: str | None,
        ui_block_id: str | None,
    ) -> None:
        normalized_user_id = str(user_id or "").strip()
        normalized_snapshot_id = str(snapshot_id or "").strip()
        if not normalized_user_id or not normalized_snapshot_id:
            return

        copy = self.meal_plan_approved_copy(
            period_label=(period_label or "").strip() or None,
            view_mode=view_mode,
        )
        saved_plan = None
        normalized_saved_plan_id = str(saved_plan_id or "").strip()
        if normalized_saved_plan_id:
            saved_plan = self._saved_meal_plan_repository.get_saved_plan(
                user_id=normalized_user_id,
                saved_plan_id=normalized_saved_plan_id,
            )
        resolved_view_mode = str(
            (saved_plan.view_mode if saved_plan is not None else view_mode) or "day"
        ).lower()
        effective_date = None
        week_start = None
        week_end = None
        if saved_plan is not None:
            effective_date = (
                saved_plan.effective_date.isoformat()
                if saved_plan.effective_date is not None
                else None
            )
            week_start = saved_plan.week_start.isoformat() if saved_plan.week_start is not None else None
            week_end = saved_plan.week_end.isoformat() if saved_plan.week_end is not None else None
        target_date = effective_date or week_start
        target = {
            "location": "ios.home",
            "tab": "home",
            "target_kind": "saved_meal_plan",
            "notification_focus": "saved_meal_plan",
            "message_id": message_id,
            "ui_block_id": ui_block_id,
            "snapshot_id": normalized_snapshot_id,
            "saved_plan_id": normalized_saved_plan_id,
            "view_mode": resolved_view_mode,
            "effective_date": target_date,
            "week_start": week_start,
            "week_end": week_end,
        }
        details = {
            "saved_plan_id": normalized_saved_plan_id,
            "snapshot_id": normalized_snapshot_id,
            "period_label": (period_label or "").strip() or None,
            "view_mode": resolved_view_mode,
            "effective_date": effective_date,
            "week_start": week_start,
            "week_end": week_end,
            "conversation_id": str(conversation_id or ""),
        }
        metadata = {
            "source": "meal_plan_approved",
            "conversation_id": str(conversation_id or ""),
            "message_id": message_id,
            "ui_block_id": ui_block_id,
        }
        idempotency_key = f"approved_plan:{normalized_user_id}:{normalized_snapshot_id}"
        await self._create_and_deliver_notification(
            user_id=normalized_user_id,
            notification_type=NotificationType.MEAL_PLAN_APPROVED,
            title=copy.title,
            message=copy.message,
            target=target,
            details=details,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    async def create_and_deliver_meal_slot_reminder(
        self,
        *,
        user_id: str,
        conversation_id: str,
        saved_plan_id: str,
        snapshot_id: str,
        effective_date: str | None,
        meal_slot: str,
        meal_name: str,
        section_title: str | None,
        meal_item: dict[str, Any] | None,
        time_label: str,
        message_id: str | None = None,
        ui_block_id: str | None = None,
    ) -> None:
        normalized_user_id = str(user_id or "").strip()
        normalized_snapshot_id = str(snapshot_id or "").strip()
        normalized_saved_plan_id = str(saved_plan_id or "").strip()
        normalized_meal_slot = str(meal_slot or "").strip().lower()
        normalized_meal_name = str(meal_name or "").strip()
        if (
            not normalized_user_id
            or not normalized_snapshot_id
            or not normalized_saved_plan_id
            or not normalized_meal_slot
            or not normalized_meal_name
        ):
            return

        copy = self.meal_slot_reminder_copy(
            meal_name=normalized_meal_name,
            meal_slot=normalized_meal_slot,
            time_label=time_label,
        )
        target = {
            "location": "ios.home",
            "tab": "home",
            "target_kind": "meal_slot_detail",
            "snapshot_id": normalized_snapshot_id,
            "saved_plan_id": normalized_saved_plan_id,
            "notification_focus": "meal_detail",
            "meal_slot": normalized_meal_slot,
            "meal_id": str((meal_item or {}).get("meal_id") or "").strip() or None,
            "meal_name": normalized_meal_name,
            "effective_date": effective_date,
            "section_title": str(section_title or "").strip() or None,
            "meal_item": dict(meal_item or {}),
        }
        details = {
            "saved_plan_id": normalized_saved_plan_id,
            "snapshot_id": normalized_snapshot_id,
            "effective_date": effective_date,
            "meal_slot": normalized_meal_slot,
            "meal_name": normalized_meal_name,
            "section_title": str(section_title or "").strip() or None,
            "conversation_id": str(conversation_id or ""),
            "message_id": message_id,
            "ui_block_id": ui_block_id,
        }
        metadata = {
            "source": "meal_slot_reminder",
            "conversation_id": str(conversation_id or ""),
            "saved_plan_id": normalized_saved_plan_id,
            "effective_date": effective_date,
            "message_id": message_id,
            "ui_block_id": ui_block_id,
        }
        idempotency_key = (
            f"meal_slot_reminder:{normalized_user_id}:{normalized_saved_plan_id}:"
            f"{effective_date or 'unknown'}:{normalized_meal_slot}"
        )
        await self._create_and_deliver_notification(
            user_id=normalized_user_id,
            notification_type=NotificationType.MEAL_SLOT_REMINDER,
            title=copy.title,
            message=copy.message,
            target=target,
            details=details,
            metadata=metadata,
            idempotency_key=idempotency_key,
            push_payload_extra={
                "notification_image_url": self._notification_image_url_for_meal_item(meal_item),
            },
        )

    def unsaved_meal_plan_reminder_copy(
        self,
        *,
        period_label: str | None = None,
        view_mode: str | None = None,
    ) -> NotificationCopy:
        return self._notification_copy_service.for_unsaved_meal_plan_reminder(
            period_label=period_label,
            view_mode=view_mode,
        )

    def meal_plan_approved_copy(
        self,
        *,
        period_label: str | None = None,
        view_mode: str | None = None,
    ) -> NotificationCopy:
        return self._notification_copy_service.for_meal_plan_approved(
            period_label=period_label,
            view_mode=view_mode,
        )

    def meal_slot_reminder_copy(
        self,
        *,
        meal_name: str,
        meal_slot: str,
        time_label: str,
    ) -> NotificationCopy:
        return self._notification_copy_service.for_meal_slot_reminder(
            meal_name=meal_name,
            meal_slot=meal_slot,
            time_label=time_label,
        )

    async def _create_and_deliver_notification(
        self,
        *,
        user_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
        target: dict[str, Any],
        details: dict[str, Any],
        metadata: dict[str, Any],
        idempotency_key: str,
        push_payload_extra: dict[str, Any] | None = None,
    ) -> None:
        item = self._notification_repository.get_by_idempotency_key(idempotency_key)
        if item is None:
            try:
                item = self._notification_repository.create_notification(
                    category=NotificationCategory.PLANNER,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    navigation_mode=NotificationNavigationMode.DIRECT,
                    recipient_user_ids=[user_id],
                    target=target,
                    details=details,
                    metadata=metadata,
                    idempotency_key=idempotency_key,
                )
            except DuplicateKeyError:
                item = self._notification_repository.get_by_idempotency_key(idempotency_key)
        if item is not None:
            item = self._notification_repository.update_notification_content(
                notification_id=item.id,
                title=title,
                message=message,
                target=target,
                details=details,
                metadata=metadata,
                navigation_mode=NotificationNavigationMode.DIRECT,
            )
        if item is None:
            return

        unread_count = self._notification_repository.unread_count_for_user(user_id=user_id)
        payload_data = {
            "notification": self._to_response(item=item, current_user_id=user_id).model_dump(mode="json"),
            "unread_count": unread_count,
        }
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="notification",
            location="ios.notifications",
            payload=payload_data,
            push_payload={
                "notification_id": item.id,
                "location": "ios.notifications",
                "target": target,
                "title": item.title,
                "message": item.message,
                **(push_payload_extra or {}),
            },
            trace_id=uuid4().hex,
            status="completed",
            channels=["websocket", "push"],
            push_alert_title=item.title,
            push_alert_body=item.message,
            metadata={"source": "notification_service", "notification_id": item.id},
        )

    @classmethod
    def _notification_image_url_for_saved_plan(cls, saved_plan: SavedMealPlan) -> str | None:
        payload = dict(saved_plan.plan_payload or {})
        planned_meals = list(saved_plan.planned_meals or [])

        return (
            cls._extract_first_image_url(payload)
            or cls._extract_first_image_url(planned_meals)
        )

    @classmethod
    def _notification_image_url_for_meal_item(cls, meal_item: dict[str, Any] | None) -> str | None:
        return cls._extract_first_image_url(dict(meal_item or {}))

    @classmethod
    def _extract_first_image_url(cls, value: Any) -> str | None:
        if isinstance(value, dict):
            direct_keys = (
                "notification_image_url",
                "hero_image_url",
                "image_url",
            )
            for key in direct_keys:
                resolved = cls._normalized_http_url(value.get(key))
                if resolved:
                    return resolved

            image_urls = value.get("image_urls")
            if isinstance(image_urls, list):
                for item in image_urls:
                    resolved = cls._normalized_http_url(item)
                    if resolved:
                        return resolved

            for nested in value.values():
                resolved = cls._extract_first_image_url(nested)
                if resolved:
                    return resolved
            return None

        if isinstance(value, list):
            for item in value:
                resolved = cls._extract_first_image_url(item)
                if resolved:
                    return resolved
            return None

        return cls._normalized_http_url(value)

    @staticmethod
    def _normalized_http_url(value: Any) -> str | None:
        normalized = str(value or "").strip()
        if normalized.startswith("https://") or normalized.startswith("http://"):
            return normalized
        return None

    @staticmethod
    def _to_response(*, item: AppNotification, current_user_id: str) -> NotificationResponse:
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
