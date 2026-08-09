from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.models.household import HouseholdBudgetContribution, HouseholdContributionSource


class HouseholdBudgetContributionRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create(
        self,
        *,
        household_id: str,
        member_id: str,
        user_id: str,
        amount_minor: int,
        currency: str,
        period_start: date,
        period_end: date,
        source: HouseholdContributionSource,
        note: str | None,
        created_by_user_id: str,
    ) -> HouseholdBudgetContribution:
        document = {
            "_id": uuid4().hex,
            "household_id": household_id,
            "member_id": member_id,
            "user_id": user_id,
            "amount_minor": int(amount_minor),
            "currency": currency,
            "period_start": _to_bson_day(period_start),
            "period_end": _to_bson_day(period_end),
            "source": source.value,
            "note": note,
            "created_by_user_id": created_by_user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def list_by_household_and_period(
        self,
        *,
        household_id: str,
        period_start: date,
        period_end: date,
    ) -> list[HouseholdBudgetContribution]:
        documents = list(
            self._collection.find(
                {
                    "household_id": household_id,
                    "period_start": {"$gte": _to_bson_day(period_start)},
                    "period_end": {"$lte": _to_bson_day(period_end)},
                }
            ).sort([("created_at", DESCENDING), ("_id", DESCENDING)])
        )
        return [self._to_model(document) for document in documents]

    def sum_by_household_and_period(
        self,
        *,
        household_id: str,
        period_start: date,
        period_end: date,
    ) -> int:
        pipeline = [
            {
                "$match": {
                    "household_id": household_id,
                    "period_start": {"$gte": _to_bson_day(period_start)},
                    "period_end": {"$lte": _to_bson_day(period_end)},
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$amount_minor"}}},
        ]
        rows = list(self._collection.aggregate(pipeline))
        if not rows:
            return 0
        return int(rows[0].get("total") or 0)

    def member_totals_by_household_and_period(
        self,
        *,
        household_id: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, int]:
        pipeline = [
            {
                "$match": {
                    "household_id": household_id,
                    "period_start": {"$gte": _to_bson_day(period_start)},
                    "period_end": {"$lte": _to_bson_day(period_end)},
                }
            },
            {"$group": {"_id": "$member_id", "total": {"$sum": "$amount_minor"}}},
            {"$sort": {"_id": ASCENDING}},
        ]
        return {
            str(row["_id"]): int(row.get("total") or 0)
            for row in self._collection.aggregate(pipeline)
        }

    @staticmethod
    def _to_model(document: dict[str, Any]) -> HouseholdBudgetContribution:
        return HouseholdBudgetContribution(
            id=str(document["_id"]),
            household_id=str(document["household_id"]),
            member_id=str(document["member_id"]),
            user_id=str(document["user_id"]),
            amount_minor=int(document.get("amount_minor") or 0),
            currency=str(document.get("currency") or "GBP"),
            period_start=_from_bson_day(document["period_start"]),
            period_end=_from_bson_day(document["period_end"]),
            source=HouseholdContributionSource(
                str(document.get("source") or HouseholdContributionSource.MANUAL.value)
            ),
            note=(
                str(document["note"])
                if document.get("note") not in (None, "")
                else None
            ),
            created_by_user_id=str(document["created_by_user_id"]),
            created_at=document["created_at"],
        )


def _to_bson_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _from_bson_day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
