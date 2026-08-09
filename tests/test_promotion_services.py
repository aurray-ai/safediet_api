from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from app.models.notification import (
    AppNotification,
    NotificationCategory,
    NotificationNavigationMode,
    NotificationType,
)
from app.core.config import Settings
from app.models.user import User, UserType
from app.schemas.admin_promotion import PromotionContentPayload
from app.services.admin_promotion_service import AdminPromotionService
from app.services.promotion_delivery_service import PromotionDeliveryService
from app.services.promotion_generation_service import PromotionGenerationService
from app.services.promotion_review_service import PromotionReviewService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeCampaignRepository:
    def __init__(self) -> None:
        now = utc_now()
        self.campaigns = {
            "camp-1": {
                "_id": "camp-1",
                "name": "Breakfast push",
                "created_by_admin_id": "admin-1",
                "status": "draft",
                "promotion_type": "meal_promotion",
                "delivery_type": "conversation",
                "target_location": "ios.conversations",
                "admin_instruction": "Create a breakfast-focused promotion.",
                "tone": "warm",
                "constraints": {},
                "selected_user_count": 1,
                "created_at": now,
                "updated_at": now,
            }
        }
        self.campaign_users = {
            ("camp-1", "user-1"): {
                "_id": "camp-user-1",
                "campaign_id": "camp-1",
                "user_id": "user-1",
                "context_status": "ready",
                "generation_status": "pending",
                "review_status": "pending",
                "delivery_status": "pending",
                "created_at": now,
                "updated_at": now,
            }
        }
        self.context_snapshots = {
            ("camp-1", "user-1"): {
                "_id": "ctx-1",
                "campaign_id": "camp-1",
                "user_id": "user-1",
                "conversation_summary": "Milk-free breakfast idea ready.",
                "recent_messages_summary": [
                    {"role": "user", "text": "I want a quick free of milk breakfast", "created_at": now}
                ],
                "latest_plan_summary": "Planned 1/1 meals",
                "profile_snapshot": {"name": "Ada", "email": "ada@example.com"},
                "preference_snapshot": {
                    "goal": "weight_loss",
                    "culture_preferences": ["nigerian"],
                    "allergies": ["milk"],
                    "diet_rules": [],
                },
                "eligibility_snapshot": {"has_recent_conversation": True},
                "source_refs": {"latest_conversation_id": "conv-1"},
                "created_at": now,
            }
        }
        self.audit_logs: list[dict] = []

    def get_campaign(self, campaign_id: str):
        return self.campaigns.get(campaign_id)

    def update_campaign(self, campaign_id: str, updates: dict):
        campaign = self.campaigns[campaign_id]
        campaign.update(updates)
        campaign["updated_at"] = utc_now()
        return campaign

    def list_campaign_users(self, *, campaign_id: str):
        return [value for (cid, _), value in self.campaign_users.items() if cid == campaign_id]

    def get_campaign_user(self, *, campaign_id: str, user_id: str):
        return self.campaign_users.get((campaign_id, user_id))

    def add_campaign_users(self, *, campaign_id: str, user_ids: list[str]):
        now = utc_now()
        inserted = 0
        for user_id in user_ids:
            key = (campaign_id, user_id)
            if key in self.campaign_users:
                self.campaign_users[key]["updated_at"] = now
                continue
            self.campaign_users[key] = {
                "_id": f"camp-user-{len(self.campaign_users) + 1}",
                "campaign_id": campaign_id,
                "user_id": user_id,
                "context_status": "pending",
                "generation_status": "pending",
                "review_status": "pending",
                "delivery_status": "pending",
                "created_at": now,
                "updated_at": now,
            }
            inserted += 1
        if inserted:
            self.campaigns[campaign_id]["selected_user_count"] = int(
                self.campaigns[campaign_id].get("selected_user_count") or 0
            ) + inserted
            self.campaigns[campaign_id]["updated_at"] = now
        return inserted

    def update_campaign_user(self, *, campaign_id: str, user_id: str, updates: dict):
        record = self.campaign_users[(campaign_id, user_id)]
        record.update(updates)
        record["updated_at"] = utc_now()
        return record

    def get_latest_context_snapshot(self, *, campaign_id: str, user_id: str):
        return self.context_snapshots.get((campaign_id, user_id))

    def replace_context_snapshot(self, *, campaign_id: str, user_id: str, snapshot: dict):
        document = {
            "_id": f"ctx-{len(self.context_snapshots) + 1}",
            "campaign_id": campaign_id,
            "user_id": user_id,
            **snapshot,
            "created_at": utc_now(),
        }
        self.context_snapshots[(campaign_id, user_id)] = document
        self.update_campaign_user(
            campaign_id=campaign_id,
            user_id=user_id,
            updates={"context_status": "ready"},
        )
        return document

    def append_audit_log(self, **kwargs):
        self.audit_logs.append(kwargs)
        return kwargs

    def list_audit_logs(self, *, campaign_id: str):
        items = [item for item in self.audit_logs if item["campaign_id"] == campaign_id]
        return items, len(items)


