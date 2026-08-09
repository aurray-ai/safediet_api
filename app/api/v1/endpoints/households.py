from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from app.dependencies import (
    get_current_user,
    get_household_budgeting_service,
    get_household_service,
    get_media_storage_service,
)
from app.models.household import HouseholdExpenseType
from app.models.user import User
from app.schemas.household import (
    AddHouseholdMemberRequest,
    CreateHouseholdExpenseRequest,
    CreateHouseholdRequest,
    HouseholdBalancesResponse,
    HouseholdBudgetSummaryResponse,
    HouseholdContributionCreateResponse,
    HouseholdContributionListResponse,
    HouseholdDetailResponse,
    HouseholdExpenseDetailResponse,
    HouseholdExpenseListResponse,
    HouseholdExpenseMutationResponse,
    HouseholdImportableOrderListResponse,
    HouseholdInvitationDetailResponse,
    HouseholdInvitationResponse,
    HouseholdMemberResponse,
    HouseholdMembershipListResponse,
    HouseholdReceiptUploadResponse,
    HouseholdResponse,
    InviteHouseholdMemberRequest,
    RecordHouseholdContributionRequest,
    UpdateHouseholdMemberRequest,
    UpdateHouseholdRequest,
)
from app.services.household_budgeting_service import HouseholdBudgetingService
from app.services.media_storage_service import MediaStorageService
from app.services.household_service import (
    HouseholdCommunicationError,
    HouseholdConflictError,
    HouseholdNotFoundError,
    HouseholdPermissionError,
    HouseholdService,
    HouseholdValidationError,
)

router = APIRouter(prefix="/households", tags=["households"])


