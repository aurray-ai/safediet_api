from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from dataclasses import dataclass, field
from types import SimpleNamespace

from app.models.household import (
    Household,
    HouseholdBudgetContribution,
    HouseholdBudgetPeriod,
    HouseholdBudgetProfile,
    HouseholdContributionSource,
    HouseholdExpenseReceiptSource,
    HouseholdExpenseSplit,
    HouseholdExpenseStatus,
    HouseholdExpenseType,
    HouseholdMember,
    HouseholdMemberRole,
    HouseholdMemberStatus,
    HouseholdSharedExpense,
    HouseholdSplitRule,
    HouseholdSplitRuleType,
    HouseholdStatus,
)
from app.models.invitation import Invitation, InvitationStatus, InvitationType
from app.models.order import OrderStatus
from app.models.user import User, UserType
from app.services.household_budgeting_service import HouseholdBudgetingService
from app.services.household_service import (
    HouseholdConflictError,
    HouseholdPermissionError,
    HouseholdService,
    HouseholdValidationError,
)


@dataclass
class FakeOrder:
    id: str
    order_number: str
    user_id: str
    status: OrderStatus
    currency: str
    total_minor: int
    created_at: datetime
    items: list[object] = field(default_factory=list)

    @property
    def pricing_summary(self) -> SimpleNamespace:
        return SimpleNamespace(total_minor=self.total_minor)


class FakeOrderRepository:
    def __init__(self, orders: list[FakeOrder]) -> None:
        self.orders = {order.id: order for order in orders}

    def get_order_for_user(self, *, user_id: str, order_id: str) -> FakeOrder | None:
        order = self.orders.get(order_id)
        if order is None or order.user_id != user_id:
            return None
        return order

    def list_orders_for_user(
        self, *, user_id: str, before: str | None, limit: int
    ) -> tuple[list[FakeOrder], str | None]:
        items = [order for order in self.orders.values() if order.user_id == user_id]
        items.sort(key=lambda order: order.created_at, reverse=True)
        return items[:limit], None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_user(user_id: str, name: str) -> User:
    return User(
        id=user_id,
        name=name,
        email=f"{user_id}@example.com",
        password_hash="hash",
        user_types=[UserType.CUSTOMER],
        user_configuration={},
        created_at=utc_now(),
    )


class FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self.users = {user.id: user for user in users}

    def find_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def find_by_email(self, email: str) -> User | None:
        normalized_email = email.strip().lower()
        for user in self.users.values():
            if user.email.lower() == normalized_email:
                return user
        return None


