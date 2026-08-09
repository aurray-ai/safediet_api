from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING
from pymongo.collection import Collection

from app.models.household import HouseholdExpenseSplit, HouseholdSplitRuleType


class HouseholdExpenseSplitRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def replace_for_expense(
        self,
        *,
        household_id: str,
        expense_id: str,
        currency: str,
        split_rule_type: HouseholdSplitRuleType,
        rows: list[dict[str, Any]],
    ) -> list[HouseholdExpenseSplit]:
        self._collection.delete_many({"expense_id": expense_id})
        now = datetime.now(timezone.utc)
        documents: list[dict[str, Any]] = []
        for row in rows:
            documents.append(
                {
                    "_id": uuid4().hex,
                    "household_id": household_id,
                    "expense_id": expense_id,
                    "member_id": str(row["member_id"]),
                    "user_id": str(row["user_id"]),
                    "owed_amount_minor": int(row["owed_amount_minor"]),
                    "paid_amount_minor": int(row["paid_amount_minor"]),
                    "net_amount_minor": int(row["net_amount_minor"]),
                    "currency": currency,
                    "split_rule_type": split_rule_type.value,
                    "created_at": now,
                }
            )
        if documents:
            self._collection.insert_many(documents)
        return [self._to_model(document) for document in documents]

    def list_by_expense(self, *, expense_id: str) -> list[HouseholdExpenseSplit]:
        documents = list(
            self._collection.find({"expense_id": expense_id}).sort([("member_id", ASCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def list_by_expense_ids(self, *, expense_ids: list[str]) -> list[HouseholdExpenseSplit]:
        if not expense_ids:
            return []
        documents = list(
            self._collection.find({"expense_id": {"$in": expense_ids}}).sort(
                [("expense_id", ASCENDING), ("member_id", ASCENDING)]
            )
        )
        return [self._to_model(document) for document in documents]

    @staticmethod
    def _to_model(document: dict[str, Any]) -> HouseholdExpenseSplit:
        return HouseholdExpenseSplit(
            id=str(document["_id"]),
            household_id=str(document["household_id"]),
            expense_id=str(document["expense_id"]),
            member_id=str(document["member_id"]),
            user_id=str(document["user_id"]),
            owed_amount_minor=int(document.get("owed_amount_minor") or 0),
            paid_amount_minor=int(document.get("paid_amount_minor") or 0),
            net_amount_minor=int(document.get("net_amount_minor") or 0),
            currency=str(document.get("currency") or "GBP"),
            split_rule_type=HouseholdSplitRuleType(
                str(document.get("split_rule_type") or HouseholdSplitRuleType.EQUAL.value)
            ),
            created_at=document["created_at"],
        )
