from __future__ import annotations

from typing import Any

from app.agents.promotions import PromotionAgentGraph, PromotionGenerationRuntime
from app.core.config import Settings
from app.models.user import User
from app.repositories.promotion_campaign_repository import PromotionCampaignRepository
from app.repositories.promotion_draft_repository import PromotionDraftRepository
from app.repositories.user_repository import UserRepository
from app.schemas.admin_promotion import PromotionContentPayload, PromotionDraftListResponse, PromotionDraftResponse, PromotionGenerateResponse


class PromotionGenerationError(Exception):
    pass


class PromotionDraftNotFoundError(Exception):
    pass


class PromotionGenerationService:
    def __init__(
        self,
        *,
        settings: Settings,
        campaign_repository: PromotionCampaignRepository,
        draft_repository: PromotionDraftRepository,
        user_repository: UserRepository,
    ) -> None:
        self._settings = settings
        self._campaign_repository = campaign_repository
        self._draft_repository = draft_repository
        self._user_repository = user_repository
        self._promotion_agent = PromotionAgentGraph(
            runtime=PromotionGenerationRuntime(
                openai_api_key=(
                    settings.openai_api_key.get_secret_value()
                    if settings.openai_api_key is not None
                    else None
                ),
                model_name=settings.openai_promotion_generation_model,
                timeout_seconds=settings.openai_promotion_generation_timeout_seconds,
            )
        )

    def generate_campaign_drafts(
        self,
        *,
        campaign_id: str,
        current_admin: User,
    ) -> PromotionGenerateResponse:
        campaign = self._require_campaign(campaign_id)
        self._campaign_repository.update_campaign(campaign_id, {"status": "generating"})
        campaign_users = self._campaign_repository.list_campaign_users(campaign_id=campaign_id)
        generated_count = 0
        failed_count = 0

        for campaign_user in campaign_users:
            try:
                self.generate_user_draft(
                    campaign_id=campaign_id,
                    user_id=str(campaign_user["user_id"]),
                    current_admin=current_admin,
                )
                generated_count += 1
            except PromotionGenerationError as exc:
                failed_count += 1
                snapshot = self._campaign_repository.get_latest_context_snapshot(
                    campaign_id=campaign_id,
                    user_id=str(campaign_user["user_id"]),
                )
                self._draft_repository.create_failed_draft(
                    campaign_id=campaign_id,
                    user_id=str(campaign_user["user_id"]),
                    context_snapshot_id=str((snapshot or {}).get("_id") or ""),
                    failure_reason=str(exc),
                )
                self._campaign_repository.update_campaign_user(
                    campaign_id=campaign_id,
                    user_id=str(campaign_user["user_id"]),
                    updates={"generation_status": "failed"},
                )

        self._campaign_repository.update_campaign(
            campaign_id,
            {"status": "ready_for_review" if generated_count else "draft"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="drafts_generated",
            metadata={"generated_count": generated_count, "failed_count": failed_count},
        )
        return PromotionGenerateResponse(
            campaign_id=campaign_id,
            generated_count=generated_count,
            failed_count=failed_count,
        )

    def generate_user_draft(
        self,
        *,
        campaign_id: str,
        user_id: str,
        current_admin: User,
    ) -> PromotionDraftResponse:
        campaign = self._require_campaign(campaign_id)
        campaign_user = self._campaign_repository.get_campaign_user(campaign_id=campaign_id, user_id=user_id)
        if campaign_user is None:
            raise PromotionGenerationError("Campaign user not found.")
        user = self._user_repository.find_by_id(user_id)
        if user is None:
            raise PromotionGenerationError("User not found.")

        snapshot = self._campaign_repository.get_latest_context_snapshot(campaign_id=campaign_id, user_id=user_id)
        if snapshot is None:
            raise PromotionGenerationError("Context snapshot is missing for this user.")

        generation_result = self._promotion_agent.run_generation(
            campaign=campaign,
            current_user=user,
            user_context={
                "profile_snapshot": dict(snapshot.get("profile_snapshot") or {}),
                "preference_snapshot": dict(snapshot.get("preference_snapshot") or {}),
                "eligibility_snapshot": dict(snapshot.get("eligibility_snapshot") or {}),
                "conversation_summary": snapshot.get("conversation_summary"),
                "recent_messages_summary": list(snapshot.get("recent_messages_summary") or []),
                "latest_plan_summary": snapshot.get("latest_plan_summary"),
                "source_refs": dict(snapshot.get("source_refs") or {}),
            },
        )
        generated_payload = generation_result.payload
        warnings = self._validation_warnings(generated_payload)
        draft = self._draft_repository.create_draft(
            campaign_id=campaign_id,
            user_id=user_id,
            context_snapshot_id=str(snapshot["_id"]),
            generated_payload=generated_payload.model_dump(mode="json"),
            validation_warnings=warnings,
        )
        self._campaign_repository.update_campaign_user(
            campaign_id=campaign_id,
            user_id=user_id,
            updates={"generation_status": "generated", "review_status": "pending"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=campaign_id,
            actor_admin_id=current_admin.id,
            action="draft_generated",
            draft_id=str(draft["_id"]),
            user_id=user_id,
            after_payload=generated_payload.model_dump(mode="json"),
        )
        return self._to_draft_response(draft, user_name=user.name)

    def list_drafts(self, *, campaign_id: str) -> PromotionDraftListResponse:
        self._require_campaign(campaign_id)
        drafts, total = self._draft_repository.list_campaign_drafts(campaign_id=campaign_id)
        users = self._user_repository.list_by_ids([str(draft["user_id"]) for draft in drafts])
        users_by_id = {user.id: user for user in users}
        return PromotionDraftListResponse(
            items=[
                self._to_draft_response(draft, user_name=(users_by_id.get(str(draft["user_id"])).name if users_by_id.get(str(draft["user_id"])) else None))
                for draft in drafts
            ],
            total=total,
        )

    def get_draft(self, draft_id: str) -> PromotionDraftResponse:
        draft = self._draft_repository.get_draft(draft_id)
        if draft is None:
            raise PromotionDraftNotFoundError
        user = self._user_repository.find_by_id(str(draft["user_id"]))
        return self._to_draft_response(draft, user_name=user.name if user is not None else None)

    def _require_campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._campaign_repository.get_campaign(campaign_id)
        if campaign is None:
            raise PromotionGenerationError("Campaign not found.")
        return campaign

    @staticmethod
    def _validation_warnings(payload: PromotionContentPayload) -> list[str]:
        warnings: list[str] = []
        if not payload.full_message:
            warnings.append("Full message is empty.")
        if len(payload.highlights) == 0:
            warnings.append("No highlights were generated.")
        return warnings

    @staticmethod
    def _to_draft_response(draft: dict[str, Any], *, user_name: str | None) -> PromotionDraftResponse:
        return PromotionDraftResponse(
            id=str(draft["_id"]),
            campaign_id=str(draft["campaign_id"]),
            user_id=str(draft["user_id"]),
            user_name=user_name,
            status=str(draft.get("status") or "generated"),
            generation_version=int(draft.get("generation_version") or 1),
            edit_version=int(draft.get("edit_version") or 0),
            generated_payload=PromotionContentPayload.model_validate(draft.get("generated_payload") or {}),
            working_payload=PromotionContentPayload.model_validate(draft.get("working_payload") or {}),
            approved_payload=(
                PromotionContentPayload.model_validate(draft["approved_payload"])
                if draft.get("approved_payload")
                else None
            ),
            is_admin_edited=bool(draft.get("is_admin_edited")),
            edited_by_admin_id=draft.get("edited_by_admin_id"),
            edited_at=draft.get("edited_at"),
            approved_by_admin_id=draft.get("approved_by_admin_id"),
            approved_at=draft.get("approved_at"),
            validation_warnings=list(draft.get("validation_warnings") or []),
            failure_reason=draft.get("failure_reason"),
            created_at=draft["created_at"],
            updated_at=draft["updated_at"],
        )
