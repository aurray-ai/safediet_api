from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.models.household import (
    Household,
    HouseholdBudgetContribution,
    HouseholdContributionSource,
    HouseholdExpenseReceiptSource,
    HouseholdExpenseSplit,
    HouseholdExpenseStatus,
    HouseholdExpenseType,
    HouseholdMember,
    HouseholdMemberRole,
    HouseholdMemberStatus,
    HouseholdSharedExpense,
    HouseholdSplitRuleType,
)
from app.models.order import OrderStatus
from app.models.user import User
from app.repositories.household_budget_contribution_repository import (
    HouseholdBudgetContributionRepository,
)
from app.repositories.household_expense_split_repository import HouseholdExpenseSplitRepository
from app.repositories.household_member_repository import HouseholdMemberRepository
from app.repositories.household_repository import HouseholdRepository
from app.repositories.household_shared_expense_repository import HouseholdSharedExpenseRepository
from app.repositories.meal_order_repository import MealOrderRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.household import (
    HouseholdBalanceItemResponse,
    HouseholdBalancesResponse,
    HouseholdBudgetSummaryResponse,
    HouseholdContributionCreateResponse,
    HouseholdContributionListResponse,
    HouseholdContributionResponse,
    HouseholdExpenseDetailResponse,
    HouseholdExpenseListResponse,
    HouseholdExpenseMutationResponse,
    HouseholdExpenseResponse,
    HouseholdExpenseSplitResponse,
    HouseholdImportableOrderListResponse,
    HouseholdImportableOrderResponse,
    HouseholdMemberContributionSummaryResponse,
)
from app.services.household_communication_service import HouseholdCommunicationService
from app.services.household_service import (
    HouseholdNotFoundError,
    HouseholdPermissionError,
    HouseholdPeriodWindow,
    HouseholdService,
    HouseholdValidationError,
)


