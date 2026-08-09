from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class HouseholdStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class HouseholdBudgetPeriod(StrEnum):
    WEEKLY = "weekly"


class HouseholdMemberRole(StrEnum):
    OWNER = "owner"
    ADULT = "adult"
    TEEN = "teen"
    CHILD = "child"
    GUEST = "guest"

    @property
    def can_split_expenses(self) -> bool:
        return self not in {HouseholdMemberRole.CHILD, HouseholdMemberRole.GUEST}


class HouseholdMemberStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class HouseholdContributionSource(StrEnum):
    MANUAL = "manual"
    WALLET_TRANSFER = "wallet_transfer"


class HouseholdExpenseType(StrEnum):
    GROCERY = "grocery"
    SHARED_MEAL = "shared_meal"


class HouseholdExpenseReceiptSource(StrEnum):
    UPLOAD = "upload"
    GROCERY_ORDER = "grocery_order"
    MEAL_ORDER = "meal_order"


class HouseholdExpenseStatus(StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    VOID = "void"


class HouseholdSplitRuleType(StrEnum):
    EQUAL = "equal"
    WEIGHTED = "weighted"


@dataclass(frozen=True, slots=True)
class HouseholdBudgetProfile:
    period: HouseholdBudgetPeriod
    target_amount_minor: int


@dataclass(frozen=True, slots=True)
class HouseholdSplitRule:
    type: HouseholdSplitRuleType
    weights: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Household:
    id: str
    owner_user_id: str
    name: str
    status: HouseholdStatus
    currency: str
    planning_mode: str
    budget_profile: HouseholdBudgetProfile
    default_split_rule: HouseholdSplitRule
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HouseholdMember:
    id: str
    household_id: str
    user_id: str
    display_name: str
    role: HouseholdMemberRole
    status: HouseholdMemberStatus
    share_weight: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HouseholdBudgetContribution:
    id: str
    household_id: str
    member_id: str
    user_id: str
    amount_minor: int
    currency: str
    period_start: date
    period_end: date
    source: HouseholdContributionSource
    note: str | None
    created_by_user_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class HouseholdSharedExpense:
    id: str
    household_id: str
    recorded_by_user_id: str
    paid_by_member_id: str
    expense_type: HouseholdExpenseType
    title: str
    description: str | None
    amount_minor: int
    currency: str
    effective_date: date
    linked_order_id: str | None
    receipt_url: str | None
    receipt_source: HouseholdExpenseReceiptSource | None
    split_rule: HouseholdSplitRule
    status: HouseholdExpenseStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HouseholdExpenseSplit:
    id: str
    household_id: str
    expense_id: str
    member_id: str
    user_id: str
    owed_amount_minor: int
    paid_amount_minor: int
    net_amount_minor: int
    currency: str
    split_rule_type: HouseholdSplitRuleType
    created_at: datetime
