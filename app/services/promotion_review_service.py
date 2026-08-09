from __future__ import annotations

from datetime import datetime, timezone

from app.models.user import User
from app.repositories.promotion_campaign_repository import PromotionCampaignRepository
from app.repositories.promotion_draft_repository import PromotionDraftRepository
from app.schemas.admin_promotion import PromotionContentPayload, PromotionDraftActionResponse


class PromotionReviewDraftNotFoundError(Exception):
    pass


class PromotionReviewService:
    def __init__(
        self,
        *,
        campaign_repository: PromotionCampaignRepository,
        draft_repository: PromotionDraftRepository,
    ) -> None:
        self._campaign_repository = campaign_repository
        self._draft_repository = draft_repository

    def update_working_payload(
        self,
        *,
        draft_id: str,
        current_admin: User,
        working_payload: PromotionContentPayload,
    ) -> PromotionDraftActionResponse:
        draft = self._require_draft(draft_id)
        updated = self._draft_repository.update_draft(
            draft_id,
            {
                "working_payload": working_payload.model_dump(mode="json"),
                "is_admin_edited": True,
                "edited_by_admin_id": current_admin.id,
                "edited_at": datetime.now(timezone.utc),
                "edit_version": int(draft.get("edit_version") or 0) + 1,
                "status": "edited",
            },
        )
        assert updated is not None
        self._campaign_repository.update_campaign_user(
            campaign_id=str(updated["campaign_id"]),
            user_id=str(updated["user_id"]),
            updates={"review_status": "edited"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=str(updated["campaign_id"]),
            actor_admin_id=current_admin.id,
            action="draft_updated",
            draft_id=draft_id,
            user_id=str(updated["user_id"]),
            before_payload=draft.get("working_payload") or {},
            after_payload=working_payload.model_dump(mode="json"),
        )
        return PromotionDraftActionResponse(draft_id=draft_id, status=str(updated["status"]))

    def reset_working_payload(
        self,
        *,
        draft_id: str,
        current_admin: User,
    ) -> PromotionDraftActionResponse:
        draft = self._require_draft(draft_id)
        updated = self._draft_repository.update_draft(
            draft_id,
            {
                "working_payload": dict(draft.get("generated_payload") or {}),
                "is_admin_edited": False,
                "edited_by_admin_id": current_admin.id,
                "edited_at": datetime.now(timezone.utc),
                "status": "generated",
            },
        )
        assert updated is not None
        self._campaign_repository.update_campaign_user(
            campaign_id=str(updated["campaign_id"]),
            user_id=str(updated["user_id"]),
            updates={"review_status": "pending"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=str(updated["campaign_id"]),
            actor_admin_id=current_admin.id,
            action="draft_reset",
            draft_id=draft_id,
            user_id=str(updated["user_id"]),
        )
        return PromotionDraftActionResponse(draft_id=draft_id, status=str(updated["status"]))

    def approve_draft(
        self,
        *,
        draft_id: str,
        current_admin: User,
    ) -> PromotionDraftActionResponse:
        draft = self._require_draft(draft_id)
        updated = self._draft_repository.update_draft(
            draft_id,
            {
                "approved_payload": dict(draft.get("working_payload") or {}),
                "approved_by_admin_id": current_admin.id,
                "approved_at": datetime.now(timezone.utc),
                "status": "approved",
            },
        )
        assert updated is not None
        self._campaign_repository.update_campaign_user(
            campaign_id=str(updated["campaign_id"]),
            user_id=str(updated["user_id"]),
            updates={"review_status": "approved"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=str(updated["campaign_id"]),
            actor_admin_id=current_admin.id,
            action="draft_approved",
            draft_id=draft_id,
            user_id=str(updated["user_id"]),
            after_payload=dict(updated.get("approved_payload") or {}),
        )
        return PromotionDraftActionResponse(draft_id=draft_id, status=str(updated["status"]))

    def reject_draft(
        self,
        *,
        draft_id: str,
        current_admin: User,
    ) -> PromotionDraftActionResponse:
        draft = self._require_draft(draft_id)
        updated = self._draft_repository.update_draft(draft_id, {"status": "rejected"})
        assert updated is not None
        self._campaign_repository.update_campaign_user(
            campaign_id=str(updated["campaign_id"]),
            user_id=str(updated["user_id"]),
            updates={"review_status": "rejected"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=str(updated["campaign_id"]),
            actor_admin_id=current_admin.id,
            action="draft_rejected",
            draft_id=draft_id,
            user_id=str(updated["user_id"]),
            before_payload=dict(draft.get("working_payload") or {}),
        )
        return PromotionDraftActionResponse(draft_id=draft_id, status=str(updated["status"]))

    def skip_draft(
        self,
        *,
        draft_id: str,
        current_admin: User,
    ) -> PromotionDraftActionResponse:
        draft = self._require_draft(draft_id)
        updated = self._draft_repository.update_draft(draft_id, {"status": "skipped"})
        assert updated is not None
        self._campaign_repository.update_campaign_user(
            campaign_id=str(updated["campaign_id"]),
            user_id=str(updated["user_id"]),
            updates={"review_status": "skipped", "delivery_status": "skipped"},
        )
        self._campaign_repository.append_audit_log(
            campaign_id=str(updated["campaign_id"]),
            actor_admin_id=current_admin.id,
            action="draft_skipped",
            draft_id=draft_id,
            user_id=str(updated["user_id"]),
        )
        return PromotionDraftActionResponse(draft_id=draft_id, status=str(updated["status"]))

    def bulk_approve(
        self,
        *,
        draft_ids: list[str],
        current_admin: User,
    ) -> list[PromotionDraftActionResponse]:
        return [self.approve_draft(draft_id=draft_id, current_admin=current_admin) for draft_id in draft_ids]

    def _require_draft(self, draft_id: str) -> dict:
        draft = self._draft_repository.get_draft(draft_id)
        if draft is None:
            raise PromotionReviewDraftNotFoundError
        return draft
