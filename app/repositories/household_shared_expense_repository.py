from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.household import (
    HouseholdExpenseReceiptSource,
    HouseholdExpenseStatus,
    HouseholdExpenseType,
    HouseholdSharedExpense,
    HouseholdSplitRule,
    HouseholdSplitRuleType,
)


class HouseholdSharedExpenseRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create(
        self,
        *,
        household_id: str,
        recorded_by_user_id: str,
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
        split_rule_type: HouseholdSplitRuleType,
        status: HouseholdExpenseStatus,
    ) -> HouseholdSharedExpense:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "household_id": household_id,
            "recorded_by_user_id": recorded_by_user_id,
            "paid_by_member_id": paid_by_member_id,
            "expense_type": expense_type.value,
            "title": title,
            "description": description,
            "amount_minor": int(amount_minor),
            "currency": currency,
            "effective_date": _to_bson_day(effective_date),
            "linked_order_id": linked_order_id,
            "receipt_url": receipt_url,
            "receipt_source": receipt_source.value if receipt_source is not None else None,
            "split_rule": {
                "type": split_rule_type.value,
                "weights": [],
            },
            "status": status.value,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_id(self, *, expense_id: str) -> HouseholdSharedExpense | None:
        document = self._collection.find_one({"_id": expense_id})
        return None if document is None else self._to_model(document)

    def get_by_household_and_id(
        self,
        *,
        household_id: str,
        expense_id: str,
    ) -> HouseholdSharedExpense | None:
        document = self._collection.find_one({"_id": expense_id, "household_id": household_id})
        return None if document is None else self._to_model(document)

    def list_by_household_and_date_range(
        self,
        *,
        household_id: str,
        date_from: date,
        date_to: date,
    ) -> list[HouseholdSharedExpense]:
        documents = list(
            self._collection.find(
                {
                    "household_id": household_id,
                    "effective_date": {
                        "$gte": _to_bson_day(date_from),
                        "$lte": _to_bson_day(date_to),
                    },
                }
            ).sort([("effective_date", DESCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def list_linked_order_ids(self, *, household_id: str) -> set[str]:
        documents = self._collection.find(
            {"household_id": household_id, "linked_order_id": {"$ne": None}},
            {"linked_order_id": 1},
        )
        return {str(document["linked_order_id"]) for document in documents}

    def update_status(
        self,
        *,
        expense_id: str,
        status: HouseholdExpenseStatus,
    ) -> HouseholdSharedExpense | None:
        self._collection.update_one(
            {"_id": expense_id},
            {
                "$set": {
                    "status": status.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return self.get_by_id(expense_id=expense_id)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> HouseholdSharedExpense:
        split_rule = dict(document.get("split_rule") or {})
        return HouseholdSharedExpense(
            id=str(document["_id"]),
            household_id=str(document["household_id"]),
            recorded_by_user_id=str(document["recorded_by_user_id"]),
            paid_by_member_id=str(document["paid_by_member_id"]),
            expense_type=HouseholdExpenseType(
                str(document.get("expense_type") or HouseholdExpenseType.GROCERY.value)
            ),
            title=str(document.get("title") or ""),
            description=(
                str(document["description"])
                if document.get("description") not in (None, "")
                else None
            ),
            amount_minor=int(document.get("amount_minor") or 0),
            currency=str(document.get("currency") or "GBP"),
            effective_date=_from_bson_day(document["effective_date"]),
            linked_order_id=(
                str(document["linked_order_id"])
                if document.get("linked_order_id") not in (None, "")
                else None
            ),
            receipt_url=(
                str(document["receipt_url"])
                if document.get("receipt_url") not in (None, "")
                else None
            ),
            receipt_source=(
                HouseholdExpenseReceiptSource(str(document["receipt_source"]))
                if document.get("receipt_source") not in (None, "")
                else None
            ),
            split_rule=HouseholdSplitRule(
                type=HouseholdSplitRuleType(
                    str(split_rule.get("type") or HouseholdSplitRuleType.EQUAL.value)
                ),
                weights=list(split_rule.get("weights") or []),
            ),
            status=HouseholdExpenseStatus(
                str(document.get("status") or HouseholdExpenseStatus.DRAFT.value)
            ),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )


def _to_bson_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _from_bson_day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
