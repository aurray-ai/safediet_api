from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.household import (
    Household,
    HouseholdBudgetPeriod,
    HouseholdBudgetProfile,
    HouseholdSplitRule,
    HouseholdSplitRuleType,
    HouseholdStatus,
)


class HouseholdRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

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
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "owner_user_id": owner_user_id,
            "name": name,
            "status": HouseholdStatus.ACTIVE.value,
            "currency": currency,
            "planning_mode": "household",
            "budget_profile": {
                "period": budget_period.value,
                "target_amount_minor": int(target_amount_minor),
            },
            "default_split_rule": {
                "type": split_rule_type.value,
                "weights": [],
            },
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_by_id(self, *, household_id: str) -> Household | None:
        document = self._collection.find_one({"_id": household_id})
        return None if document is None else self._to_model(document)

    def list_by_ids(self, *, household_ids: list[str]) -> list[Household]:
        if not household_ids:
            return []
        documents = list(self._collection.find({"_id": {"$in": household_ids}}))
        return [self._to_model(document) for document in documents]

    def get_active_by_owner_user_id(self, *, owner_user_id: str) -> Household | None:
        document = self._collection.find_one(
            {
                "owner_user_id": owner_user_id,
                "status": HouseholdStatus.ACTIVE.value,
            }
        )
        return None if document is None else self._to_model(document)

    def update(
        self,
        *,
        household_id: str,
        name: str | None = None,
        target_amount_minor: int | None = None,
        budget_period: HouseholdBudgetPeriod | None = None,
        split_rule_type: HouseholdSplitRuleType | None = None,
    ) -> Household | None:
        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if name is not None:
            updates["name"] = name
        if target_amount_minor is not None:
            updates["budget_profile.target_amount_minor"] = int(target_amount_minor)
        if budget_period is not None:
            updates["budget_profile.period"] = budget_period.value
        if split_rule_type is not None:
            updates["default_split_rule.type"] = split_rule_type.value

        self._collection.update_one({"_id": household_id}, {"$set": updates})
        return self.get_by_id(household_id=household_id)

    def archive(self, *, household_id: str) -> Household | None:
        self._collection.update_one(
            {"_id": household_id},
            {
                "$set": {
                    "status": HouseholdStatus.ARCHIVED.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return self.get_by_id(household_id=household_id)

    @staticmethod
    def _to_model(document: dict[str, Any]) -> Household:
        budget_profile = dict(document.get("budget_profile") or {})
        default_split_rule = dict(document.get("default_split_rule") or {})
        return Household(
            id=str(document["_id"]),
            owner_user_id=str(document["owner_user_id"]),
            name=str(document.get("name") or ""),
            status=HouseholdStatus(str(document.get("status") or HouseholdStatus.ACTIVE.value)),
            currency=str(document.get("currency") or "GBP"),
            planning_mode=str(document.get("planning_mode") or "household"),
            budget_profile=HouseholdBudgetProfile(
                period=HouseholdBudgetPeriod(
                    str(budget_profile.get("period") or HouseholdBudgetPeriod.WEEKLY.value)
                ),
                target_amount_minor=int(budget_profile.get("target_amount_minor") or 0),
            ),
            default_split_rule=HouseholdSplitRule(
                type=HouseholdSplitRuleType(
                    str(default_split_rule.get("type") or HouseholdSplitRuleType.EQUAL.value)
                ),
                weights=list(default_split_rule.get("weights") or []),
            ),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
