import argparse
from datetime import date
from typing import Any

from app.db.mongodb import mongo_manager
from app.models.grocery import CountryCode
from app.models.meal import MealType
from app.models.saved_meal_plan import SavedMealPlan
from app.repositories.user_meal_usage_repository import UserMealUsageRepository
from app.services.goal_target_service import GoalTargetService
from app.services.user_meal_usage_service import UserMealUsageService


def build_saved_plan(document: dict[str, Any]) -> SavedMealPlan:
    meal_type = document.get("meal_type")
    country_code = document.get("country_code")
    effective_date = document.get("effective_date")
    return SavedMealPlan(
        id=str(document["_id"]),
        user_id=str(document["user_id"]),
        title=str(document.get("title") or "Meal Plan"),
        status=str(document.get("status") or "saved"),
        view_mode=str(document.get("view_mode") or "day"),
        plan_scope=str(document["plan_scope"]) if document.get("plan_scope") else None,
        effective_date=date.fromisoformat(str(effective_date)) if effective_date else None,
        week_start=(
            date.fromisoformat(str(document["week_start"]))
            if document.get("week_start")
            else None
        ),
        week_end=(
            date.fromisoformat(str(document["week_end"]))
            if document.get("week_end")
            else None
        ),
        day_index=int(document["day_index"]) if document.get("day_index") is not None else None,
        parent_saved_plan_id=(
            str(document["parent_saved_plan_id"])
            if document.get("parent_saved_plan_id")
            else None
        ),
        source_saved_plan_id=(
            str(document["source_saved_plan_id"])
            if document.get("source_saved_plan_id")
            else None
        ),
        linked_day_plan_ids=[str(item) for item in list(document.get("linked_day_plan_ids") or [])],
        meal_type=MealType(str(meal_type)) if meal_type else None,
        country_code=CountryCode(str(country_code)) if country_code else None,
        planned_meals=list(document.get("planned_meals") or []),
        plan_payload=dict(document.get("plan_payload") or {}),
        requested_culture=str(document["requested_culture"]) if document.get("requested_culture") else None,
        user_goal=str(document["user_goal"]) if document.get("user_goal") else None,
        source_snapshot_id=str(document["source_snapshot_id"]),
        source_conversation_id=str(document["source_conversation_id"]),
        agent_type=str(document.get("agent_type") or "meal_coordinator"),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill normalized user meal usage from saved day plans.")
    parser.add_argument("--user-id", default=None, help="Optional user id filter.")
    args = parser.parse_args()

    mongo_manager.connect()
    try:
        usage_service = UserMealUsageService(
            user_meal_usage_repository=UserMealUsageRepository(
                mongo_manager.user_meal_usage_entries_collection()
            ),
            goal_target_service=GoalTargetService(),
        )
        query: dict[str, Any] = {"view_mode": "day"}
        if args.user_id:
            query["user_id"] = args.user_id

        processed = 0
        synced_entries = 0
        for document in mongo_manager.saved_meal_plans_collection().find(query):
            saved_plan = build_saved_plan(document)
            synced_entries += len(usage_service.sync_saved_day_plan(saved_plan=saved_plan))
            processed += 1

        print(
            f"Processed {processed} saved day plans and wrote {synced_entries} usage entries."
        )
    finally:
        mongo_manager.close()


if __name__ == "__main__":
    main()
