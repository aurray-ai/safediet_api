from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    get_admin_promotion_service,
    get_promotion_delivery_service,
    get_promotion_generation_service,
    get_promotion_review_service,
    require_platform_user,
)
from app.models.user import User
from app.schemas.admin_promotion import (
    PromotionAuditLogListResponse,
    PromotionBulkApproveRequest,
    PromotionCampaignCreateRequest,
    PromotionCampaignListResponse,
    PromotionCampaignResponse,
    PromotionCampaignUpdateRequest,
    PromotionCampaignUsersAddRequest,
    PromotionCampaignUsersListResponse,
    PromotionContextRefreshResponse,
    PromotionContextSnapshotResponse,
    PromotionDeliverResponse,
    PromotionDeliveryListResponse,
    PromotionDraftActionResponse,
    PromotionDraftListResponse,
    PromotionDraftResponse,
    PromotionDraftUpdateRequest,
    PromotionGenerateResponse,
    PromotionUserProfileResponse,
    PromotionSelectableUsersListResponse,
)
from app.services.admin_promotion_service import (
    AdminPromotionService,
    PromotionCampaignNotFoundError,
    PromotionCampaignUserNotFoundError,
    PromotionUserNotFoundError,
)
from app.services.promotion_delivery_service import PromotionDeliveryError, PromotionDeliveryService
from app.services.promotion_generation_service import (
    PromotionDraftNotFoundError,
    PromotionGenerationError,
    PromotionGenerationService,
)
from app.services.promotion_review_service import PromotionReviewDraftNotFoundError, PromotionReviewService

router = APIRouter(prefix="/admin/promotions", tags=["admin-promotions"])


@router.get("/users", response_model=PromotionSelectableUsersListResponse, status_code=status.HTTP_200_OK)
def list_promotion_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    _: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionSelectableUsersListResponse:
    return admin_promotion_service.list_selectable_users(page=page, page_size=page_size, search=search)