class FakeHouseholdRepository:
    def __init__(self) -> None:
        self.items: dict[str, Household] = {}

    def create(
        self,
        *,
        owner_user_id: str,
        name: str,
        currency: str,
        budget_period: HouseholdBudgetPeriod,
        target_amount_minor: int,
        split_rule_type: HouseholdSplitRuleType,
    ) -> Household:
        item = Household(
            id=f"hh-{len(self.items) + 1}",
            owner_user_id=owner_user_id,
            name=name,
            status=HouseholdStatus.ACTIVE,
            currency=currency,
            planning_mode="household",
            budget_profile=HouseholdBudgetProfile(
                period=budget_period,
                target_amount_minor=target_amount_minor,
            ),
            default_split_rule=HouseholdSplitRule(type=split_rule_type, weights=[]),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_by_id(self, *, household_id: str) -> Household | None:
        return self.items.get(household_id)

    def get_active_by_owner_user_id(self, *, owner_user_id: str) -> Household | None:
        for item in self.items.values():
            if item.owner_user_id == owner_user_id and item.status == HouseholdStatus.ACTIVE:
                return item
        return None

    def list_by_ids(self, *, household_ids: list[str]) -> list[Household]:
        return [self.items[household_id] for household_id in household_ids if household_id in self.items]

    def update(
        self,
        *,
        household_id: str,
        name: str | None = None,
        target_amount_minor: int | None = None,
        budget_period: HouseholdBudgetPeriod | None = None,
        split_rule_type: HouseholdSplitRuleType | None = None,
    ) -> Household | None:
        current = self.items.get(household_id)
        if current is None:
            return None
        updated = Household(
            id=current.id,
            owner_user_id=current.owner_user_id,
            name=name if name is not None else current.name,
            status=current.status,
            currency=current.currency,
            planning_mode=current.planning_mode,
            budget_profile=HouseholdBudgetProfile(
                period=budget_period if budget_period is not None else current.budget_profile.period,
                target_amount_minor=(
                    target_amount_minor
                    if target_amount_minor is not None
                    else current.budget_profile.target_amount_minor
                ),
            ),
            default_split_rule=HouseholdSplitRule(
                type=split_rule_type if split_rule_type is not None else current.default_split_rule.type,
                weights=current.default_split_rule.weights,
            ),
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[household_id] = updated
        return updated

    def archive(self, *, household_id: str) -> Household | None:
        current = self.items.get(household_id)
        if current is None:
            return None
        archived = Household(
            id=current.id,
            owner_user_id=current.owner_user_id,
            name=current.name,
            status=HouseholdStatus.ARCHIVED,
            currency=current.currency,
            planning_mode=current.planning_mode,
            budget_profile=current.budget_profile,
            default_split_rule=current.default_split_rule,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[household_id] = archived
        return archived


class FakeHouseholdMemberRepository:
    def __init__(self) -> None:
        self.items: dict[str, HouseholdMember] = {}

    def create(
        self,
        *,
        household_id: str,
        user_id: str,
        display_name: str,
        role: HouseholdMemberRole,
        status: HouseholdMemberStatus = HouseholdMemberStatus.ACTIVE,
        share_weight: int = 1,
    ) -> HouseholdMember:
        item = HouseholdMember(
            id=f"member-{len(self.items) + 1}",
            household_id=household_id,
            user_id=user_id,
            display_name=display_name,
            role=role,
            status=status,
            share_weight=share_weight,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_by_id(self, *, member_id: str) -> HouseholdMember | None:
        return self.items.get(member_id)

    def get_by_household_and_user_id(self, *, household_id: str, user_id: str) -> HouseholdMember | None:
        for item in self.items.values():
            if item.household_id == household_id and item.user_id == user_id:
                return item
        return None

    def get_active_by_user_id(self, *, user_id: str) -> HouseholdMember | None:
        for item in self.items.values():
            if item.user_id == user_id and item.status == HouseholdMemberStatus.ACTIVE:
                return item
        return None

    def get_active_by_user_id_and_household_id(
        self, *, user_id: str, household_id: str
    ) -> HouseholdMember | None:
        for item in self.items.values():
            if (
                item.user_id == user_id
                and item.household_id == household_id
                and item.status == HouseholdMemberStatus.ACTIVE
            ):
                return item
        return None

    def list_active_by_user_id(self, *, user_id: str) -> list[HouseholdMember]:
        items = [
            item
            for item in self.items.values()
            if item.user_id == user_id and item.status == HouseholdMemberStatus.ACTIVE
        ]
        items.sort(key=lambda item: item.id)
        return items

    def list_by_household_id(
        self,
        *,
        household_id: str,
        include_inactive: bool = False,
    ) -> list[HouseholdMember]:
        items = [
            item
            for item in self.items.values()
            if item.household_id == household_id
            and (include_inactive or item.status == HouseholdMemberStatus.ACTIVE)
        ]
        items.sort(key=lambda item: item.id)
        return items

    def update_share_weight(self, *, member_id: str, share_weight: int) -> HouseholdMember | None:
        current = self.items.get(member_id)
        if current is None:
            return None
        updated = HouseholdMember(
            id=current.id,
            household_id=current.household_id,
            user_id=current.user_id,
            display_name=current.display_name,
            role=current.role,
            status=current.status,
            share_weight=share_weight,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[member_id] = updated
        return updated


class FakeInvitationRepository:
    def __init__(self) -> None:
        self.items: dict[str, Invitation] = {}

    def create(
        self,
        *,
        invitation_type: InvitationType,
        invited_by_user_id: str,
        invitee_email: str,
        invitee_user_id: str | None,
        display_name: str,
        token_hash: str,
        expires_at: datetime,
        context: dict,
    ) -> Invitation:
        item = Invitation(
            id=f"invite-{len(self.items) + 1}",
            invitation_type=invitation_type,
            invited_by_user_id=invited_by_user_id,
            invitee_email=invitee_email,
            invitee_user_id=invitee_user_id,
            display_name=display_name,
            status=InvitationStatus.PENDING,
            token_hash=token_hash,
            expires_at=expires_at,
            accepted_at=None,
            accepted_by_user_id=None,
            context=dict(context),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_by_id(self, *, invitation_id: str) -> Invitation | None:
        return self.items.get(invitation_id)

    def list_by_type(
        self,
        *,
        invitation_type: InvitationType,
        context_filters: dict | None = None,
        statuses: list[InvitationStatus] | None = None,
    ) -> list[Invitation]:
        items = [item for item in self.items.values() if item.invitation_type == invitation_type]
        for key, value in (context_filters or {}).items():
            items = [item for item in items if item.context.get(key) == value]
        if statuses:
            allowed = set(statuses)
            items = [item for item in items if item.status in allowed]
        items.sort(key=lambda item: item.id, reverse=True)
        return items

    def get_pending_by_type_and_email(
        self,
        *,
        invitation_type: InvitationType,
        invitee_email: str,
        context_filters: dict | None,
        now: datetime,
    ) -> Invitation | None:
        normalized = invitee_email.strip().lower()
        for item in self.items.values():
            if item.invitation_type != invitation_type:
                continue
            if item.invitee_email.lower() != normalized:
                continue
            if item.status != InvitationStatus.PENDING or item.expires_at <= now:
                continue
            if context_filters and any(item.context.get(key) != value for key, value in context_filters.items()):
                continue
            return item
        return None

    def find_active_by_token_hash(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> Invitation | None:
        for item in self.items.values():
            if (
                item.token_hash == token_hash
                and item.status == InvitationStatus.PENDING
                and item.expires_at > now
            ):
                return item
        return None

    def mark_accepted(
        self,
        *,
        invitation_id: str,
        accepted_by_user_id: str,
    ) -> Invitation | None:
        current = self.items.get(invitation_id)
        if current is None:
            return None
        updated = Invitation(
            id=current.id,
            invitation_type=current.invitation_type,
            invited_by_user_id=current.invited_by_user_id,
            invitee_email=current.invitee_email,
            invitee_user_id=current.invitee_user_id,
            display_name=current.display_name,
            status=InvitationStatus.ACCEPTED,
            token_hash=current.token_hash,
            expires_at=current.expires_at,
            accepted_at=utc_now(),
            accepted_by_user_id=accepted_by_user_id,
            context=dict(current.context),
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[invitation_id] = updated
        return updated

    def deactivate(self, *, member_id: str) -> HouseholdMember | None:
        current = self.items.get(member_id)
        if current is None:
            return None
        updated = HouseholdMember(
            id=current.id,
            household_id=current.household_id,
            user_id=current.user_id,
            display_name=current.display_name,
            role=current.role,
            status=HouseholdMemberStatus.INACTIVE,
            share_weight=current.share_weight,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[member_id] = updated
        return updated


class FakeContributionRepository:
    def __init__(self) -> None:
        self.items: list[HouseholdBudgetContribution] = []

    def create(self, **kwargs: object) -> HouseholdBudgetContribution:
        item = HouseholdBudgetContribution(
            id=f"contribution-{len(self.items) + 1}",
            household_id=str(kwargs["household_id"]),
            member_id=str(kwargs["member_id"]),
            user_id=str(kwargs["user_id"]),
            amount_minor=int(kwargs["amount_minor"]),
            currency=str(kwargs["currency"]),
            period_start=kwargs["period_start"],  # type: ignore[assignment]
            period_end=kwargs["period_end"],  # type: ignore[assignment]
            source=kwargs["source"],  # type: ignore[assignment]
            note=kwargs["note"],  # type: ignore[assignment]
            created_by_user_id=str(kwargs["created_by_user_id"]),
            created_at=utc_now(),
        )
        self.items.append(item)
        return item

    def list_by_household_and_period(self, *, household_id: str, period_start: date, period_end: date) -> list[HouseholdBudgetContribution]:
        return [
            item
            for item in self.items
            if item.household_id == household_id
            and item.period_start >= period_start
            and item.period_end <= period_end
        ][::-1]

    def sum_by_household_and_period(self, *, household_id: str, period_start: date, period_end: date) -> int:
        return sum(
            item.amount_minor
            for item in self.items
            if item.household_id == household_id
            and item.period_start >= period_start
            and item.period_end <= period_end
        )

    def member_totals_by_household_and_period(self, *, household_id: str, period_start: date, period_end: date) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            if item.household_id != household_id:
                continue
            if item.period_start < period_start or item.period_end > period_end:
                continue
            result[item.member_id] = result.get(item.member_id, 0) + item.amount_minor
        return result


class FakeExpenseRepository:
    def __init__(self) -> None:
        self.items: dict[str, HouseholdSharedExpense] = {}

    def create(self, **kwargs: object) -> HouseholdSharedExpense:
        item = HouseholdSharedExpense(
            id=f"expense-{len(self.items) + 1}",
            household_id=str(kwargs["household_id"]),
            recorded_by_user_id=str(kwargs["recorded_by_user_id"]),
            paid_by_member_id=str(kwargs["paid_by_member_id"]),
            expense_type=kwargs["expense_type"],  # type: ignore[assignment]
            title=str(kwargs["title"]),
            description=kwargs["description"],  # type: ignore[assignment]
            amount_minor=int(kwargs["amount_minor"]),
            currency=str(kwargs["currency"]),
            effective_date=kwargs["effective_date"],  # type: ignore[assignment]
            linked_order_id=kwargs["linked_order_id"],  # type: ignore[assignment]
            receipt_url=kwargs.get("receipt_url"),  # type: ignore[arg-type]
            receipt_source=kwargs.get("receipt_source"),  # type: ignore[arg-type]
            split_rule=HouseholdSplitRule(type=kwargs["split_rule_type"], weights=[]),  # type: ignore[arg-type]
            status=kwargs["status"],  # type: ignore[assignment]
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.items[item.id] = item
        return item

    def get_by_id(self, *, expense_id: str) -> HouseholdSharedExpense | None:
        return self.items.get(expense_id)

    def get_by_household_and_id(self, *, household_id: str, expense_id: str) -> HouseholdSharedExpense | None:
        item = self.items.get(expense_id)
        if item is None or item.household_id != household_id:
            return None
        return item

    def list_linked_order_ids(self, *, household_id: str) -> set[str]:
        return {
            item.linked_order_id
            for item in self.items.values()
            if item.household_id == household_id and item.linked_order_id is not None
        }

    def list_by_household_and_date_range(self, *, household_id: str, date_from: date, date_to: date) -> list[HouseholdSharedExpense]:
        items = [
            item
            for item in self.items.values()
            if item.household_id == household_id
            and date_from <= item.effective_date <= date_to
        ]
        items.sort(key=lambda item: item.effective_date, reverse=True)
        return items

    def update_status(self, *, expense_id: str, status: HouseholdExpenseStatus) -> HouseholdSharedExpense | None:
        current = self.items.get(expense_id)
        if current is None:
            return None
        updated = HouseholdSharedExpense(
            id=current.id,
            household_id=current.household_id,
            recorded_by_user_id=current.recorded_by_user_id,
            paid_by_member_id=current.paid_by_member_id,
            expense_type=current.expense_type,
            title=current.title,
            description=current.description,
            amount_minor=current.amount_minor,
            currency=current.currency,
            effective_date=current.effective_date,
            linked_order_id=current.linked_order_id,
            receipt_url=current.receipt_url,
            receipt_source=current.receipt_source,
            split_rule=current.split_rule,
            status=status,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self.items[expense_id] = updated
        return updated


class FakeSplitRepository:
    def __init__(self) -> None:
        self.items: list[HouseholdExpenseSplit] = []

    def replace_for_expense(
        self,
        *,
        household_id: str,
        expense_id: str,
        currency: str,
        split_rule_type: HouseholdSplitRuleType,
        rows: list[dict[str, object]],
    ) -> list[HouseholdExpenseSplit]:
        self.items = [item for item in self.items if item.expense_id != expense_id]
        created: list[HouseholdExpenseSplit] = []
        for row in rows:
            item = HouseholdExpenseSplit(
                id=f"split-{len(self.items) + len(created) + 1}",
                household_id=household_id,
                expense_id=expense_id,
                member_id=str(row["member_id"]),
                user_id=str(row["user_id"]),
                owed_amount_minor=int(row["owed_amount_minor"]),
                paid_amount_minor=int(row["paid_amount_minor"]),
                net_amount_minor=int(row["net_amount_minor"]),
                currency=currency,
                split_rule_type=split_rule_type,
                created_at=utc_now(),
            )
            created.append(item)
        self.items.extend(created)
        return created

    def list_by_expense(self, *, expense_id: str) -> list[HouseholdExpenseSplit]:
        return [item for item in self.items if item.expense_id == expense_id]

    def list_by_expense_ids(self, *, expense_ids: list[str]) -> list[HouseholdExpenseSplit]:
        return [item for item in self.items if item.expense_id in expense_ids]


class FakeHouseholdCommunicationService:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.invitation_events: list[dict[str, object]] = []

    def notify(self, **kwargs: object) -> None:
        self.events.append(kwargs)

    def notify_invitation(self, **kwargs: object) -> None:
        self.invitation_events.append(kwargs)


class HouseholdBackendServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = make_user("user-1", "Sarah")
        self.member = make_user("user-2", "David")
        self.member2 = make_user("user-3", "Aisha")
        self.user_repository = FakeUserRepository([self.owner, self.member, self.member2])
        self.household_repository = FakeHouseholdRepository()
        self.household_member_repository = FakeHouseholdMemberRepository()
        self.invitation_repository = FakeInvitationRepository()
        self.contribution_repository = FakeContributionRepository()
        self.expense_repository = FakeExpenseRepository()
        self.split_repository = FakeSplitRepository()
        self.household_communication_service = FakeHouseholdCommunicationService()
        self.household_service = HouseholdService(
            household_repository=self.household_repository,
            household_member_repository=self.household_member_repository,
            invitation_repository=self.invitation_repository,
            user_repository=self.user_repository,
            household_communication_service=self.household_communication_service,
        )
        self.budgeting_service = HouseholdBudgetingService(
            household_service=self.household_service,
            household_repository=self.household_repository,
            household_member_repository=self.household_member_repository,
            household_budget_contribution_repository=self.contribution_repository,
            household_shared_expense_repository=self.expense_repository,
            household_expense_split_repository=self.split_repository,
            household_communication_service=self.household_communication_service,
        )

    def test_create_household_creates_owner_membership(self) -> None:
        response = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )

        self.assertEqual("Our Kitchen", response.household.name)
        self.assertEqual(1, response.household.member_count)
        self.assertEqual("Sarah", response.members[0].display_name)
        self.assertEqual(HouseholdMemberRole.OWNER, response.members[0].role)
        self.assertEqual("household_created", self.household_communication_service.events[-1]["focus"])

    def test_add_member_requires_owner(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )

        with self.assertRaises(HouseholdPermissionError):
            self.household_service.add_member(
                current_user=self.member,
                household_id=created.household.id,
                user_id=self.member2.id,
                contact=None,
                display_name=None,
                role=HouseholdMemberRole.ADULT,
                share_weight=1,
            )

    def test_invite_existing_user_creates_pending_invitation_and_notification(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )

        invitation = self.household_service.invite_member(
            current_user=self.owner,
            household_id=created.household.id,
            contact=self.member.email,
            display_name="David",
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )

        self.assertEqual(InvitationStatus.PENDING, invitation.status)
        self.assertEqual(self.member.id, invitation.invitee_user_id)
        self.assertEqual(
            1,
            len(self.household_member_repository.list_by_household_id(household_id=created.household.id)),
        )
        self.assertEqual("household_invitation", self.household_communication_service.invitation_events[-1]["focus"])

    def test_invite_new_email_creates_pending_invitation_without_user_id(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )

        invitation = self.household_service.invite_member(
            current_user=self.owner,
            household_id=created.household.id,
            contact="newmember@example.com",
            display_name="Bella",
            role=HouseholdMemberRole.GUEST,
            share_weight=1,
        )

        self.assertEqual(InvitationStatus.PENDING, invitation.status)
        self.assertIsNone(invitation.invitee_user_id)
        self.assertEqual("newmember@example.com", invitation.invitee_email)

    def test_accept_invitation_creates_active_membership(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        invitation = self.household_service.invite_member(
            current_user=self.owner,
            household_id=created.household.id,
            contact=self.member.email,
            display_name="David",
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )

        raw_token = self.household_communication_service.invitation_events[-1]["action_url"].rsplit("/", 1)[-1]
        accepted = self.household_service.accept_invitation(
            current_user=self.member,
            token=str(raw_token),
        )

        self.assertEqual(2, len(accepted.members))
        accepted_member = next(item for item in accepted.members if item.user_id == self.member.id)
        self.assertEqual(HouseholdMemberRole.ADULT, accepted_member.role)
        updated_invitation = self.invitation_repository.get_by_id(invitation_id=invitation.id)
        self.assertIsNotNone(updated_invitation)
        self.assertEqual(InvitationStatus.ACCEPTED, updated_invitation.status if updated_invitation is not None else None)

    def test_create_household_allows_user_to_belong_to_multiple_active_households(self) -> None:
        first = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )

        second = self.household_service.create_household(
            current_user=self.owner,
            name="Another Household",
            currency="GBP",
            target_amount_minor=10_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )

        self.assertNotEqual(first.household.id, second.household.id)
        memberships = self.household_service.list_households_for_user(current_user=self.owner)
        self.assertEqual(
            {first.household.id, second.household.id},
            {membership.household_id for membership in memberships},
        )

    def test_record_contribution_and_equal_split_balance_flow(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        david = self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )
        aisha = self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member2.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )

        contribution = self.budgeting_service.record_contribution(
            current_user=self.owner,
            household_id=created.household.id,
            member_id=david.id,
            amount_minor=3_000,
            currency="GBP",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            source=HouseholdContributionSource.MANUAL,
            note="Weekly top-up",
        )
        self.assertEqual(3_000, contribution.contribution.amount_minor)
        self.assertEqual(3_000, contribution.budget_summary.contributed_amount_minor)

        expense = self.budgeting_service.create_expense(
            current_user=self.owner,
            household_id=created.household.id,
            paid_by_member_id=created.members[0].id,
            expense_type=HouseholdExpenseType.GROCERY,
            title="Weekly Lidl shop",
            description="Fruit and veg",
            amount_minor=9_200,
            currency="GBP",
            effective_date=date(2026, 7, 18),
            linked_order_id=None,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
            status=HouseholdExpenseStatus.POSTED,
        )

        self.assertEqual(3, len(expense.splits))
        self.assertEqual(9_200, sum(item.owed_amount_minor for item in expense.splits))
        balances = {
            item.display_name: item.net_balance_minor
            for item in expense.balances.items
        }
        self.assertEqual(-6_133, balances["Sarah"])
        self.assertEqual(3_067, balances["David"])
        self.assertEqual(3_066, balances["Aisha"])

    def test_weighted_split_uses_member_weights(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.WEIGHTED,
        )
        david = self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=2,
        )
        self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member2.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )
        owner_member = created.members[0]
        self.household_service.update_member_weight(
            current_user=self.owner,
            household_id=created.household.id,
            member_id=owner_member.id,
            share_weight=1,
        )

        expense = self.budgeting_service.create_expense(
            current_user=self.owner,
            household_id=created.household.id,
            paid_by_member_id=david.id,
            expense_type=HouseholdExpenseType.GROCERY,
            title="Weighted shop",
            description=None,
            amount_minor=10_000,
            currency="GBP",
            effective_date=date(2026, 7, 18),
            linked_order_id=None,
            split_rule_type=HouseholdSplitRuleType.WEIGHTED,
            status=HouseholdExpenseStatus.POSTED,
        )

        owed = {item.display_name: item.owed_amount_minor for item in expense.splits}
        self.assertEqual(2_500, owed["Sarah"])
        self.assertEqual(5_000, owed["David"])
        self.assertEqual(2_500, owed["Aisha"])

    def test_voided_expense_is_excluded_from_balances(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )

        expense = self.budgeting_service.create_expense(
            current_user=self.owner,
            household_id=created.household.id,
            paid_by_member_id=created.members[0].id,
            expense_type=HouseholdExpenseType.GROCERY,
            title="Shared shop",
            description=None,
            amount_minor=6_000,
            currency="GBP",
            effective_date=date(2026, 7, 18),
            linked_order_id=None,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
            status=HouseholdExpenseStatus.POSTED,
        )

        voided = self.budgeting_service.void_expense(
            current_user=self.owner,
            household_id=created.household.id,
            expense_id=expense.expense.id,
        )

        balances = {item.display_name: item.net_balance_minor for item in voided.balances.items}
        self.assertEqual(0, balances["Sarah"])
        self.assertEqual(0, balances["David"])

    def test_finance_flow_emits_notifications(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        david = self.household_service.add_member(
            current_user=self.owner,
            household_id=created.household.id,
            user_id=self.member.id,
            contact=None,
            display_name=None,
            role=HouseholdMemberRole.ADULT,
            share_weight=1,
        )

        self.budgeting_service.record_contribution(
            current_user=self.member,
            household_id=created.household.id,
            member_id=david.id,
            amount_minor=3_000,
            currency="GBP",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            source=HouseholdContributionSource.MANUAL,
            note="Weekly top-up",
        )
        expense = self.budgeting_service.create_expense(
            current_user=self.owner,
            household_id=created.household.id,
            paid_by_member_id=created.members[0].id,
            expense_type=HouseholdExpenseType.GROCERY,
            title="Weekly Lidl shop",
            description="Fruit and veg",
            amount_minor=9_200,
            currency="GBP",
            effective_date=date(2026, 7, 18),
            linked_order_id=None,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
            status=HouseholdExpenseStatus.POSTED,
        )
        self.budgeting_service.void_expense(
            current_user=self.owner,
            household_id=created.household.id,
            expense_id=expense.expense.id,
        )

        focuses = [str(event["focus"]) for event in self.household_communication_service.events]
        self.assertIn("member_added", focuses)
        self.assertIn("contribution_added", focuses)
        self.assertIn("expense_added", focuses)
        self.assertIn("expense_voided", focuses)

    def test_create_expense_from_linked_order_overrides_amount_and_marks_receipt_source(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        order = FakeOrder(
            id="order-1",
            order_number="4521",
            user_id=self.owner.id,
            status=OrderStatus.DELIVERED,
            currency="GBP",
            total_minor=9_230,
            created_at=utc_now(),
        )
        order_repository = FakeOrderRepository([order])
        budgeting_service = HouseholdBudgetingService(
            household_service=self.household_service,
            household_repository=self.household_repository,
            household_member_repository=self.household_member_repository,
            household_budget_contribution_repository=self.contribution_repository,
            household_shared_expense_repository=self.expense_repository,
            household_expense_split_repository=self.split_repository,
            household_communication_service=self.household_communication_service,
            order_repository=order_repository,
        )

        result = budgeting_service.create_expense(
            current_user=self.owner,
            household_id=created.household.id,
            paid_by_member_id=created.members[0].id,
            expense_type=HouseholdExpenseType.GROCERY,
            title="",
            description=None,
            amount_minor=1,
            currency="GBP",
            effective_date=date(2026, 1, 1),
            linked_order_id="order-1",
            split_rule_type=HouseholdSplitRuleType.EQUAL,
            status=HouseholdExpenseStatus.POSTED,
        )

        self.assertEqual(9_230, result.expense.amount_minor)
        self.assertEqual("order-1", result.expense.linked_order_id)
        self.assertEqual(HouseholdExpenseReceiptSource.GROCERY_ORDER, result.expense.receipt_source)

        with self.assertRaises(HouseholdValidationError):
            budgeting_service.create_expense(
                current_user=self.owner,
                household_id=created.household.id,
                paid_by_member_id=created.members[0].id,
                expense_type=HouseholdExpenseType.GROCERY,
                title="Duplicate import",
                description=None,
                amount_minor=1,
                currency="GBP",
                effective_date=date(2026, 1, 1),
                linked_order_id="order-1",
                split_rule_type=HouseholdSplitRuleType.EQUAL,
                status=HouseholdExpenseStatus.POSTED,
            )

    def test_list_importable_orders_excludes_already_linked_orders(self) -> None:
        created = self.household_service.create_household(
            current_user=self.owner,
            name="Our Kitchen",
            currency="GBP",
            target_amount_minor=12_000,
            budget_period=HouseholdBudgetPeriod.WEEKLY,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
        )
        linked_order = FakeOrder(
            id="order-linked",
            order_number="1001",
            user_id=self.owner.id,
            status=OrderStatus.DELIVERED,
            currency="GBP",
            total_minor=5_000,
            created_at=utc_now(),
        )
        importable_order = FakeOrder(
            id="order-importable",
            order_number="1002",
            user_id=self.owner.id,
            status=OrderStatus.DELIVERED,
            currency="GBP",
            total_minor=6_000,
            created_at=utc_now(),
        )
        order_repository = FakeOrderRepository([linked_order, importable_order])
        budgeting_service = HouseholdBudgetingService(
            household_service=self.household_service,
            household_repository=self.household_repository,
            household_member_repository=self.household_member_repository,
            household_budget_contribution_repository=self.contribution_repository,
            household_shared_expense_repository=self.expense_repository,
            household_expense_split_repository=self.split_repository,
            household_communication_service=self.household_communication_service,
            order_repository=order_repository,
        )
        budgeting_service.create_expense(
            current_user=self.owner,
            household_id=created.household.id,
            paid_by_member_id=created.members[0].id,
            expense_type=HouseholdExpenseType.GROCERY,
            title="",
            description=None,
            amount_minor=1,
            currency="GBP",
            effective_date=date(2026, 1, 1),
            linked_order_id="order-linked",
            split_rule_type=HouseholdSplitRuleType.EQUAL,
            status=HouseholdExpenseStatus.POSTED,
        )

        result = budgeting_service.list_importable_orders(
            current_user=self.owner,
            household_id=created.household.id,
            expense_type=HouseholdExpenseType.GROCERY,
        )

        order_ids = [item.order_id for item in result.items]
        self.assertNotIn("order-linked", order_ids)
        self.assertIn("order-importable", order_ids)


if __name__ == "__main__":
    unittest.main()