class HouseholdBudgetingService:
    def __init__(
        self,
        *,
        household_service: HouseholdService,
        household_repository: HouseholdRepository,
        household_member_repository: HouseholdMemberRepository,
        household_budget_contribution_repository: HouseholdBudgetContributionRepository,
        household_shared_expense_repository: HouseholdSharedExpenseRepository,
        household_expense_split_repository: HouseholdExpenseSplitRepository,
        household_communication_service: HouseholdCommunicationService | None = None,
        order_repository: OrderRepository | None = None,
        meal_order_repository: MealOrderRepository | None = None,
    ) -> None:
        self._household_service = household_service
        self._household_repository = household_repository
        self._household_member_repository = household_member_repository
        self._household_budget_contribution_repository = household_budget_contribution_repository
        self._household_shared_expense_repository = household_shared_expense_repository
        self._household_expense_split_repository = household_expense_split_repository
        self._household_communication_service = household_communication_service
        self._order_repository = order_repository
        self._meal_order_repository = meal_order_repository

    def record_contribution(
        self,
        *,
        current_user: User,
        household_id: str,
        member_id: str,
        amount_minor: int,
        currency: str,
        period_start: date | None,
        period_end: date | None,
        source: HouseholdContributionSource,
        note: str | None,
    ) -> HouseholdContributionCreateResponse:
        household, actor_membership = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
        )
        member = self._require_active_household_member(household_id=household_id, member_id=member_id)
        if (
            actor_membership.role != HouseholdMemberRole.OWNER
            and actor_membership.user_id != member.user_id
        ):
            raise HouseholdPermissionError("Members can only record their own contributions.")
        if currency != household.currency:
            raise HouseholdValidationError("Contribution currency must match household currency.")

        period_window = self._household_service.resolve_period_window(
            period_start=period_start,
            period_end=period_end,
        )
        contribution = self._household_budget_contribution_repository.create(
            household_id=household_id,
            member_id=member_id,
            user_id=member.user_id,
            amount_minor=amount_minor,
            currency=currency,
            period_start=period_window.period_start,
            period_end=period_window.period_end,
            source=source,
            note=note,
            created_by_user_id=current_user.id,
        )
        self._notify(
            household_id=household_id,
            recipient_user_ids=self._list_recipient_user_ids(household_id=household_id),
            title="Contribution added",
            message=(
                f"{member.display_name} added {self._format_amount(currency, amount_minor)} "
                "to the shared budget."
            ),
            focus="contribution_added",
            idempotency_key=f"household_contribution:{contribution.id}",
            email_subject="A household contribution was added",
            email_intro=(
                f"{member.display_name} added {self._format_amount(currency, amount_minor)} "
                "to the shared budget."
            ),
            details={
                "contribution_id": contribution.id,
                "member_id": member.id,
                "amount_minor": amount_minor,
                "currency": currency,
            },
        )
        summary = self.get_budget_summary(
            current_user=current_user,
            household_id=household_id,
            period_start=period_window.period_start,
            period_end=period_window.period_end,
        )
        return HouseholdContributionCreateResponse(
            contribution=self._to_contribution_response(contribution),
            budget_summary=summary,
        )

    def list_contributions(
        self,
        *,
        current_user: User,
        household_id: str,
        period_start: date | None,
        period_end: date | None,
    ) -> HouseholdContributionListResponse:
        self._require_active_membership(current_user=current_user, household_id=household_id)
        period_window = self._household_service.resolve_period_window(
            period_start=period_start,
            period_end=period_end,
        )
        items = self._household_budget_contribution_repository.list_by_household_and_period(
            household_id=household_id,
            period_start=period_window.period_start,
            period_end=period_window.period_end,
        )
        return HouseholdContributionListResponse(
            items=[self._to_contribution_response(item) for item in items]
        )

    def create_expense(
        self,
        *,
        current_user: User,
        household_id: str,
        paid_by_member_id: str,
        expense_type: HouseholdExpenseType,
        title: str,
        description: str | None,
        amount_minor: int,
        currency: str,
        effective_date: date,
        linked_order_id: str | None,
        receipt_url: str | None = None,
        receipt_source: HouseholdExpenseReceiptSource | None = None,
        split_rule_type: HouseholdSplitRuleType | None,
        status: HouseholdExpenseStatus,
    ) -> HouseholdExpenseMutationResponse:
        household, _ = self._require_active_membership(current_user=current_user, household_id=household_id)
        payer = self._require_active_household_member(
            household_id=household_id,
            member_id=paid_by_member_id,
        )

        resolved_receipt_source = receipt_source
        if linked_order_id is not None:
            title, amount_minor, currency, effective_date = self._resolve_linked_order_snapshot(
                current_user=current_user,
                household_id=household_id,
                expense_type=expense_type,
                order_id=linked_order_id,
                fallback_title=title,
            )
            if resolved_receipt_source is None:
                resolved_receipt_source = (
                    HouseholdExpenseReceiptSource.GROCERY_ORDER
                    if expense_type == HouseholdExpenseType.GROCERY
                    else HouseholdExpenseReceiptSource.MEAL_ORDER
                )
        elif receipt_url is not None and resolved_receipt_source is None:
            resolved_receipt_source = HouseholdExpenseReceiptSource.UPLOAD

        if currency != household.currency:
            raise HouseholdValidationError("Expense currency must match household currency.")

        resolved_split_rule_type = split_rule_type or household.default_split_rule.type
        expense = self._household_shared_expense_repository.create(
            household_id=household_id,
            recorded_by_user_id=current_user.id,
            paid_by_member_id=payer.id,
            expense_type=expense_type,
            title=title,
            description=description,
            amount_minor=amount_minor,
            currency=currency,
            effective_date=effective_date,
            linked_order_id=linked_order_id,
            receipt_url=receipt_url,
            receipt_source=resolved_receipt_source,
            split_rule_type=resolved_split_rule_type,
            status=status,
        )
        splits: list[HouseholdExpenseSplit] = []
        if expense.status == HouseholdExpenseStatus.POSTED:
            splits = self._compute_and_persist_splits(
                household=household,
                expense=expense,
            )
        self._notify(
            household_id=household_id,
            recipient_user_ids=self._list_recipient_user_ids(household_id=household_id),
            title="Shared expense added",
            message=(
                f"{title} was added for {self._format_amount(currency, amount_minor)} "
                f"and marked as {expense.status.value}."
            ),
            focus="expense_added",
            idempotency_key=f"household_expense:{expense.id}:{expense.status.value}",
            email_subject="A shared expense was added",
            email_intro=(
                f"{title} was added for {self._format_amount(currency, amount_minor)} "
                f"and marked as {expense.status.value}."
            ),
            details={
                "expense_id": expense.id,
                "paid_by_member_id": payer.id,
                "amount_minor": amount_minor,
                "currency": currency,
                "status": expense.status.value,
            },
        )

        period_window = self._household_service.resolve_week_window_for_date(
            anchor_date=effective_date
        )
        return HouseholdExpenseMutationResponse(
            expense=self._to_expense_response(expense),
            splits=self._to_split_responses(splits),
            budget_summary=self.get_budget_summary(
                current_user=current_user,
                household_id=household_id,
                period_start=period_window.period_start,
                period_end=period_window.period_end,
            ),
            balances=self.get_member_balances(
                current_user=current_user,
                household_id=household_id,
                period_start=period_window.period_start,
                period_end=period_window.period_end,
            ),
        )

    def ensure_active_membership(
        self,
        *,
        current_user: User,
        household_id: str,
    ) -> None:
        self._require_active_membership(current_user=current_user, household_id=household_id)

    def list_importable_orders(
        self,
        *,
        current_user: User,
        household_id: str,
        expense_type: HouseholdExpenseType,
    ) -> HouseholdImportableOrderListResponse:
        self._require_active_membership(current_user=current_user, household_id=household_id)
        already_linked = self._household_shared_expense_repository.list_linked_order_ids(
            household_id=household_id
        )

        items: list[HouseholdImportableOrderResponse] = []
        if expense_type == HouseholdExpenseType.GROCERY:
            if self._order_repository is None:
                return HouseholdImportableOrderListResponse(items=[])
            orders, _ = self._order_repository.list_orders_for_user(
                user_id=current_user.id,
                before=None,
                limit=25,
            )
            for order in orders:
                if order.status != OrderStatus.DELIVERED or order.id in already_linked:
                    continue
                items.append(
                    HouseholdImportableOrderResponse(
                        order_id=order.id,
                        order_number=order.order_number,
                        order_type=HouseholdExpenseType.GROCERY,
                        effective_date=order.created_at.date(),
                        total_minor=order.pricing_summary.total_minor,
                        currency=order.currency,
                        item_count=len(order.items),
                        thumbnail_url=order.items[0].img_url if order.items else None,
                    )
                )
        else:
            if self._meal_order_repository is None:
                return HouseholdImportableOrderListResponse(items=[])
            orders, _ = self._meal_order_repository.list_orders_for_user(
                user_id=current_user.id,
                before=None,
                limit=25,
            )
            for order in orders:
                if order.status != OrderStatus.DELIVERED or order.id in already_linked:
                    continue
                items.append(
                    HouseholdImportableOrderResponse(
                        order_id=order.id,
                        order_number=order.order_number,
                        order_type=HouseholdExpenseType.SHARED_MEAL,
                        effective_date=order.created_at.date(),
                        total_minor=order.pricing_summary.total_minor,
                        currency=order.currency,
                        item_count=len(order.items),
                        thumbnail_url=None,
                    )
                )
        return HouseholdImportableOrderListResponse(items=items)

    def _resolve_linked_order_snapshot(
        self,
        *,
        current_user: User,
        household_id: str,
        expense_type: HouseholdExpenseType,
        order_id: str,
        fallback_title: str,
    ) -> tuple[str, int, str, date]:
        already_linked = self._household_shared_expense_repository.list_linked_order_ids(
            household_id=household_id
        )
        if order_id in already_linked:
            raise HouseholdValidationError("That order has already been imported as an expense.")

        if expense_type == HouseholdExpenseType.GROCERY:
            if self._order_repository is None:
                raise HouseholdNotFoundError("Order not found.")
            order = self._order_repository.get_order_for_user(
                user_id=current_user.id,
                order_id=order_id,
            )
            if order is None:
                raise HouseholdNotFoundError("Order not found.")
            title = fallback_title.strip() or f"Groceries — Order #{order.order_number}"
            return title, order.pricing_summary.total_minor, order.currency, order.created_at.date()

        if self._meal_order_repository is None:
            raise HouseholdNotFoundError("Order not found.")
        meal_order = self._meal_order_repository.get_order_for_user(
            user_id=current_user.id,
            order_id=order_id,
        )
        if meal_order is None:
            raise HouseholdNotFoundError("Order not found.")
        title = fallback_title.strip() or f"Meals — Order #{meal_order.order_number}"
        return title, meal_order.pricing_summary.total_minor, meal_order.currency, meal_order.created_at.date()

    def get_expense_detail(
        self,
        *,
        current_user: User,
        household_id: str,
        expense_id: str,
    ) -> HouseholdExpenseDetailResponse:
        self._require_active_membership(current_user=current_user, household_id=household_id)
        expense = self._household_shared_expense_repository.get_by_household_and_id(
            household_id=household_id,
            expense_id=expense_id,
        )
        if expense is None:
            raise HouseholdNotFoundError("Expense not found.")
        splits = self._household_expense_split_repository.list_by_expense(expense_id=expense_id)
        return HouseholdExpenseDetailResponse(
            expense=self._to_expense_response(expense),
            splits=self._to_split_responses(splits),
        )

    def list_expenses(
        self,
        *,
        current_user: User,
        household_id: str,
        date_from: date,
        date_to: date,
    ) -> HouseholdExpenseListResponse:
        self._require_active_membership(current_user=current_user, household_id=household_id)
        items = self._household_shared_expense_repository.list_by_household_and_date_range(
            household_id=household_id,
            date_from=date_from,
            date_to=date_to,
        )
        return HouseholdExpenseListResponse(
            items=[self._to_expense_response(item) for item in items]
        )

    def void_expense(
        self,
        *,
        current_user: User,
        household_id: str,
        expense_id: str,
    ) -> HouseholdExpenseMutationResponse:
        expense = self._household_shared_expense_repository.get_by_household_and_id(
            household_id=household_id,
            expense_id=expense_id,
        )
        if expense is None:
            raise HouseholdNotFoundError("Expense not found.")
        self._require_active_membership(current_user=current_user, household_id=household_id)
        updated = self._household_shared_expense_repository.update_status(
            expense_id=expense_id,
            status=HouseholdExpenseStatus.VOID,
        )
        if updated is None:
            raise HouseholdNotFoundError("Expense not found.")
        splits = self._household_expense_split_repository.list_by_expense(expense_id=expense_id)
        self._notify(
            household_id=household_id,
            recipient_user_ids=self._list_recipient_user_ids(household_id=household_id),
            title="Shared expense voided",
            message=f"{updated.title} was voided and removed from the current balances.",
            focus="expense_voided",
            idempotency_key=f"household_expense_voided:{updated.id}",
            email_subject="A shared expense was voided",
            email_intro=f"{updated.title} was voided and removed from the current balances.",
            details={
                "expense_id": updated.id,
                "amount_minor": updated.amount_minor,
                "currency": updated.currency,
            },
        )
        period_window = self._household_service.resolve_week_window_for_date(
            anchor_date=updated.effective_date
        )
        return HouseholdExpenseMutationResponse(
            expense=self._to_expense_response(updated),
            splits=self._to_split_responses(splits),
            budget_summary=self.get_budget_summary(
                current_user=current_user,
                household_id=household_id,
                period_start=period_window.period_start,
                period_end=period_window.period_end,
            ),
            balances=self.get_member_balances(
                current_user=current_user,
                household_id=household_id,
                period_start=period_window.period_start,
                period_end=period_window.period_end,
            ),
        )

    def get_budget_summary(
        self,
        *,
        current_user: User,
        household_id: str,
        period_start: date | None,
        period_end: date | None,
    ) -> HouseholdBudgetSummaryResponse:
        household, members = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
            include_members=True,
        )
        period_window = self._household_service.resolve_period_window(
            period_start=period_start,
            period_end=period_end,
        )
        contributed_amount_minor = (
            self._household_budget_contribution_repository.sum_by_household_and_period(
                household_id=household_id,
                period_start=period_window.period_start,
                period_end=period_window.period_end,
            )
        )
        member_totals = self._household_budget_contribution_repository.member_totals_by_household_and_period(
            household_id=household_id,
            period_start=period_window.period_start,
            period_end=period_window.period_end,
        )
        spent_amount_minor = sum(
            expense.amount_minor
            for expense in self._household_shared_expense_repository.list_by_household_and_date_range(
                household_id=household_id,
                date_from=period_window.period_start,
                date_to=period_window.period_end,
            )
            if expense.status == HouseholdExpenseStatus.POSTED
        )
        return HouseholdBudgetSummaryResponse(
            period_start=period_window.period_start,
            period_end=period_window.period_end,
            currency=household.currency,
            target_amount_minor=household.budget_profile.target_amount_minor,
            contributed_amount_minor=contributed_amount_minor,
            spent_amount_minor=spent_amount_minor,
            remaining_budget_minor=household.budget_profile.target_amount_minor - spent_amount_minor,
            member_contributions=[
                HouseholdMemberContributionSummaryResponse(
                    member_id=member.id,
                    display_name=member.display_name,
                    amount_minor=int(member_totals.get(member.id) or 0),
                )
                for member in members
            ],
        )

    def get_member_balances(
        self,
        *,
        current_user: User,
        household_id: str,
        period_start: date | None,
        period_end: date | None,
    ) -> HouseholdBalancesResponse:
        household, members = self._require_active_membership(
            current_user=current_user,
            household_id=household_id,
            include_members=True,
        )
        period_window = self._household_service.resolve_period_window(
            period_start=period_start,
            period_end=period_end,
        )
        contributions_by_member = self._household_budget_contribution_repository.member_totals_by_household_and_period(
            household_id=household_id,
            period_start=period_window.period_start,
            period_end=period_window.period_end,
        )
        posted_expenses = [
            expense
            for expense in self._household_shared_expense_repository.list_by_household_and_date_range(
                household_id=household_id,
                date_from=period_window.period_start,
                date_to=period_window.period_end,
            )
            if expense.status == HouseholdExpenseStatus.POSTED
        ]
        splits = self._household_expense_split_repository.list_by_expense_ids(
            expense_ids=[expense.id for expense in posted_expenses]
        )
        owed_by_member: dict[str, int] = defaultdict(int)
        paid_by_member: dict[str, int] = defaultdict(int)
        net_by_member: dict[str, int] = defaultdict(int)
        for split in splits:
            owed_by_member[split.member_id] += split.owed_amount_minor
            paid_by_member[split.member_id] += split.paid_amount_minor
            net_by_member[split.member_id] += split.net_amount_minor

        items = [
            HouseholdBalanceItemResponse(
                member_id=member.id,
                display_name=member.display_name,
                contributed_amount_minor=int(contributions_by_member.get(member.id) or 0),
                paid_amount_minor=paid_by_member.get(member.id, 0),
                owed_amount_minor=owed_by_member.get(member.id, 0),
                net_balance_minor=net_by_member.get(member.id, 0),
            )
            for member in members
        ]
        return HouseholdBalancesResponse(currency=household.currency, items=items)

    def _compute_and_persist_splits(
        self,
        *,
        household: Household,
        expense: HouseholdSharedExpense,
    ) -> list[HouseholdExpenseSplit]:
        members = self._household_member_repository.list_by_household_id(household_id=household.id)
        split_members = [
            member
            for member in members
            if member.status == HouseholdMemberStatus.ACTIVE and member.role.can_split_expenses
        ]
        if not split_members:
            raise HouseholdValidationError("No active members available for expense splitting.")

        ordered_members = sorted(split_members, key=lambda member: member.id)
        owed_map = self._allocate_owed_amounts(
            amount_minor=expense.amount_minor,
            members=ordered_members,
            split_rule_type=expense.split_rule.type,
        )
        rows: list[dict[str, int | str]] = []
        for member in ordered_members:
            paid_amount_minor = expense.amount_minor if member.id == expense.paid_by_member_id else 0
            owed_amount_minor = owed_map[member.id]
            rows.append(
                {
                    "member_id": member.id,
                    "user_id": member.user_id,
                    "owed_amount_minor": owed_amount_minor,
                    "paid_amount_minor": paid_amount_minor,
                    "net_amount_minor": owed_amount_minor - paid_amount_minor,
                }
            )
        return self._household_expense_split_repository.replace_for_expense(
            household_id=household.id,
            expense_id=expense.id,
            currency=expense.currency,
            split_rule_type=expense.split_rule.type,
            rows=rows,
        )

    @staticmethod
    def _allocate_owed_amounts(
        *,
        amount_minor: int,
        members: list[HouseholdMember],
        split_rule_type: HouseholdSplitRuleType,
    ) -> dict[str, int]:
        if split_rule_type == HouseholdSplitRuleType.EQUAL:
            count = len(members)
            base = amount_minor // count
            remainder = amount_minor % count
            result: dict[str, int] = {}
            for index, member in enumerate(members):
                result[member.id] = base + (1 if index < remainder else 0)
            return result

        total_weight = sum(max(member.share_weight, 1) for member in members)
        allocations: dict[str, int] = {}
        assigned = 0
        for member in members:
            owed = (amount_minor * max(member.share_weight, 1)) // total_weight
            allocations[member.id] = owed
            assigned += owed
        remainder = amount_minor - assigned
        for member in members:
            if remainder <= 0:
                break
            allocations[member.id] += 1
            remainder -= 1
        return allocations

    def _require_active_membership(
        self,
        *,
        current_user: User,
        household_id: str,
        include_members: bool = False,
    ) -> tuple[Household, HouseholdMember] | tuple[Household, list[HouseholdMember]]:
        actor_membership = self._household_member_repository.get_by_household_and_user_id(
            household_id=household_id,
            user_id=current_user.id,
        )
        if actor_membership is None or actor_membership.status != HouseholdMemberStatus.ACTIVE:
            raise HouseholdPermissionError("You do not have access to this household.")
        household = self._household_repository.get_by_id(household_id=household_id)
        if household is None:
            raise HouseholdNotFoundError("Household not found.")
        if include_members:
            members = self._household_member_repository.list_by_household_id(household_id=household_id)
            return household, members
        return household, actor_membership

    def _require_active_household_member(
        self,
        *,
        household_id: str,
        member_id: str,
    ) -> HouseholdMember:
        member = self._household_member_repository.get_by_id(member_id=member_id)
        if member is None or member.household_id != household_id:
            raise HouseholdNotFoundError("Household member not found.")
        if member.status != HouseholdMemberStatus.ACTIVE:
            raise HouseholdValidationError("Household member is not active.")
        return member

    def _to_contribution_response(
        self,
        contribution: HouseholdBudgetContribution,
    ) -> HouseholdContributionResponse:
        return HouseholdContributionResponse(
            id=contribution.id,
            household_id=contribution.household_id,
            member_id=contribution.member_id,
            user_id=contribution.user_id,
            amount_minor=contribution.amount_minor,
            currency=contribution.currency,
            period_start=contribution.period_start,
            period_end=contribution.period_end,
            source=contribution.source,
            note=contribution.note,
            created_by_user_id=contribution.created_by_user_id,
            created_at=contribution.created_at,
        )

    def _notify(
        self,
        *,
        household_id: str,
        recipient_user_ids: list[str],
        title: str,
        message: str,
        focus: str,
        idempotency_key: str,
        email_subject: str,
        email_intro: str,
        details: dict[str, object] | None = None,
    ) -> None:
        if self._household_communication_service is None:
            return
        self._household_communication_service.notify(
            recipient_user_ids=recipient_user_ids,
            title=title,
            message=message,
            household_id=household_id,
            focus=focus,
            idempotency_key=idempotency_key,
            email_subject=email_subject,
            email_intro=email_intro,
            details=details,
        )

    def _list_recipient_user_ids(self, *, household_id: str) -> list[str]:
        return [
            member.user_id
            for member in self._household_member_repository.list_by_household_id(
                household_id=household_id
            )
        ]

    @staticmethod
    def _format_amount(currency: str, amount_minor: int) -> str:
        return f"{currency} {amount_minor / 100:.2f}"

    def _to_expense_response(self, expense: HouseholdSharedExpense) -> HouseholdExpenseResponse:
        return HouseholdExpenseResponse(
            id=expense.id,
            household_id=expense.household_id,
            recorded_by_user_id=expense.recorded_by_user_id,
            paid_by_member_id=expense.paid_by_member_id,
            expense_type=expense.expense_type,
            title=expense.title,
            description=expense.description,
            amount_minor=expense.amount_minor,
            currency=expense.currency,
            effective_date=expense.effective_date,
            linked_order_id=expense.linked_order_id,
            receipt_url=expense.receipt_url,
            receipt_source=expense.receipt_source,
            split_rule={
                "type": expense.split_rule.type,
                "weights": expense.split_rule.weights,
            },
            status=expense.status,
            created_at=expense.created_at,
            updated_at=expense.updated_at,
        )

    def _to_split_responses(
        self,
        splits: list[HouseholdExpenseSplit],
    ) -> list[HouseholdExpenseSplitResponse]:
        members = {
            member.id: member
            for member in self._household_member_repository.list_by_household_id(
                household_id=splits[0].household_id
            )
        } if splits else {}
        items: list[HouseholdExpenseSplitResponse] = []
        for split in splits:
            member = members.get(split.member_id)
            display_name = member.display_name if member is not None else split.member_id
            items.append(
                HouseholdExpenseSplitResponse(
                    member_id=split.member_id,
                    user_id=split.user_id,
                    display_name=display_name,
                    owed_amount_minor=split.owed_amount_minor,
                    paid_amount_minor=split.paid_amount_minor,
                    net_amount_minor=split.net_amount_minor,
                    currency=split.currency,
                    split_rule_type=split.split_rule_type,
                    created_at=split.created_at,
                )
            )
        return items
