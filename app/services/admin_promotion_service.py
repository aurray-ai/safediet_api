from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.user import User, UserType
from app.repositories.meal_conversation_repository import MealConversationRepository
from app.repositories.promotion_campaign_repository import PromotionCampaignRepository
from app.repositories.user_repository import UserRepository
from app.schemas.admin_promotion import (
    PromotionCampaignCreateRequest,
    PromotionCampaignListResponse,
    PromotionCampaignResponse,
    PromotionCampaignUpdateRequest,
    PromotionUserCampaignMembershipResponse,
    PromotionCampaignUserSummaryResponse,
    PromotionCampaignUsersListResponse,
    PromotionContextRefreshResponse,
    PromotionContextSnapshotResponse,
    PromotionSelectableUserResponse,
    PromotionSelectableUsersListResponse,
    PromotionUserConversationSummaryResponse,
    PromotionUserMessageSummaryResponse,
    PromotionUserProfileResponse,
)
from app.services.promotion_context_service import PromotionContextService


class PromotionCampaignNotFoundError(Exception):
    pass


class PromotionCampaignUserNotFoundError(Exception):
    pass


class PromotionUserNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PromotionContextRefreshResult:
    campaign_id: str
    refreshed_count: int


class AdminPromotionService:
    def __init__(
        self,
        *,
        campaign_repository: PromotionCampaignRepository,
        user_repository: UserRepository,
        meal_conversation_repository: MealConversationRepository,
        promotion_context_service: PromotionContextService,
    ) -> None:
        self._campaign_repository = campaign_repository
        self._user_repository = user_repository
        self._meal_conversation_repository = meal_conversation_repository
        self._promotion_context_service = promotion_context_service

    def list_selectable_users(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
    ) -> PromotionSelectableUsersListResponse:
        users, total = self._user_repository.list_users(
            page=page,
            page_size=page_size,
            search=search,
            user_type=UserType.CUSTOMER,
        )
        return PromotionSelectableUsersListResponse(
            items=[
                PromotionSelectableUserResponse(
                    id=user.id,
                    name=user.name,
                    email=user.email,
                    user_types=[user_type.value for user_type in user.user_types],
                    created_at=user.created_at,
                )
                for user in users
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def create_campaign(
        self,
        *,
        current_admin: User,
        payload: PromotionCampaignCreateRequest,
    ) -> PromotionCampaignResponse:
        document = self._campaign_repository.create_campaign(
            created_by_admin_id=current_admin.id,
            name=payload.name,
            status="draft",
            promotion_type=payload.promotion_type,
            delivery_type=payload.delivery_type,
            target_location=payload.target_location,
            admin_instruction=payload.admin_instruction,
            tone=payload.tone,
            constraints=payload.constraints,
        )
        self._campaign_repository.append_audit_log(
            campaign_id=str(document["_id"]),
            actor_admin_id=current_admin.id,
            action="campaign_created",
            after_payload=self._campaign_public_payload(document),
        )
        return self._to_campaign_response(document)

    def list_campaigns(self, *, page: int, page_size: int) -> PromotionCampaignListResponse:
        items, total = self._campaign_repository.list_campaigns(page=page, page_size=page_size)
        return PromotionCampaignListResponse(
            items=[self._to_campaign_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_campaign(self, campaign_id: str) -> PromotionCampaignResponse:
        campaign = self._require_campaign(campaign_id)
        return self._to_campaign_response(campaign)

    def update_campaign(
        self,
        *,
        campaign_id: str,
        current_admin: User,
        payload: PromotionCampaignUpdateRequest,
    ) -> PromotionCampaignResponse:
        campaign = self._require_campaign(campaign_id)
        updates = payload.model_dump(exclude_none=True)
        updated = self._campaign_repository.update_campaign(campaign_id, updates)
        assert updated is not None
        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="campaign_updated",
            before_payload=self._campaign_public_payload(campaign),
            after_payload=self._campaign_public_payload(updated),
        )
        return self._to_campaign_response(updated)

    def add_users(
        self,
        *,
        campaign_id: str,
        current_admin: User,
        user_ids: list[str],
    ) -> PromotionCampaignUsersListResponse:
        self._require_campaign(campaign_id)
        existing_user_ids = {
            str(item["user_id"])
            for item in self._campaign_repository.list_campaign_users(campaign_id=campaign_id)
        }
        users_by_id = {
            user.id: user
            for user in self._user_repository.list_by_ids(user_ids)
        }
        valid_user_ids = [user_id for user_id in user_ids if user_id in users_by_id]
        inserted = self._campaign_repository.add_campaign_users(campaign_id=campaign_id, user_ids=valid_user_ids)
        newly_added_user_ids = [user_id for user_id in valid_user_ids if user_id not in existing_user_ids]
        context_ready_count = 0

        for user_id in newly_added_user_ids:
            user = users_by_id.get(user_id)
            if user is None:
                continue
            snapshot = self._promotion_context_service.build_snapshot(user=user)
            self._campaign_repository.replace_context_snapshot(
                campaign_id=campaign_id,
                user_id=user_id,
                snapshot=snapshot,
            )
            context_ready_count += 1

        if inserted:
            self._campaign_repository.update_campaign(campaign_id, {"status": "draft"})

        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="campaign_users_added",
            metadata={
                "requested_user_ids": user_ids,
                "valid_user_ids": valid_user_ids,
                "inserted_count": inserted,
                "context_ready_count": context_ready_count,
            },
        )
        return self.list_campaign_users(campaign_id=campaign_id)

    def remove_user(
        self,
        *,
        campaign_id: str,
        user_id: str,
        current_admin: User,
    ) -> None:
        self._require_campaign(campaign_id)
        removed = self._campaign_repository.remove_campaign_user(campaign_id=campaign_id, user_id=user_id)
        if not removed:
            raise PromotionCampaignUserNotFoundError
        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="campaign_user_removed",
            user_id=user_id,
        )

    def list_campaign_users(self, *, campaign_id: str) -> PromotionCampaignUsersListResponse:
        self._require_campaign(campaign_id)
        items = self._campaign_repository.list_campaign_users(campaign_id=campaign_id)
        users_by_id = {
            user.id: user
            for user in self._user_repository.list_by_ids([str(item["user_id"]) for item in items])
        }
        summaries = [
            self._to_campaign_user_summary(item, users_by_id.get(str(item["user_id"])))
            for item in items
        ]
        return PromotionCampaignUsersListResponse(items=summaries, total=len(summaries))

    def get_user_profile(
        self,
        *,
        user_id: str,
        campaign_id: str | None = None,
    ) -> PromotionUserProfileResponse:
        user = self._user_repository.find_by_id(user_id)
        if user is None:
            raise PromotionUserNotFoundError

        snapshot = self._promotion_context_service.build_snapshot(user=user)
        recent_conversations = self._meal_conversation_repository.list_recent_conversations(user_id=user.id, limit=5)
        recent_messages = list(snapshot.get("recent_messages_summary") or [])

        campaign_membership: PromotionUserCampaignMembershipResponse | None = None
        if campaign_id:
            self._require_campaign(campaign_id)
            campaign_user = self._campaign_repository.get_campaign_user(campaign_id=campaign_id, user_id=user_id)
            if campaign_user is not None:
                context_snapshot = self._campaign_repository.get_latest_context_snapshot(
                    campaign_id=campaign_id,
                    user_id=user_id,
                )
                campaign_membership = PromotionUserCampaignMembershipResponse(
                    campaign_id=campaign_id,
                    context_status=str(campaign_user.get("context_status") or "pending"),
                    generation_status=str(campaign_user.get("generation_status") or "pending"),
                    review_status=str(campaign_user.get("review_status") or "pending"),
                    delivery_status=str(campaign_user.get("delivery_status") or "pending"),
                    context_snapshot=(
                        self._to_context_snapshot_response(context_snapshot)
                        if context_snapshot is not None
                        else None
                    ),
                )

        return PromotionUserProfileResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            user_types=[user_type.value for user_type in user.user_types],
            created_at=user.created_at,
            user_configuration=dict(user.user_configuration or {}),
            profile_snapshot=dict(snapshot.get("profile_snapshot") or {}),
            preference_snapshot=dict(snapshot.get("preference_snapshot") or {}),
            eligibility_snapshot=dict(snapshot.get("eligibility_snapshot") or {}),
            source_refs=dict(snapshot.get("source_refs") or {}),
            recent_conversations=[
                self._to_user_conversation_summary(item)
                for item in recent_conversations
            ],
            recent_messages=[
                PromotionUserMessageSummaryResponse(
                    id=str(message.get("id") or ""),
                    role=str(message.get("role") or ""),
                    text=str(message.get("text") or ""),
                    created_at=message.get("created_at"),
                )
                for message in recent_messages
            ],
            campaign_membership=campaign_membership,
        )

    def refresh_contexts(
        self,
        *,
        campaign_id: str,
        current_admin: User,
    ) -> PromotionContextRefreshResponse:
        self._require_campaign(campaign_id)
        campaign_users = self._campaign_repository.list_campaign_users(campaign_id=campaign_id)
        users_by_id = {
            user.id: user
            for user in self._user_repository.list_by_ids([str(item["user_id"]) for item in campaign_users])
        }
        refreshed_count = 0
        for campaign_user in campaign_users:
            user = users_by_id.get(str(campaign_user["user_id"]))
            if user is None:
                continue
            snapshot = self._promotion_context_service.build_snapshot(user=user)
            self._campaign_repository.replace_context_snapshot(
                campaign_id=campaign_id,
                user_id=user.id,
                snapshot=snapshot,
            )
            refreshed_count += 1

        self._campaign_repository.update_campaign(campaign_id, {"status": "draft"})
        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="context_refreshed",
            metadata={"refreshed_count": refreshed_count},
        )
        return PromotionContextRefreshResponse(campaign_id=campaign_id, refreshed_count=refreshed_count)

    def get_user_context(
        self,
        *,
        campaign_id: str,
        user_id: str,
    ) -> PromotionContextSnapshotResponse:
        self._require_campaign(campaign_id)
        snapshot = self._campaign_repository.get_latest_context_snapshot(campaign_id=campaign_id, user_id=user_id)
        if snapshot is None:
            campaign_user = self._campaign_repository.get_campaign_user(campaign_id=campaign_id, user_id=user_id)
            if campaign_user is None:
                raise PromotionCampaignUserNotFoundError
            user = self._user_repository.find_by_id(user_id)
            if user is None:
                raise PromotionCampaignUserNotFoundError
            snapshot = self._campaign_repository.replace_context_snapshot(
                campaign_id=campaign_id,
                user_id=user_id,
                snapshot=self._promotion_context_service.build_snapshot(user=user),
            )
        return self._to_context_snapshot_response(snapshot)

    def _require_campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._campaign_repository.get_campaign(campaign_id)
        if campaign is None:
            raise PromotionCampaignNotFoundError
        return campaign

    def _to_campaign_user_summary(
        self,
        campaign_user: dict[str, Any],
        user: User | None,
    ) -> PromotionCampaignUserSummaryResponse:
        snapshot = self._campaign_repository.get_latest_context_snapshot(
            campaign_id=str(campaign_user["campaign_id"]),
            user_id=str(campaign_user["user_id"]),
        )
        recent_conversation = None
        if user is not None:
            recent_conversations = self._meal_conversation_repository.list_recent_conversations(user_id=user.id, limit=1)
            recent_conversation = recent_conversations[0] if recent_conversations else None
        latest_summary = dict((recent_conversation or {}).get("current_summary") or {})

        return PromotionCampaignUserSummaryResponse(
            user_id=str(campaign_user["user_id"]),
            user_name=user.name if user is not None else "Unknown user",
            email=user.email if user is not None else "",
            context_status=str(campaign_user.get("context_status") or "pending"),
            generation_status=str(campaign_user.get("generation_status") or "pending"),
            review_status=str(campaign_user.get("review_status") or "pending"),
            delivery_status=str(campaign_user.get("delivery_status") or "pending"),
            last_activity_at=(recent_conversation or {}).get("last_message_at"),
            latest_conversation_summary=(snapshot or {}).get("conversation_summary") or latest_summary.get("last_assistant_preview"),
            latest_plan_summary=(snapshot or {}).get("latest_plan_summary"),
            agent_type=str((recent_conversation or {}).get("agent_type") or "") or None,
            requested_culture=latest_summary.get("requested_culture"),
            has_more_context=snapshot is not None,
        )

    @staticmethod
    def _campaign_public_payload(campaign: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(campaign["_id"]),
            "name": campaign.get("name"),
            "status": campaign.get("status"),
            "promotion_type": campaign.get("promotion_type"),
            "delivery_type": campaign.get("delivery_type"),
            "target_location": campaign.get("target_location"),
            "tone": campaign.get("tone"),
            "selected_user_count": campaign.get("selected_user_count"),
        }

    @staticmethod
    def _to_campaign_response(campaign: dict[str, Any]) -> PromotionCampaignResponse:
        return PromotionCampaignResponse(
            id=str(campaign["_id"]),
            name=str(campaign.get("name") or ""),
            created_by_admin_id=str(campaign.get("created_by_admin_id") or ""),
            status=str(campaign.get("status") or "draft"),
            promotion_type=str(campaign.get("promotion_type") or ""),
            delivery_type=str(campaign.get("delivery_type") or ""),
            target_location=str(campaign.get("target_location") or ""),
            admin_instruction=str(campaign.get("admin_instruction") or ""),
            tone=str(campaign.get("tone") or ""),
            constraints=dict(campaign.get("constraints") or {}),
            selected_user_count=int(campaign.get("selected_user_count") or 0),
            created_at=campaign["created_at"],
            updated_at=campaign["updated_at"],
        )

    @staticmethod
    def _to_context_snapshot_response(snapshot: dict[str, Any]) -> PromotionContextSnapshotResponse:
        return PromotionContextSnapshotResponse(
            id=str(snapshot["_id"]),
            campaign_id=str(snapshot["campaign_id"]),
            user_id=str(snapshot["user_id"]),
            conversation_summary=snapshot.get("conversation_summary"),
            recent_messages_summary=list(snapshot.get("recent_messages_summary") or []),
            latest_plan_summary=snapshot.get("latest_plan_summary"),
            profile_snapshot=dict(snapshot.get("profile_snapshot") or {}),
            preference_snapshot=dict(snapshot.get("preference_snapshot") or {}),
            eligibility_snapshot=dict(snapshot.get("eligibility_snapshot") or {}),
            source_refs=dict(snapshot.get("source_refs") or {}),
            created_at=snapshot["created_at"],
        )

    def _to_user_conversation_summary(self, conversation: dict[str, Any]) -> PromotionUserConversationSummaryResponse:
        summary = dict(conversation.get("current_summary") or {})
        latest_ui_blocks = list(summary.get("latest_ui_blocks") or [])
        latest_plan_summary: str | None = None
        for block in latest_ui_blocks:
            if str(block.get("block_type") or "") != "day_plan":
                continue
            payload = dict(block.get("payload") or {})
            tracked_text = str(payload.get("tracked_text") or "").strip()
            if tracked_text:
                latest_plan_summary = tracked_text
                break

        conversation_id = str(conversation["_id"])
        recent_messages = self._meal_conversation_repository.list_recent_messages(conversation_id, limit=8)
        last_user_message_preview: str | None = None
        last_assistant_preview = summary.get("last_assistant_preview")
        for message in recent_messages:
            role = str(message.get("role") or "").strip().lower()
            text = str(message.get("text") or "").strip()
            if role == "user" and text and not last_user_message_preview:
                last_user_message_preview = text[:220]
            if role == "assistant" and text and not last_assistant_preview:
                last_assistant_preview = text[:220]
            if last_user_message_preview and last_assistant_preview:
                break

        if not last_user_message_preview:
            fallback_user_intent = str(summary.get("last_user_intent") or "").strip()
            last_user_message_preview = fallback_user_intent or None

        return PromotionUserConversationSummaryResponse(
            conversation_id=conversation_id,
            agent_type=str(conversation.get("agent_type") or ""),
            status=str(conversation.get("status") or ""),
            meal_type=summary.get("meal_type"),
            requested_culture=summary.get("requested_culture"),
            last_user_message_preview=last_user_message_preview,
            last_assistant_preview=last_assistant_preview,
            latest_plan_summary=latest_plan_summary,
            message_count=int(conversation.get("message_count") or summary.get("message_count") or 0),
            last_message_at=conversation.get("last_message_at") or summary.get("last_message_at"),
            updated_at=conversation.get("updated_at"),
            created_at=conversation["created_at"],
        )
