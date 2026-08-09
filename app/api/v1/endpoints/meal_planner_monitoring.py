import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.dependencies import get_user_repository, require_platform_user
from app.models.user import User
from app.schemas.meal_planner_monitoring import (
    MealPlannerMonitoringEventResponse,
    MealPlannerMonitoringRunDetailResponse,
    MealPlannerMonitoringRunResponse,
)
from app.services.meal_planner_monitoring_service import meal_planner_monitoring_service

router = APIRouter(prefix="/monitoring/meal-planner", tags=["meal-planner-monitoring"])
logger = logging.getLogger(__name__)


def _extract_websocket_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    token = websocket.query_params.get("access_token")
    return token.strip() if token else None


def _ensure_enabled() -> None:
    if not get_settings().meal_planner_monitoring_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal planner monitoring is disabled.")


def _to_run_response(document: dict) -> MealPlannerMonitoringRunResponse:
    return MealPlannerMonitoringRunResponse(
        id=str(document["_id"]),
        user_id=str(document.get("user_id") or ""),
        trace_id=str(document["trace_id"]) if document.get("trace_id") is not None else None,
        request_type=str(document["request_type"]) if document.get("request_type") is not None else None,
        view_mode=str(document["view_mode"]) if document.get("view_mode") is not None else None,
        effective_date=str(document["effective_date"]) if document.get("effective_date") is not None else None,
        status=str(document.get("status") or "unknown"),
        root_step_id=str(document["root_step_id"]) if document.get("root_step_id") is not None else None,
        metadata=dict(document.get("metadata") or {}),
        event_count=int(document.get("event_count") or 0),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        completed_at=document.get("completed_at"),
        last_event_at=document.get("last_event_at"),
        last_step_key=str(document["last_step_key"]) if document.get("last_step_key") is not None else None,
        last_step_status=str(document["last_step_status"]) if document.get("last_step_status") is not None else None,
        summary=dict(document.get("summary") or {}),
    )


def _to_event_response(document: dict) -> MealPlannerMonitoringEventResponse:
    return MealPlannerMonitoringEventResponse(
        id=str(document["_id"]),
        run_id=str(document.get("run_id") or ""),
        user_id=str(document.get("user_id") or ""),
        trace_id=str(document["trace_id"]) if document.get("trace_id") is not None else None,
        event_kind=str(document.get("event_kind") or "log"),
        step_id=str(document.get("step_id") or ""),
        parent_step_id=str(document["parent_step_id"]) if document.get("parent_step_id") is not None else None,
        branch_key=str(document["branch_key"]) if document.get("branch_key") is not None else None,
        step_key=str(document.get("step_key") or ""),
        step_type=str(document.get("step_type") or "step"),
        status=str(document.get("status") or "unknown"),
        input=document.get("input"),
        output=document.get("output"),
        metrics=document.get("metrics"),
        error=document.get("error"),
        tags=document.get("tags"),
        created_at=document["created_at"],
    )


@router.get("/runs", response_model=list[MealPlannerMonitoringRunResponse], status_code=status.HTTP_200_OK)
def list_meal_planner_monitoring_runs(
    trace_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(require_platform_user),
) -> list[MealPlannerMonitoringRunResponse]:
    _ensure_enabled()
    runs = meal_planner_monitoring_service.list_runs(
        trace_id=trace_id.strip() if trace_id else None,
        user_id=user_id.strip() if user_id else None,
        limit=limit,
    )
    return [_to_run_response(item) for item in runs]


@router.get("/runs/{run_id}", response_model=MealPlannerMonitoringRunDetailResponse, status_code=status.HTTP_200_OK)
def get_meal_planner_monitoring_run(
    run_id: str,
    limit: int = Query(default=5000, ge=1, le=20000),
    current_user: User = Depends(require_platform_user),
) -> MealPlannerMonitoringRunDetailResponse:
    _ensure_enabled()
    run = meal_planner_monitoring_service.get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring run not found.")
    events = meal_planner_monitoring_service.list_events(
        run_id=run_id,
        limit=limit,
    )
    return MealPlannerMonitoringRunDetailResponse(
        run=_to_run_response(run),
        events=[_to_event_response(item) for item in events],
    )


@router.websocket("/ws")
async def meal_planner_monitoring_websocket(websocket: WebSocket) -> None:
    if not get_settings().meal_planner_monitoring_enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    token = _extract_websocket_token(websocket)
    client_host = websocket.client.host if websocket.client else "-"
    if not token:
        logger.warning("Meal planner monitoring websocket rejected missing_token client=%s", client_host)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        user_id = decode_access_token(token)
    except JWTError:
        logger.warning("Meal planner monitoring websocket rejected invalid_token client=%s", client_host)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = get_user_repository().find_by_id(user_id)
    if user is None:
        logger.warning("Meal planner monitoring websocket rejected unknown_user user_id=%s", user_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    run_ids = [
        value.strip()
        for value in (websocket.query_params.get("run_ids") or "").split(",")
        if value.strip()
    ]
    trace_ids = [
        value.strip()
        for value in (websocket.query_params.get("trace_ids") or "").split(",")
        if value.strip()
    ]
    await meal_planner_monitoring_service.connect(
        user_id=user.id,
        websocket=websocket,
        run_ids=run_ids,
        trace_ids=trace_ids,
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await meal_planner_monitoring_service.disconnect(websocket)
    except Exception:
        logger.exception("Meal planner monitoring websocket failed for user_id=%s", user.id)
        await meal_planner_monitoring_service.disconnect(websocket)
