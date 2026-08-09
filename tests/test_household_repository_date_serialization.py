from __future__ import annotations

from datetime import date, datetime
import unittest

from app.models.household import (
    HouseholdContributionSource,
    HouseholdExpenseStatus,
    HouseholdExpenseType,
    HouseholdSplitRuleType,
)
from app.repositories.household_budget_contribution_repository import (
    HouseholdBudgetContributionRepository,
)
from app.repositories.household_shared_expense_repository import (
    HouseholdSharedExpenseRepository,
)


class _Cursor:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self._documents = documents

    def sort(self, *_: object, **__: object) -> list[dict[str, object]]:
        return self._documents


class _RecordingCollection:
    def __init__(self) -> None:
        self.last_inserted: dict[str, object] | None = None
        self.last_find_filter: dict[str, object] | None = None
        self.next_find_documents: list[dict[str, object]] = []

    def insert_one(self, document: dict[str, object]) -> None:
        self.last_inserted = document

    def find(self, query: dict[str, object]) -> _Cursor:
        self.last_find_filter = query
        return _Cursor(self.next_find_documents)


class HouseholdRepositoryDateSerializationTests(unittest.TestCase):
    def test_contribution_repository_serializes_dates_to_datetimes(self) -> None:
        collection = _RecordingCollection()
        repository = HouseholdBudgetContributionRepository(collection)  # type: ignore[arg-type]

        contribution = repository.create(
            household_id="household-1",
            member_id="member-1",
            user_id="user-1",
            amount_minor=3000,
            currency="GBP",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            source=HouseholdContributionSource.MANUAL,
            note="Weekly top-up",
            created_by_user_id="user-1",
        )

        inserted = collection.last_inserted
        self.assertIsNotNone(inserted)
        self.assertIsInstance(inserted["period_start"], datetime)  # type: ignore[index]
        self.assertIsInstance(inserted["period_end"], datetime)  # type: ignore[index]
        self.assertEqual(date(2026, 7, 13), contribution.period_start)
        self.assertEqual(date(2026, 7, 19), contribution.period_end)

    def test_contribution_repository_serializes_date_filters_to_datetimes(self) -> None:
        collection = _RecordingCollection()
        collection.next_find_documents = [
            {
                "_id": "contribution-1",
                "household_id": "household-1",
                "member_id": "member-1",
                "user_id": "user-1",
                "amount_minor": 3000,
                "currency": "GBP",
                "period_start": datetime(2026, 7, 13),
                "period_end": datetime(2026, 7, 19),
                "source": "manual",
                "note": "Weekly top-up",
                "created_by_user_id": "user-1",
                "created_at": datetime(2026, 7, 18, 12, 0, 0),
            }
        ]
        repository = HouseholdBudgetContributionRepository(collection)  # type: ignore[arg-type]

        items = repository.list_by_household_and_period(
            household_id="household-1",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
        )

        self.assertEqual(1, len(items))
        self.assertIsInstance(
            collection.last_find_filter["period_start"]["$gte"],  # type: ignore[index]
            datetime,
        )
        self.assertIsInstance(
            collection.last_find_filter["period_end"]["$lte"],  # type: ignore[index]
            datetime,
        )
        self.assertEqual(date(2026, 7, 13), items[0].period_start)
        self.assertEqual(date(2026, 7, 19), items[0].period_end)

    def test_expense_repository_serializes_dates_to_datetimes(self) -> None:
        collection = _RecordingCollection()
        repository = HouseholdSharedExpenseRepository(collection)  # type: ignore[arg-type]

        expense = repository.create(
            household_id="household-1",
            recorded_by_user_id="user-1",
            paid_by_member_id="member-1",
            expense_type=HouseholdExpenseType.GROCERY,
            title="Groceries",
            description="Weekend shop",
            amount_minor=4875,
            currency="GBP",
            effective_date=date(2026, 7, 18),
            linked_order_id=None,
            split_rule_type=HouseholdSplitRuleType.EQUAL,
            status=HouseholdExpenseStatus.POSTED,
        )

        inserted = collection.last_inserted
        self.assertIsNotNone(inserted)
        self.assertIsInstance(inserted["effective_date"], datetime)  # type: ignore[index]
        self.assertEqual(date(2026, 7, 18), expense.effective_date)

    def test_expense_repository_serializes_date_filters_to_datetimes(self) -> None:
        collection = _RecordingCollection()
        collection.next_find_documents = [
            {
                "_id": "expense-1",
                "household_id": "household-1",
                "recorded_by_user_id": "user-1",
                "paid_by_member_id": "member-1",
                "expense_type": "grocery",
                "title": "Groceries",
                "description": "Weekend shop",
                "amount_minor": 4875,
                "currency": "GBP",
                "effective_date": datetime(2026, 7, 18),
                "linked_order_id": None,
                "split_rule": {"type": "equal", "weights": []},
                "status": "posted",
                "created_at": datetime(2026, 7, 18, 12, 0, 0),
                "updated_at": datetime(2026, 7, 18, 12, 0, 0),
            }
        ]
        repository = HouseholdSharedExpenseRepository(collection)  # type: ignore[arg-type]

        items = repository.list_by_household_and_date_range(
            household_id="household-1",
            date_from=date(2026, 7, 13),
            date_to=date(2026, 7, 19),
        )

        self.assertEqual(1, len(items))
        self.assertIsInstance(
            collection.last_find_filter["effective_date"]["$gte"],  # type: ignore[index]
            datetime,
        )
        self.assertIsInstance(
            collection.last_find_filter["effective_date"]["$lte"],  # type: ignore[index]
            datetime,
        )
        self.assertEqual(date(2026, 7, 18), items[0].effective_date)


if __name__ == "__main__":
    unittest.main()
