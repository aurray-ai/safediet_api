import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.dependencies import get_current_user, get_meal_conversation_service, get_notification_service
from app.models.user import User
from app.schemas.meal_conversation import (
    MealPlannerDraftSaveRequest,
    MealPlannerRequest,
    MealPlannerRunAcceptedResponse,
    MealPlannerRunResponse,
)
from app.schemas.saved_meal_plan import SavedMealPlanResponse
from app.services.meal_conversation_service import MealConversationService
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/meal-planning/planner", tags=["meal-planning"])
logger = logging.getLogger(__name__)


def _to_saved_plan_response(saved_plan) -> SavedMealPlanResponse:
    return SavedMealPlanResponse(
        id=saved_plan.id,
        title=saved_plan.title,
        status=saved_plan.status,
        view_mode=saved_plan.view_mode,
        plan_scope=saved_plan.plan_scope,
        effective_date=saved_plan.effective_date,
        week_start=saved_plan.week_start,
        week_end=saved_plan.week_end,
        day_index=saved_plan.day_index,
        parent_saved_plan_id=saved_plan.parent_saved_plan_id,
        source_saved_plan_id=saved_plan.source_saved_plan_id,
        linked_day_plan_ids=list(saved_plan.linked_day_plan_ids),
        meal_type=saved_plan.meal_type,
        country_code=saved_plan.country_code,
        planned_meals=list(saved_plan.planned_meals),
        plan_payload=dict(saved_plan.plan_payload),
        requested_culture=saved_plan.requested_culture,
        user_goal=saved_plan.user_goal,
        source_snapshot_id=saved_plan.source_snapshot_id,
        source_conversation_id=saved_plan.source_conversation_id,
        agent_type=saved_plan.agent_type,
        created_at=saved_plan.created_at,
        updated_at=saved_plan.updated_at,
    )


async def _process_weekly_plan_generation(
    *,
    meal_conversation_service: MealConversationService,
    current_user: User,
    payload: MealPlannerRequest,
    trace_id: str | None,
) -> None:
    await meal_conversation_service.generate_weekly_plan_with_progress(
        current_user=current_user,
        payload=payload,
        trace_id=trace_id,
    )


@router.post("", response_model=MealPlannerRunResponse | MealPlannerRunAcceptedResponse, status_code=status.HTTP_200_OK)
def run_meal_planner(
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    payload: MealPlannerRequest,
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
) -> MealPlannerRunResponse | MealPlannerRunAcceptedResponse:
    trace_id = request.headers.get("x-meal-trace-id", "")
    started_at = time.perf_counter()
    meal_conversation_service.assert_plan_generation_allowed(
        current_user=current_user,
        payload=payload,
    )
    if payload.request_type in {"generate_week_plan", "generate_multi_day_plan"}:
        background_tasks.add_task(
            _process_weekly_plan_generation,
            meal_conversation_service=meal_conversation_service,
            current_user=current_user,
            payload=payload,
            trace_id=trace_id or None,
        )
        logger.info(
            "planner.endpoint.run.accepted trace_id=%s user_id=%s request_type=%s slots=%s duration_ms=%s",
            trace_id or "-",
            current_user.id,
            payload.request_type,
            ",".join(slot.value for slot in payload.slots),
            int((time.perf_counter() - started_at) * 1000),
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return MealPlannerRunAcceptedResponse(
            trace_id=trace_id or "",
            assistant_text=(
                "Your selected dates plan is being prepared."
                if payload.request_type == "generate_multi_day_plan"
                else "Your weekly plan is being prepared."
            ),
            request_type=payload.request_type,
            view_mode="week",
            effective_date=payload.effective_date,
        )

    result = meal_conversation_service.plan_meals(
        current_user=current_user,
        payload=payload,
        trace_id=trace_id or None,
    )
    logger.info(
        "planner.endpoint.run trace_id=%s user_id=%s request_type=%s slots=%s duration_ms=%s turn_mode=%s planned_meals=%s",
        trace_id or "-",
        current_user.id,
        payload.request_type,
        ",".join(slot.value for slot in payload.slots),
        int((time.perf_counter() - started_at) * 1000),
        result.turn_result.turn_mode,
        len(result.turn_result.planned_meals),
    )
    return MealPlannerRunResponse(
        assistant_text=result.turn_result.assistant_text,
        turn_mode=result.turn_result.turn_mode,
        planned_meals=result.turn_result.planned_meals,
        requested_culture=result.turn_result.requested_culture,
        bundle_summary=dict(result.turn_result.metadata.get("bundle_summary") or {}),
        inventory_summary=dict(result.turn_result.metadata.get("inventory_summary") or {}),
        cart_summary=dict(result.turn_result.metadata.get("cart_summary") or {}),
        ui_blocks=result.turn_result.ui_blocks,
        quick_actions=result.turn_result.quick_actions,
        metadata=result.turn_result.metadata,
        prepared_action_payload=result.prepared_action_payload,
        semantic_queries=[
            {
                "slot": item.slot,
                "semantic_query": item.semantic_query,
                "candidate_count": item.candidate_count,
            }
            for item in result.semantic_queries
        ],
    )


@router.post("/drafts/save", response_model=SavedMealPlanResponse, status_code=status.HTTP_200_OK)
async def save_meal_planner_draft(
    payload: MealPlannerDraftSaveRequest,
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
    notification_service: NotificationService = Depends(get_notification_service),
) -> SavedMealPlanResponse:
    result = meal_conversation_service.save_meal_planner_draft_result(
        current_user=current_user,
        payload=payload,
    )
    notification_event = dict(result.notification_event or {})
    if notification_event.get("type") == "meal_plan_approved":
        await notification_service.create_and_deliver_meal_plan_approved_notification(
            user_id=current_user.id,
            conversation_id=str(notification_event.get("conversation_id") or "direct-planner"),
            saved_plan_id=str(notification_event.get("saved_plan_id") or result.saved_plan.id),
            snapshot_id=str(notification_event.get("snapshot_id") or ""),
            view_mode=str(notification_event.get("view_mode") or result.saved_plan.view_mode),
            period_label=str(notification_event.get("period_label") or "").strip() or None,
            message_id=None,
            ui_block_id=str(notification_event.get("ui_block_id") or payload.ui_block.id) or None,
        )
    return _to_saved_plan_response(result.saved_plan)