def _raise_household_http_error(exc: Exception) -> None:
    if isinstance(exc, HouseholdNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, HouseholdPermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, HouseholdConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, HouseholdValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if isinstance(exc, HouseholdCommunicationError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("", response_model=HouseholdDetailResponse, status_code=status.HTTP_201_CREATED)
def create_household(
    payload: CreateHouseholdRequest,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdDetailResponse:
    try:
        return household_service.create_household(
            current_user=current_user,
            name=payload.name,
            currency=payload.currency,
            target_amount_minor=payload.budget_profile.target_amount_minor,
            budget_period=payload.budget_profile.period,
            split_rule_type=payload.default_split_rule.type,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get("/mine", response_model=HouseholdMembershipListResponse, status_code=status.HTTP_200_OK)
def list_my_households(
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdMembershipListResponse:
    try:
        return HouseholdMembershipListResponse(
            items=household_service.list_households_for_user(current_user=current_user)
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get("/current", response_model=HouseholdDetailResponse, status_code=status.HTTP_200_OK)
def get_current_household(
    household_id: str | None = Query(default=None),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdDetailResponse:
    try:
        household, members = household_service.get_household_for_user(
            current_user=current_user,
            household_id=household_id,
        )
        summary = household_budgeting_service.get_budget_summary(
            current_user=current_user,
            household_id=household.id,
            period_start=period_start,
            period_end=period_end,
        )
        balances = household_budgeting_service.get_member_balances(
            current_user=current_user,
            household_id=household.id,
            period_start=period_start,
            period_end=period_end,
        )
        return HouseholdDetailResponse(
            household=household_service.to_household_response(
                household,
                member_count=len(members),
            ),
            members=[household_service.to_member_response(member) for member in members],
            invitations=household_service.list_pending_invitations(
                current_user=current_user,
                household_id=household.id,
            ),
            budget_summary=summary,
            balances=balances,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/invitations",
    response_model=HouseholdInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_household_member(
    household_id: str,
    payload: InviteHouseholdMemberRequest,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdInvitationResponse:
    try:
        return household_service.invite_member(
            current_user=current_user,
            household_id=household_id,
            contact=payload.contact,
            display_name=payload.display_name,
            role=payload.role,
            share_weight=payload.share_weight,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get(
    "/invitations/{token}",
    response_model=HouseholdInvitationDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_household_invitation_detail(
    token: str,
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdInvitationDetailResponse:
    try:
        return household_service.get_invitation_detail(token=token)
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/invitations/{token}/accept",
    response_model=HouseholdDetailResponse,
    status_code=status.HTTP_200_OK,
)
def accept_household_invitation(
    token: str,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdDetailResponse:
    try:
        return household_service.accept_invitation(
            current_user=current_user,
            token=token,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/members",
    response_model=HouseholdMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_household_member(
    household_id: str,
    payload: AddHouseholdMemberRequest,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdMemberResponse:
    try:
        return household_service.add_member(
            current_user=current_user,
            household_id=household_id,
            user_id=payload.user_id,
            contact=payload.contact,
            display_name=payload.display_name,
            role=payload.role,
            share_weight=payload.share_weight,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.patch("/{household_id}", response_model=HouseholdResponse, status_code=status.HTTP_200_OK)
def update_household(
    household_id: str,
    payload: UpdateHouseholdRequest,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdResponse:
    try:
        return household_service.update_household(
            current_user=current_user,
            household_id=household_id,
            name=payload.name,
            target_amount_minor=(
                payload.budget_profile.target_amount_minor if payload.budget_profile is not None else None
            ),
            budget_period=(payload.budget_profile.period if payload.budget_profile is not None else None),
            split_rule_type=(
                payload.default_split_rule.type if payload.default_split_rule is not None else None
            ),
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.patch(
    "/{household_id}/members/{member_id}",
    response_model=HouseholdMemberResponse,
    status_code=status.HTTP_200_OK,
)
def update_household_member(
    household_id: str,
    member_id: str,
    payload: UpdateHouseholdMemberRequest,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdMemberResponse:
    try:
        if payload.share_weight is None:
            raise HouseholdValidationError("At least one member field must be provided.")
        return household_service.update_member_weight(
            current_user=current_user,
            household_id=household_id,
            member_id=member_id,
            share_weight=payload.share_weight,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/members/{member_id}/deactivate",
    response_model=HouseholdMemberResponse,
    status_code=status.HTTP_200_OK,
)
def deactivate_household_member(
    household_id: str,
    member_id: str,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdMemberResponse:
    try:
        return household_service.deactivate_member(
            current_user=current_user,
            household_id=household_id,
            member_id=member_id,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/archive",
    response_model=HouseholdResponse,
    status_code=status.HTTP_200_OK,
)
def archive_household(
    household_id: str,
    current_user: User = Depends(get_current_user),
    household_service: HouseholdService = Depends(get_household_service),
) -> HouseholdResponse:
    try:
        return household_service.archive_household(
            current_user=current_user,
            household_id=household_id,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/contributions",
    response_model=HouseholdContributionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_household_contribution(
    household_id: str,
    payload: RecordHouseholdContributionRequest,
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdContributionCreateResponse:
    try:
        return household_budgeting_service.record_contribution(
            current_user=current_user,
            household_id=household_id,
            member_id=payload.member_id,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            period_start=payload.period_start,
            period_end=payload.period_end,
            source=payload.source,
            note=payload.note,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get(
    "/{household_id}/contributions",
    response_model=HouseholdContributionListResponse,
    status_code=status.HTTP_200_OK,
)
def list_household_contributions(
    household_id: str,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdContributionListResponse:
    try:
        return household_budgeting_service.list_contributions(
            current_user=current_user,
            household_id=household_id,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/expenses",
    response_model=HouseholdExpenseMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_household_expense(
    household_id: str,
    payload: CreateHouseholdExpenseRequest,
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdExpenseMutationResponse:
    try:
        return household_budgeting_service.create_expense(
            current_user=current_user,
            household_id=household_id,
            paid_by_member_id=payload.paid_by_member_id,
            expense_type=payload.expense_type,
            title=payload.title,
            description=payload.description,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            effective_date=payload.effective_date,
            linked_order_id=payload.linked_order_id,
            receipt_url=payload.receipt_url,
            receipt_source=payload.receipt_source,
            split_rule_type=(payload.split_rule.type if payload.split_rule is not None else None),
            status=payload.status,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get(
    "/{household_id}/expenses",
    response_model=HouseholdExpenseListResponse,
    status_code=status.HTTP_200_OK,
)
def list_household_expenses(
    household_id: str,
    date_from: date = Query(...),
    date_to: date = Query(...),
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdExpenseListResponse:
    try:
        return household_budgeting_service.list_expenses(
            current_user=current_user,
            household_id=household_id,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get(
    "/{household_id}/expenses/importable-orders",
    response_model=HouseholdImportableOrderListResponse,
    status_code=status.HTTP_200_OK,
)
def list_household_importable_orders(
    household_id: str,
    expense_type: HouseholdExpenseType = Query(...),
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdImportableOrderListResponse:
    try:
        return household_budgeting_service.list_importable_orders(
            current_user=current_user,
            household_id=household_id,
            expense_type=expense_type,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/expenses/receipts",
    response_model=HouseholdReceiptUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_household_expense_receipt(
    household_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
    media_storage_service: MediaStorageService = Depends(get_media_storage_service),
) -> HouseholdReceiptUploadResponse:
    try:
        household_budgeting_service.ensure_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        asset = await media_storage_service.upload_image(
            file=file,
            folder=f"household-receipts/{household_id}",
            public_base_url=str(request.base_url).rstrip("/"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        _raise_household_http_error(exc)
        raise
    return HouseholdReceiptUploadResponse(receipt_url=asset.url)


@router.get(
    "/{household_id}/expenses/{expense_id}",
    response_model=HouseholdExpenseDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_household_expense(
    household_id: str,
    expense_id: str,
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdExpenseDetailResponse:
    try:
        return household_budgeting_service.get_expense_detail(
            current_user=current_user,
            household_id=household_id,
            expense_id=expense_id,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.post(
    "/{household_id}/expenses/{expense_id}/void",
    response_model=HouseholdExpenseMutationResponse,
    status_code=status.HTTP_200_OK,
)
def void_household_expense(
    household_id: str,
    expense_id: str,
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdExpenseMutationResponse:
    try:
        return household_budgeting_service.void_expense(
            current_user=current_user,
            household_id=household_id,
            expense_id=expense_id,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get(
    "/{household_id}/budget-summary",
    response_model=HouseholdBudgetSummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_household_budget_summary(
    household_id: str,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdBudgetSummaryResponse:
    try:
        return household_budgeting_service.get_budget_summary(
            current_user=current_user,
            household_id=household_id,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:
        _raise_household_http_error(exc)


@router.get(
    "/{household_id}/balances",
    response_model=HouseholdBalancesResponse,
    status_code=status.HTTP_200_OK,
)
def get_household_balances(
    household_id: str,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    household_budgeting_service: HouseholdBudgetingService = Depends(get_household_budgeting_service),
) -> HouseholdBalancesResponse:
    try:
        return household_budgeting_service.get_member_balances(
            current_user=current_user,
            household_id=household_id,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:
        _raise_household_http_error(exc)