@router.get("/users/{user_id}", response_model=PromotionUserProfileResponse, status_code=status.HTTP_200_OK)
def get_promotion_user_profile(
    user_id: str,
    campaign_id: str | None = Query(default=None),
    _: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionUserProfileResponse:
    try:
        return admin_promotion_service.get_user_profile(user_id=user_id, campaign_id=campaign_id)
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc
    except PromotionUserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.") from exc


@router.post("/campaigns", response_model=PromotionCampaignResponse, status_code=status.HTTP_201_CREATED)
def create_promotion_campaign(
    payload: PromotionCampaignCreateRequest,
    current_admin: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionCampaignResponse:
    return admin_promotion_service.create_campaign(current_admin=current_admin, payload=payload)


@router.get("/campaigns", response_model=PromotionCampaignListResponse, status_code=status.HTTP_200_OK)
def list_promotion_campaigns(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionCampaignListResponse:
    return admin_promotion_service.list_campaigns(page=page, page_size=page_size)


@router.get("/campaigns/{campaign_id}", response_model=PromotionCampaignResponse, status_code=status.HTTP_200_OK)
def get_promotion_campaign(
    campaign_id: str,
    _: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionCampaignResponse:
    try:
        return admin_promotion_service.get_campaign(campaign_id)
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc


@router.patch("/campaigns/{campaign_id}", response_model=PromotionCampaignResponse, status_code=status.HTTP_200_OK)
def update_promotion_campaign(
    campaign_id: str,
    payload: PromotionCampaignUpdateRequest,
    current_admin: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionCampaignResponse:
    try:
        return admin_promotion_service.update_campaign(
            campaign_id=campaign_id,
            current_admin=current_admin,
            payload=payload,
        )
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc


@router.post("/campaigns/{campaign_id}/users", response_model=PromotionCampaignUsersListResponse, status_code=status.HTTP_200_OK)
def add_promotion_campaign_users(
    campaign_id: str,
    payload: PromotionCampaignUsersAddRequest,
    current_admin: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionCampaignUsersListResponse:
    try:
        return admin_promotion_service.add_users(
            campaign_id=campaign_id,
            current_admin=current_admin,
            user_ids=payload.user_ids,
        )
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc


@router.get("/campaigns/{campaign_id}/users", response_model=PromotionCampaignUsersListResponse, status_code=status.HTTP_200_OK)
def list_promotion_campaign_users(
    campaign_id: str,
    _: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionCampaignUsersListResponse:
    try:
        return admin_promotion_service.list_campaign_users(campaign_id=campaign_id)
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc


@router.delete("/campaigns/{campaign_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_promotion_campaign_user(
    campaign_id: str,
    user_id: str,
    current_admin: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> None:
    try:
        admin_promotion_service.remove_user(campaign_id=campaign_id, user_id=user_id, current_admin=current_admin)
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc
    except PromotionCampaignUserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign user not found.") from exc


@router.post("/campaigns/{campaign_id}/context/refresh", response_model=PromotionContextRefreshResponse, status_code=status.HTTP_200_OK)
def refresh_promotion_contexts(
    campaign_id: str,
    current_admin: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionContextRefreshResponse:
    try:
        return admin_promotion_service.refresh_contexts(campaign_id=campaign_id, current_admin=current_admin)
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc


@router.get("/campaigns/{campaign_id}/users/{user_id}/context", response_model=PromotionContextSnapshotResponse, status_code=status.HTTP_200_OK)
def get_promotion_user_context(
    campaign_id: str,
    user_id: str,
    _: User = Depends(require_platform_user),
    admin_promotion_service: AdminPromotionService = Depends(get_admin_promotion_service),
) -> PromotionContextSnapshotResponse:
    try:
        return admin_promotion_service.get_user_context(campaign_id=campaign_id, user_id=user_id)
    except PromotionCampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion campaign not found.") from exc
    except PromotionCampaignUserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign user not found.") from exc


@router.post("/campaigns/{campaign_id}/generate", response_model=PromotionGenerateResponse, status_code=status.HTTP_200_OK)
def generate_promotion_campaign_drafts(
    campaign_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_generation_service: PromotionGenerationService = Depends(get_promotion_generation_service),
) -> PromotionGenerateResponse:
    try:
        return promotion_generation_service.generate_campaign_drafts(
            campaign_id=campaign_id,
            current_admin=current_admin,
        )
    except PromotionGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/users/{user_id}/generate", response_model=PromotionDraftResponse, status_code=status.HTTP_200_OK)
def generate_single_promotion_draft(
    campaign_id: str,
    user_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_generation_service: PromotionGenerationService = Depends(get_promotion_generation_service),
) -> PromotionDraftResponse:
    try:
        return promotion_generation_service.generate_user_draft(
            campaign_id=campaign_id,
            user_id=user_id,
            current_admin=current_admin,
        )
    except PromotionGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/drafts", response_model=PromotionDraftListResponse, status_code=status.HTTP_200_OK)
def list_promotion_drafts(
    campaign_id: str,
    _: User = Depends(require_platform_user),
    promotion_generation_service: PromotionGenerationService = Depends(get_promotion_generation_service),
) -> PromotionDraftListResponse:
    try:
        return promotion_generation_service.list_drafts(campaign_id=campaign_id)
    except PromotionGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/drafts/{draft_id}", response_model=PromotionDraftResponse, status_code=status.HTTP_200_OK)
def get_promotion_draft(
    draft_id: str,
    _: User = Depends(require_platform_user),
    promotion_generation_service: PromotionGenerationService = Depends(get_promotion_generation_service),
) -> PromotionDraftResponse:
    try:
        return promotion_generation_service.get_draft(draft_id)
    except PromotionDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion draft not found.") from exc


@router.patch("/drafts/{draft_id}", response_model=PromotionDraftActionResponse, status_code=status.HTTP_200_OK)
def update_promotion_draft(
    draft_id: str,
    payload: PromotionDraftUpdateRequest,
    current_admin: User = Depends(require_platform_user),
    promotion_review_service: PromotionReviewService = Depends(get_promotion_review_service),
) -> PromotionDraftActionResponse:
    try:
        return promotion_review_service.update_working_payload(
            draft_id=draft_id,
            current_admin=current_admin,
            working_payload=payload.working_payload,
        )
    except PromotionReviewDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion draft not found.") from exc


@router.post("/drafts/{draft_id}/reset", response_model=PromotionDraftActionResponse, status_code=status.HTTP_200_OK)
def reset_promotion_draft(
    draft_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_review_service: PromotionReviewService = Depends(get_promotion_review_service),
) -> PromotionDraftActionResponse:
    try:
        return promotion_review_service.reset_working_payload(draft_id=draft_id, current_admin=current_admin)
    except PromotionReviewDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion draft not found.") from exc


@router.post("/drafts/{draft_id}/approve", response_model=PromotionDraftActionResponse, status_code=status.HTTP_200_OK)
def approve_promotion_draft(
    draft_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_review_service: PromotionReviewService = Depends(get_promotion_review_service),
) -> PromotionDraftActionResponse:
    try:
        return promotion_review_service.approve_draft(draft_id=draft_id, current_admin=current_admin)
    except PromotionReviewDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion draft not found.") from exc


@router.post("/drafts/{draft_id}/reject", response_model=PromotionDraftActionResponse, status_code=status.HTTP_200_OK)
def reject_promotion_draft(
    draft_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_review_service: PromotionReviewService = Depends(get_promotion_review_service),
) -> PromotionDraftActionResponse:
    try:
        return promotion_review_service.reject_draft(draft_id=draft_id, current_admin=current_admin)
    except PromotionReviewDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion draft not found.") from exc


@router.post("/drafts/{draft_id}/skip", response_model=PromotionDraftActionResponse, status_code=status.HTTP_200_OK)
def skip_promotion_draft(
    draft_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_review_service: PromotionReviewService = Depends(get_promotion_review_service),
) -> PromotionDraftActionResponse:
    try:
        return promotion_review_service.skip_draft(draft_id=draft_id, current_admin=current_admin)
    except PromotionReviewDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion draft not found.") from exc


@router.post("/drafts/bulk-approve", response_model=list[PromotionDraftActionResponse], status_code=status.HTTP_200_OK)
def bulk_approve_promotion_drafts(
    payload: PromotionBulkApproveRequest,
    current_admin: User = Depends(require_platform_user),
    promotion_review_service: PromotionReviewService = Depends(get_promotion_review_service),
) -> list[PromotionDraftActionResponse]:
    return promotion_review_service.bulk_approve(draft_ids=payload.draft_ids, current_admin=current_admin)


@router.post("/campaigns/{campaign_id}/deliver", response_model=PromotionDeliverResponse, status_code=status.HTTP_200_OK)
async def deliver_promotion_campaign(
    campaign_id: str,
    current_admin: User = Depends(require_platform_user),
    promotion_delivery_service: PromotionDeliveryService = Depends(get_promotion_delivery_service),
) -> PromotionDeliverResponse:
    try:
        return await promotion_delivery_service.deliver_campaign(
            campaign_id=campaign_id,
            current_admin=current_admin,
        )
    except PromotionDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/deliveries", response_model=PromotionDeliveryListResponse, status_code=status.HTTP_200_OK)
def list_promotion_deliveries(
    campaign_id: str,
    _: User = Depends(require_platform_user),
    promotion_delivery_service: PromotionDeliveryService = Depends(get_promotion_delivery_service),
) -> PromotionDeliveryListResponse:
    try:
        return promotion_delivery_service.list_deliveries(campaign_id=campaign_id)
    except PromotionDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/audit", response_model=PromotionAuditLogListResponse, status_code=status.HTTP_200_OK)
def list_promotion_audit_logs(
    campaign_id: str,
    _: User = Depends(require_platform_user),
    promotion_delivery_service: PromotionDeliveryService = Depends(get_promotion_delivery_service),
) -> PromotionAuditLogListResponse:
    try:
        return promotion_delivery_service.list_audit_logs(campaign_id=campaign_id)
    except PromotionDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