class FakeDraftRepository:
    def __init__(self) -> None:
        self.drafts: dict[str, dict] = {}

    def next_generation_version(self, *, campaign_id: str, user_id: str) -> int:
        versions = [
            int(draft.get("generation_version") or 0)
            for draft in self.drafts.values()
            if draft["campaign_id"] == campaign_id and draft["user_id"] == user_id
        ]
        return (max(versions) if versions else 0) + 1

    def create_draft(self, *, campaign_id: str, user_id: str, context_snapshot_id: str, generated_payload: dict, validation_warnings=None):
        now = utc_now()
        draft_id = f"draft-{len(self.drafts) + 1}"
        document = {
            "_id": draft_id,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "context_snapshot_id": context_snapshot_id,
            "generated_payload": generated_payload,
            "working_payload": dict(generated_payload),
            "approved_payload": None,
            "is_admin_edited": False,
            "edited_by_admin_id": None,
            "edited_at": None,
            "approved_by_admin_id": None,
            "approved_at": None,
            "generation_version": self.next_generation_version(campaign_id=campaign_id, user_id=user_id),
            "edit_version": 0,
            "status": "generated",
            "validation_warnings": validation_warnings or [],
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        self.drafts[draft_id] = document
        return document

    def create_failed_draft(self, *, campaign_id: str, user_id: str, context_snapshot_id: str, failure_reason: str):
        now = utc_now()
        draft_id = f"draft-{len(self.drafts) + 1}"
        document = {
            "_id": draft_id,
            "campaign_id": campaign_id,
            "user_id": user_id,
            "context_snapshot_id": context_snapshot_id,
            "generated_payload": {
                "title": "Generation failed",
                "short_message": "",
                "full_message": "",
                "summary": failure_reason,
                "highlights": [],
                "cta_primary": "Review",
                "cta_secondary": "",
                "delivery_type": "notification",
                "location": "ios.home",
                "specs": [],
                "image_urls": [],
                "meal_data": {},
                "grocery_data": {},
                "metadata": {},
            },
            "working_payload": {},
            "approved_payload": None,
            "is_admin_edited": False,
            "edited_by_admin_id": None,
            "edited_at": None,
            "approved_by_admin_id": None,
            "approved_at": None,
            "generation_version": 1,
            "edit_version": 0,
            "status": "failed",
            "validation_warnings": [],
            "failure_reason": failure_reason,
            "created_at": now,
            "updated_at": now,
        }
        self.drafts[draft_id] = document
        return document

    def get_draft(self, draft_id: str):
        return self.drafts.get(draft_id)

    def update_draft(self, draft_id: str, updates: dict):
        draft = self.drafts[draft_id]
        draft.update(updates)
        draft["updated_at"] = utc_now()
        return draft

    def list_campaign_drafts(self, *, campaign_id: str):
        items = [draft for draft in self.drafts.values() if draft["campaign_id"] == campaign_id]
        return items, len(items)

    def list_campaign_drafts_by_status(self, *, campaign_id: str, status: str):
        return [draft for draft in self.drafts.values() if draft["campaign_id"] == campaign_id and draft["status"] == status]


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.deliveries: dict[str, dict] = {}

    def create_delivery(self, *, campaign_id: str, draft_id: str, user_id: str, delivery_type: str, location: str, payload_sent: dict):
        now = utc_now()
        delivery_id = f"delivery-{len(self.deliveries) + 1}"
        document = {
            "_id": delivery_id,
            "campaign_id": campaign_id,
            "draft_id": draft_id,
            "user_id": user_id,
            "delivery_type": delivery_type,
            "location": location,
            "payload_sent": payload_sent,
            "delivery_status": "queued",
            "trace_id": None,
            "chat_message_id": None,
            "sent_at": None,
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
        self.deliveries[delivery_id] = document
        return document

    def update_delivery(self, delivery_id: str, updates: dict):
        delivery = self.deliveries[delivery_id]
        delivery.update(updates)
        delivery["updated_at"] = utc_now()
        return delivery

    def list_campaign_deliveries(self, *, campaign_id: str):
        items = [delivery for delivery in self.deliveries.values() if delivery["campaign_id"] == campaign_id]
        return items, len(items)


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.notifications: dict[str, AppNotification] = {}

    def create_notification(
        self,
        *,
        category: NotificationCategory,
        notification_type: NotificationType,
        title: str,
        message: str,
        navigation_mode: NotificationNavigationMode,
        recipient_user_ids: list[str],
        target: dict,
        details: dict,
        metadata: dict,
        idempotency_key: str | None = None,
    ) -> AppNotification:
        now = utc_now()
        item = AppNotification(
            id=uuid4().hex,
            category=category,
            notification_type=notification_type,
            title=title,
            message=message,
            navigation_mode=navigation_mode,
            recipient_user_ids=list(recipient_user_ids),
            read_by_user_ids=[],
            target=dict(target),
            details=dict(details),
            metadata=dict(metadata),
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        self.notifications[item.id] = item
        return item

    def get_by_idempotency_key(self, idempotency_key: str) -> AppNotification | None:
        for item in self.notifications.values():
            if item.idempotency_key == idempotency_key:
                return item
        return None

    def unread_count_for_user(self, *, user_id: str) -> int:
        return sum(
            1
            for item in self.notifications.values()
            if user_id in item.recipient_user_ids and user_id not in item.read_by_user_ids
        )


class FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self.users = {user.id: user for user in users}

    def find_by_id(self, user_id: str):
        return self.users.get(user_id)

    def list_by_ids(self, user_ids: list[str]):
        return [self.users[user_id] for user_id in user_ids if user_id in self.users]


class FakeMealConversationRepository:
    def __init__(self) -> None:
        now = utc_now()
        self.conversations = {
            "conv-1": {
                "_id": "conv-1",
                "user_id": "user-1",
                "agent_type": "meal_coordinator",
                "status": "active",
                "current_summary": {
                    "agent_type": "meal_coordinator",
                    "meal_type": "breakfast",
                    "planned_meals": [],
                    "selected_meal_id": None,
                    "selected_meal_name": None,
                    "meal_source": None,
                    "requested_culture": "nigerian",
                    "last_user_intent": "breakfast help",
                    "last_assistant_preview": "Quick breakfast ready.",
                    "latest_ui_blocks": [],
                    "latest_quick_actions": [],
                    "latest_message_id": None,
                    "message_count": 0,
                    "last_message_at": now,
                },
                "created_at": now,
                "updated_at": now,
                "last_message_at": now,
                "message_count": 0,
            }
        }
        self.messages: list[dict] = []

    def get_current_conversation(self, *, user_id: str, user_goal: str | None = None):
        for conversation in self.conversations.values():
            if conversation["user_id"] == user_id and conversation["status"] == "active":
                if user_goal is not None and conversation.get("user_goal") != user_goal:
                    continue
                return conversation
        return None

    def find_reusable_conversation(self, *, user_id: str, user_goal: str):
        for conversation in sorted(
            self.conversations.values(),
            key=lambda item: item["updated_at"],
            reverse=True,
        ):
            if conversation["user_id"] == user_id and conversation.get("user_goal") == user_goal:
                return conversation
        return None

    def list_recent_conversations(self, *, user_id: str, limit: int):
        items = [
            conversation
            for conversation in self.conversations.values()
            if conversation["user_id"] == user_id
        ]
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items[:limit]

    def list_recent_messages(self, conversation_id: str, limit: int):
        items = [
            message
            for message in self.messages
            if message["conversation_id"] == conversation_id
        ]
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items[:limit]

    def create_conversation(self, *, user_id: str, user_goal: str | None, agent_type: str, status: str, current_summary: dict):
        now = utc_now()
        conversation = {
            "_id": f"conv-{len(self.conversations) + 1}",
            "user_id": user_id,
            "user_goal": user_goal,
            "agent_type": agent_type,
            "status": status,
            "current_summary": current_summary,
            "created_at": now,
            "updated_at": now,
            "last_message_at": None,
            "message_count": 0,
        }
        self.conversations[conversation["_id"]] = conversation
        return conversation

    def append_message(self, *, conversation_id: str, role: str, text: str, ui_blocks: list, quick_actions: list, metadata=None):
        now = utc_now()
        message = {
            "_id": f"msg-{len(self.messages) + 1}",
            "conversation_id": conversation_id,
            "role": role,
            "text": text,
            "ui_blocks": ui_blocks,
            "quick_actions": quick_actions,
            "metadata": metadata or {},
            "created_at": now,
        }
        self.messages.append(message)
        conversation = self.conversations[conversation_id]
        conversation["last_message_at"] = now
        conversation["latest_message_id"] = message["_id"]
        conversation["message_count"] = int(conversation.get("message_count") or 0) + 1
        return message

    def get_conversation(self, conversation_id: str):
        return self.conversations.get(conversation_id)

    def update_conversation_summary(self, *, conversation_id: str, user_goal: str | None, agent_type: str, status: str, current_summary: dict):
        conversation = self.conversations[conversation_id]
        conversation["user_goal"] = user_goal
        conversation["agent_type"] = agent_type
        conversation["status"] = status
        conversation["current_summary"] = current_summary
        conversation["updated_at"] = utc_now()
        return conversation


class FakePromotionContextService:
    def build_snapshot(self, *, user: User):
        return {
            "conversation_summary": f"Prepared context for {user.name}",
            "recent_messages_summary": [],
            "latest_plan_summary": "1 meal request ready for promotion",
            "profile_snapshot": {"name": user.name, "email": user.email},
            "preference_snapshot": {"goal": "weight_loss"},
            "eligibility_snapshot": {"has_recent_conversation": True},
            "source_refs": {"latest_conversation_id": "conv-prepared"},
        }


class PromotionServicesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.user = User(
            id="user-1",
            name="Ada",
            email="ada@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.admin = User(
            id="admin-1",
            name="Admin",
            email="admin@example.com",
            password_hash="x",
            user_types=[UserType.PLATFORM_USER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.campaign_repo = FakeCampaignRepository()
        self.draft_repo = FakeDraftRepository()
        self.delivery_repo = FakeDeliveryRepository()
        self.extra_user = User(
            id="user-2",
            name="Bola",
            email="bola@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.user_repo = FakeUserRepository([self.user, self.extra_user, self.admin])
        self.meal_conversation_repo = FakeMealConversationRepository()

    def test_generation_service_falls_back_without_llm(self) -> None:
        service = PromotionGenerationService(
            settings=Settings(openai_api_key=None),
            campaign_repository=self.campaign_repo,
            draft_repository=self.draft_repo,
            user_repository=self.user_repo,
        )

        response = service.generate_user_draft(
            campaign_id="camp-1",
            user_id="user-1",
            current_admin=self.admin,
        )

        self.assertEqual(response.status, "generated")
        self.assertEqual(response.working_payload.delivery_type, "conversation")
        self.assertEqual(response.working_payload.location, "ios.conversations")
        self.assertEqual(response.working_payload.metadata["generation_source"], "fallback")
        self.assertIn("weight loss", response.working_payload.full_message.lower())

    def test_review_service_updates_and_approves_working_payload(self) -> None:
        base_payload = PromotionContentPayload(
            title="Original title",
            short_message="Short preview",
            full_message="Original full message",
            summary="Original summary",
            highlights=["One"],
            cta_primary="Open chat",
            cta_secondary="View details",
            delivery_type="conversation",
            location="ios.conversations",
            specs=[],
            image_urls=[],
            meal_data={},
            grocery_data={},
            metadata={},
        )
        draft = self.draft_repo.create_draft(
            campaign_id="camp-1",
            user_id="user-1",
            context_snapshot_id="ctx-1",
            generated_payload=base_payload.model_dump(mode="json"),
        )
        review_service = PromotionReviewService(
            campaign_repository=self.campaign_repo,
            draft_repository=self.draft_repo,
        )

        updated_payload = PromotionContentPayload(
            **{
                **base_payload.model_dump(mode="json"),
                "title": "Edited title",
                "full_message": "Edited full message",
            }
        )
        update_response = review_service.update_working_payload(
            draft_id=str(draft["_id"]),
            current_admin=self.admin,
            working_payload=updated_payload,
        )
        self.assertEqual(update_response.status, "edited")
        self.assertEqual(self.draft_repo.get_draft(str(draft["_id"]))["generated_payload"]["title"], "Original title")
        self.assertEqual(self.draft_repo.get_draft(str(draft["_id"]))["working_payload"]["title"], "Edited title")

        approve_response = review_service.approve_draft(
            draft_id=str(draft["_id"]),
            current_admin=self.admin,
        )
        self.assertEqual(approve_response.status, "approved")
        self.assertEqual(self.draft_repo.get_draft(str(draft["_id"]))["approved_payload"]["title"], "Edited title")

    def test_add_users_prepares_context_for_new_users(self) -> None:
        service = AdminPromotionService(
            campaign_repository=self.campaign_repo,
            user_repository=self.user_repo,
            meal_conversation_repository=self.meal_conversation_repo,
            promotion_context_service=FakePromotionContextService(),
        )

        response = service.add_users(
            campaign_id="camp-1",
            current_admin=self.admin,
            user_ids=["user-2"],
        )

        self.assertEqual(response.total, 2)
        campaign_user = self.campaign_repo.get_campaign_user(campaign_id="camp-1", user_id="user-2")
        self.assertIsNotNone(campaign_user)
        assert campaign_user is not None
        self.assertEqual(campaign_user["context_status"], "ready")
        snapshot = self.campaign_repo.get_latest_context_snapshot(campaign_id="camp-1", user_id="user-2")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["conversation_summary"], "Prepared context for Bola")
        self.assertEqual(self.campaign_repo.campaigns["camp-1"]["selected_user_count"], 2)
        self.assertEqual(self.campaign_repo.audit_logs[-1]["metadata"]["context_ready_count"], 1)

    def test_get_user_profile_includes_campaign_membership_and_recent_context(self) -> None:
        service = AdminPromotionService(
            campaign_repository=self.campaign_repo,
            user_repository=self.user_repo,
            meal_conversation_repository=self.meal_conversation_repo,
            promotion_context_service=FakePromotionContextService(),
        )

        response = service.get_user_profile(user_id="user-1", campaign_id="camp-1")

        self.assertEqual(response.id, "user-1")
        self.assertEqual(response.email, "ada@example.com")
        self.assertEqual(len(response.recent_conversations), 1)
        self.assertEqual(len(response.recent_messages), 0)
        self.assertIsNotNone(response.campaign_membership)
        assert response.campaign_membership is not None
        self.assertEqual(response.campaign_membership.context_status, "ready")
        self.assertIsNotNone(response.campaign_membership.context_snapshot)


class PromotionDeliveryAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user = User(
            id="user-1",
            name="Ada",
            email="ada@example.com",
            password_hash="x",
            user_types=[UserType.CUSTOMER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.admin = User(
            id="admin-1",
            name="Admin",
            email="admin@example.com",
            password_hash="x",
            user_types=[UserType.PLATFORM_USER],
            user_configuration={},
            created_at=utc_now(),
        )
        self.campaign_repo = FakeCampaignRepository()
        self.draft_repo = FakeDraftRepository()
        self.delivery_repo = FakeDeliveryRepository()
        self.meal_conversation_repo = FakeMealConversationRepository()
        self.notification_repo = FakeNotificationRepository()
        payload = PromotionContentPayload(
            title="Breakfast is ready",
            short_message="A quick breakfast idea is ready.",
            full_message="Try a quick tofu scramble with spinach and avocado.",
            summary="Quick milk-free breakfast.",
            highlights=["Milk-free", "Fast", "Protein-forward"],
            cta_primary="Open chat",
            cta_secondary="View details",
            delivery_type="conversation",
            location="ios.conversations",
            specs=[],
            image_urls=[],
            meal_data={},
            grocery_data={},
            metadata={},
        )
        draft = self.draft_repo.create_draft(
            campaign_id="camp-1",
            user_id="user-1",
            context_snapshot_id="ctx-1",
            generated_payload=payload.model_dump(mode="json"),
        )
        self.draft_repo.update_draft(
            str(draft["_id"]),
            {
                "approved_payload": payload.model_dump(mode="json"),
                "status": "approved",
            },
        )
        self.delivery_service = PromotionDeliveryService(
            campaign_repository=self.campaign_repo,
            draft_repository=self.draft_repo,
            delivery_repository=self.delivery_repo,
            meal_conversation_repository=self.meal_conversation_repo,
            notification_repository=self.notification_repo,
        )

    async def test_delivery_service_persists_final_conversation_message(self) -> None:
        with patch(
            "app.services.promotion_delivery_service.realtime_delivery_service.deliver",
            new=AsyncMock(),
        ) as deliver_mock:
            response = await self.delivery_service.deliver_campaign(
                campaign_id="camp-1",
                current_admin=self.admin,
            )

        self.assertEqual(response.delivered_count, 1)
        self.assertEqual(len(self.meal_conversation_repo.messages), 1)
        self.assertEqual(self.meal_conversation_repo.messages[0]["role"], "assistant")
        self.assertEqual(
            self.meal_conversation_repo.messages[0]["metadata"]["source"],
            "promotion_campaign",
        )
        self.assertTrue(deliver_mock.await_count >= 1)
        deliveries, total = self.delivery_repo.list_campaign_deliveries(campaign_id="camp-1")
        self.assertEqual(total, 1)
        self.assertEqual(deliveries[0]["delivery_status"], "sent")
        self.assertIsNotNone(deliveries[0]["chat_message_id"])
        self.assertEqual(deliver_mock.await_args.kwargs["channels"], ["websocket", "push"])
        self.assertEqual(len(self.notification_repo.notifications), 0)

    async def test_notification_delivery_persists_notification_and_routes_through_inbox(self) -> None:
        payload = PromotionContentPayload(
            title="Budget-friendly lunch picks",
            short_message="Fresh ideas picked for your week.",
            full_message="We picked a few affordable lunch options based on your preferences.",
            summary="Affordable lunch promotion.",
            highlights=["Budget-aware", "Quick prep"],
            cta_primary="Open home",
            cta_secondary="See options",
            delivery_type="notification",
            location="ios.home",
            specs=[],
            image_urls=[],
            meal_data={},
            grocery_data={},
            metadata={},
        )
        draft = self.draft_repo.get_draft("draft-1")
        assert draft is not None
        self.draft_repo.update_draft(
            str(draft["_id"]),
            {
                "approved_payload": payload.model_dump(mode="json"),
                "status": "approved",
            },
        )
        self.campaign_repo.update_campaign(
            "camp-1",
            {
                "delivery_type": "notification",
                "target_location": "ios.home",
            },
        )

        with patch(
            "app.services.promotion_delivery_service.realtime_delivery_service.deliver",
            new=AsyncMock(),
        ) as deliver_mock:
            response = await self.delivery_service.deliver_campaign(
                campaign_id="camp-1",
                current_admin=self.admin,
            )

        self.assertEqual(response.delivered_count, 1)
        self.assertEqual(len(self.meal_conversation_repo.messages), 0)
        self.assertEqual(len(self.notification_repo.notifications), 1)

        notification = next(iter(self.notification_repo.notifications.values()))
        self.assertEqual(notification.title, "Budget-friendly lunch picks")
        self.assertEqual(notification.navigation_mode, NotificationNavigationMode.DIRECT)
        self.assertEqual(notification.target["location"], "ios.home")

        self.assertEqual(deliver_mock.await_count, 1)
        self.assertEqual(deliver_mock.await_args.kwargs["delivery_type"], "notification")
        self.assertEqual(deliver_mock.await_args.kwargs["location"], "ios.notifications")
        self.assertEqual(
            deliver_mock.await_args.kwargs["push_payload"]["notification_id"],
            notification.id,
        )
        self.assertEqual(
            deliver_mock.await_args.kwargs["push_payload"]["target"]["location"],
            "ios.home",
        )


if __name__ == "__main__":
    unittest.main()
