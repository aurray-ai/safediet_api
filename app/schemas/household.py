from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.household import (
    HouseholdBudgetPeriod,
    HouseholdContributionSource,
    HouseholdExpenseReceiptSource,
    HouseholdExpenseStatus,
    HouseholdExpenseType,
    HouseholdMemberRole,
    HouseholdMemberStatus,
    HouseholdSplitRuleType,
    HouseholdStatus,
)
from app.models.invitation import InvitationStatus


class HouseholdBudgetProfilePayload(BaseModel):
    period: HouseholdBudgetPeriod = HouseholdBudgetPeriod.WEEKLY
    target_amount_minor: int = Field(ge=0, le=5_000_000)


class HouseholdSplitRulePayload(BaseModel):
    type: HouseholdSplitRuleType = HouseholdSplitRuleType.EQUAL
    weights: list[dict[str, Any]] = Field(default_factory=list)


class CreateHouseholdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    budget_profile: HouseholdBudgetProfilePayload
    default_split_rule: HouseholdSplitRulePayload = Field(default_factory=HouseholdSplitRulePayload)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class UpdateHouseholdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    budget_profile: HouseholdBudgetProfilePayload | None = None
    default_split_rule: HouseholdSplitRulePayload | None = None


class AddHouseholdMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, min_length=3, max_length=160)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: HouseholdMemberRole = HouseholdMemberRole.ADULT
    share_weight: int = Field(default=1, ge=1, le=1000)

    @field_validator("contact", mode="before")
    @classmethod
    def normalize_contact(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class InviteHouseholdMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact: str = Field(min_length=3, max_length=160)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: HouseholdMemberRole = HouseholdMemberRole.ADULT
    share_weight: int = Field(default=1, ge=1, le=1000)

    @field_validator("contact", mode="before")
    @classmethod
    def normalize_invitation_contact(cls, value: str) -> str:
        return str(value).strip().lower()


class UpdateHouseholdMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_weight: int | None = Field(default=None, ge=1, le=1000)


class RecordHouseholdContributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: str = Field(min_length=1, max_length=120)
    amount_minor: int = Field(ge=1, le=5_000_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    period_start: date | None = None
    period_end: date | None = None
    source: HouseholdContributionSource = HouseholdContributionSource.MANUAL
    note: str | None = Field(default=None, max_length=240)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class CreateHouseholdExpenseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paid_by_member_id: str = Field(min_length=1, max_length=120)
    expense_type: HouseholdExpenseType = HouseholdExpenseType.GROCERY
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=400)
    amount_minor: int = Field(ge=1, le=5_000_000)
    currency: str = Field(min_length=3, max_length=3, default="GBP")
    effective_date: date
    linked_order_id: str | None = Field(default=None, max_length=120)
    receipt_url: str | None = Field(default=None, max_length=2000)
    receipt_source: HouseholdExpenseReceiptSource | None = None
    split_rule: HouseholdSplitRulePayload | None = None
    status: HouseholdExpenseStatus = HouseholdExpenseStatus.POSTED

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return str(value).strip().upper()


class HouseholdBudgetProfileResponse(BaseModel):
    period: HouseholdBudgetPeriod
    target_amount_minor: int


class HouseholdSplitRuleResponse(BaseModel):
    type: HouseholdSplitRuleType
    weights: list[dict[str, Any]] = Field(default_factory=list)


class HouseholdResponse(BaseModel):
    id: str
    name: str
    currency: str
    status: HouseholdStatus
    budget_profile: HouseholdBudgetProfileResponse
    default_split_rule: HouseholdSplitRuleResponse
    member_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class HouseholdMemberResponse(BaseModel):
    id: str
    user_id: str
    display_name: str
    role: HouseholdMemberRole
    status: HouseholdMemberStatus
    share_weight: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class HouseholdInvitationResponse(BaseModel):
    id: str
    household_id: str
    invited_by_user_id: str
    invitee_email: str
    invitee_user_id: str | None = None
    display_name: str
    role: HouseholdMemberRole
    status: InvitationStatus
    share_weight: int = Field(ge=1)
    expires_at: datetime
    accepted_at: datetime | None = None
    accepted_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class HouseholdInvitationDetailResponse(BaseModel):
    invitation: HouseholdInvitationResponse
    household_name: str
    inviter_name: str
    requires_registration: bool
    is_existing_user: bool


class HouseholdContributionResponse(BaseModel):
    id: str
    household_id: str
    member_id: str
    user_id: str
    amount_minor: int = Field(ge=0)
    currency: str
    period_start: date
    period_end: date
    source: HouseholdContributionSource
    note: str | None = None
    created_by_user_id: str
    created_at: datetime


class HouseholdContributionListResponse(BaseModel):
    items: list[HouseholdContributionResponse] = Field(default_factory=list)


class HouseholdMemberContributionSummaryResponse(BaseModel):
    member_id: str
    display_name: str
    amount_minor: int = Field(ge=0)


class HouseholdBudgetSummaryResponse(BaseModel):
    period_start: date
    period_end: date
    currency: str
    target_amount_minor: int = Field(ge=0)
    contributed_amount_minor: int = Field(ge=0)
    spent_amount_minor: int = Field(ge=0)
    remaining_budget_minor: int
    member_contributions: list[HouseholdMemberContributionSummaryResponse] = Field(default_factory=list)


class HouseholdContributionCreateResponse(BaseModel):
    contribution: HouseholdContributionResponse
    budget_summary: HouseholdBudgetSummaryResponse


class HouseholdExpenseResponse(BaseModel):
    id: str
    household_id: str
    recorded_by_user_id: str
    paid_by_member_id: str
    expense_type: HouseholdExpenseType
    title: str
    description: str | None = None
    amount_minor: int = Field(ge=0)
    currency: str
    effective_date: date
    linked_order_id: str | None = None
    receipt_url: str | None = None
    receipt_source: HouseholdExpenseReceiptSource | None = None
    split_rule: HouseholdSplitRuleResponse
    status: HouseholdExpenseStatus
    created_at: datetime
    updated_at: datetime


class HouseholdExpenseSplitResponse(BaseModel):
    member_id: str
    user_id: str
    display_name: str
    owed_amount_minor: int
    paid_amount_minor: int
    net_amount_minor: int
    currency: str
    split_rule_type: HouseholdSplitRuleType
    created_at: datetime


class HouseholdExpenseDetailResponse(BaseModel):
    expense: HouseholdExpenseResponse
    splits: list[HouseholdExpenseSplitResponse] = Field(default_factory=list)


class HouseholdExpenseListResponse(BaseModel):
    items: list[HouseholdExpenseResponse] = Field(default_factory=list)


class HouseholdBalanceItemResponse(BaseModel):
    member_id: str
    display_name: str
    contributed_amount_minor: int = Field(ge=0)
    paid_amount_minor: int = Field(ge=0)
    owed_amount_minor: int = Field(ge=0)
    net_balance_minor: int


class HouseholdBalancesResponse(BaseModel):
    currency: str
    items: list[HouseholdBalanceItemResponse] = Field(default_factory=list)


class HouseholdExpenseMutationResponse(BaseModel):
    expense: HouseholdExpenseResponse
    splits: list[HouseholdExpenseSplitResponse] = Field(default_factory=list)
    budget_summary: HouseholdBudgetSummaryResponse
    balances: HouseholdBalancesResponse


class HouseholdMembershipSummaryResponse(BaseModel):
    household_id: str
    name: str
    currency: str
    role: HouseholdMemberRole
    member_count: int = Field(ge=0)


class HouseholdMembershipListResponse(BaseModel):
    items: list[HouseholdMembershipSummaryResponse] = Field(default_factory=list)


class HouseholdReceiptUploadResponse(BaseModel):
    receipt_url: str


class HouseholdImportableOrderResponse(BaseModel):
    order_id: str
    order_number: str
    order_type: HouseholdExpenseType
    effective_date: date
    total_minor: int = Field(ge=0)
    currency: str
    item_count: int = Field(ge=0)
    thumbnail_url: str | None = None


class HouseholdImportableOrderListResponse(BaseModel):
    items: list[HouseholdImportableOrderResponse] = Field(default_factory=list)


class HouseholdDetailResponse(BaseModel):
    household: HouseholdResponse
    members: list[HouseholdMemberResponse] = Field(default_factory=list)
    invitations: list[HouseholdInvitationResponse] = Field(default_factory=list)
    budget_summary: HouseholdBudgetSummaryResponse | None = None
    balances: HouseholdBalancesResponse | None = None
