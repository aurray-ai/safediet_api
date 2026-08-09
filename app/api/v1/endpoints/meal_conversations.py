import logging
import time
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.dependencies import (
    get_current_user,
    get_goal_target_service,
    get_grocery_repository,
    get_meal_conversation_repository,
    get_meal_conversation_service,
    get_meal_repository,
    get_notification_repository,
    get_saved_meal_plan_repository,
    get_user_meal_usage_service,
    get_user_meal_usage_repository,
    get_user_repository,
)
from app.models.meal import MealType
from app.models.user import User
from app.schemas.meal_conversation import (
    ConversationMessagesResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    CurrentConversationResponse,
    SendConversationMessageAcceptedResponse,
    SendConversationMessageRequest,
    SendConversationMessageResponse,
)
from app.services.meal_conversation_service import (
    MealConversationNotFoundError,
    MealConversationTurnDeliveryError,
    MealConversationService,
)
from app.services.notification_service import NotificationService
from app.services.realtime_delivery_service import realtime_delivery_service

router = APIRouter(prefix="/meal-planning/conversations", tags=["meal-planning"])
logger = logging.getLogger(__name__)


def _json_payload(value: object) -> str:
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except Exception:
        return str(value)


def _build_meal_conversation_service() -> MealConversationService:
    return get_meal_conversation_service(
        user_repository=get_user_repository(),
        meal_conversation_repository=get_meal_conversation_repository(),
        meal_repository=get_meal_repository(),
        grocery_repository=get_grocery_repository(),
        saved_meal_plan_repository=get_saved_meal_plan_repository(),
        user_meal_usage_service=get_user_meal_usage_service(
            user_meal_usage_repository=get_user_meal_usage_repository(),
            goal_target_service=get_goal_target_service(),
        ),
    )


def _build_notification_service() -> NotificationService:
    return NotificationService(
        notification_repository=get_notification_repository(),
        saved_meal_plan_repository=get_saved_meal_plan_repository(),
    )


def _friendly_delivery_error_message(*, quick_action_type: str | None, exc: Exception | None = None) -> str:
    if quick_action_type == "save_meal_plan":
        return "We couldn't save this meal plan right now. Please try again."

    if isinstance(exc, MealConversationTurnDeliveryError):
        return str(exc.message or "We couldn't finish that planner request right now. Please try again.")

    if isinstance(exc, MealConversationNotFoundError):
        return "Conversation not found."

    return "We couldn't finish that planner request right now. Please try again."


async def _process_message_delivery(
    *,
    user_id: str,
    conversation_id: str,
    payload_data: dict[str, object],
    trace_id: str | None,
) -> None:
    user = get_user_repository().find_by_id(user_id)
    if user is None:
        logger.warning(
            "planner.send_message.background.user_not_found trace_id=%s conversation_id=%s user_id=%s",
            trace_id or "-",
            conversation_id,
            user_id,
        )
        return

    payload = SendConversationMessageRequest.model_validate(payload_data)
    service = _build_meal_conversation_service()
    active_subscribers = await realtime_delivery_service.active_subscriber_count(
        user_id=user_id,
        location="ios.conversations",
    )
    success_channels = ["websocket"] if active_subscribers > 0 else ["push"]
    try:
        response = service.complete_message(
            current_user=user,
            conversation_id=conversation_id,
            payload=payload,
            trace_id=trace_id,
        )
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="conversation",
            location="ios.conversations",
            payload=response.model_dump(mode="json"),
            push_payload={
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "status": "completed",
            },
            trace_id=trace_id,
            conversation_id=conversation_id,
            status="completed",
            channels=success_channels,
            push_alert_title="Plan ready",
            push_alert_body="Your planner response is ready.",
            metadata={"source": "meal_conversation"},
        )
        notification_event = dict(response.assistant_message.metadata.get("notification_event") or {})
        if notification_event.get("type") == "meal_plan_approved":
            try:
                notification_service = _build_notification_service()
                await notification_service.create_and_deliver_meal_plan_approved_notification(
                    user_id=user_id,
                    conversation_id=str(notification_event.get("conversation_id") or conversation_id),
                    saved_plan_id=str(notification_event.get("saved_plan_id") or ""),
                    snapshot_id=str(notification_event.get("snapshot_id") or ""),
                    view_mode=str(notification_event.get("view_mode") or "day"),
                    period_label=str(notification_event.get("period_label") or "").strip() or None,
                    message_id=response.assistant_message.id,
                    ui_block_id=str(notification_event.get("ui_block_id") or "") or None,
                )
            except Exception:
                logger.exception(
                    "planner.send_message.background.approved_notification.failed trace_id=%s conversation_id=%s",
                    trace_id or "-",
                    conversation_id,
                )
    except MealConversationNotFoundError:
        failure_message = _friendly_delivery_error_message(
            quick_action_type=payload.quick_action_type,
            exc=MealConversationNotFoundError(),
        )
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="conversation",
            location="ios.conversations",
            payload={
                "error_message": failure_message,
                "request_kind": payload.quick_action_type or "message",
            },
            push_payload={
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "status": "failed",
                "error_message": failure_message,
                "request_kind": payload.quick_action_type or "message",
            },
            trace_id=trace_id,
            conversation_id=conversation_id,
            status="failed",
            channels=["websocket", "push"],
            push_alert_title="Planner update failed",
            push_alert_body="We could not finish that planner request.",
            metadata={"source": "meal_conversation", "reason": "conversation_not_found"},
        )
    except MealConversationTurnDeliveryError as exc:
        failure_message = _friendly_delivery_error_message(
            quick_action_type=payload.quick_action_type,
            exc=exc,
        )
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="conversation",
            location="ios.conversations",
            payload={
                "error_message": failure_message,
                "request_kind": payload.quick_action_type or "message",
                "issue": exc.issue,
            },
            push_payload={
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "status": "failed",
                "error_message": failure_message,
                "request_kind": payload.quick_action_type or "message",
                "issue": exc.issue,
            },
            trace_id=trace_id,
            conversation_id=conversation_id,
            status="failed",
            channels=["websocket", "push"],
            push_alert_title="Planner update failed",
            push_alert_body="We could not finish that planner request.",
            metadata={"source": "meal_conversation", "reason": exc.issue or "turn_delivery_failed"},
        )
    except Exception as exc:
        logger.exception(
            "planner.send_message.background.failed trace_id=%s conversation_id=%s",
            trace_id or "-",
            conversation_id,
        )
        failure_message = _friendly_delivery_error_message(
            quick_action_type=payload.quick_action_type,
            exc=exc,
        )
        await realtime_delivery_service.deliver(
            user_id=user_id,
            delivery_type="conversation",
            location="ios.conversations",
            payload={
                "error_message": failure_message,
                "request_kind": payload.quick_action_type or "message",
            },
            push_payload={
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "status": "failed",
                "error_message": failure_message,
                "request_kind": payload.quick_action_type or "message",
            },
            trace_id=trace_id,
            conversation_id=conversation_id,
            status="failed",
            channels=["websocket", "push"],
            push_alert_title="Planner update failed",
            push_alert_body="We could not finish that planner request.",
            metadata={"source": "meal_conversation", "reason": "unhandled_exception"},
        )


@router.post("", response_model=CreateConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: Request,
    payload: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
) -> CreateConversationResponse:
    trace_id = request.headers.get("x-meal-trace-id", "")
    started_at = time.perf_counter()
    logger.debug(
        "planner.create_conversation.received trace_id=%s user_id=%s payload=%s",
        trace_id or "-",
        current_user.id,
        _json_payload(payload.model_dump(mode="json")),
    )
    response = meal_conversation_service.start_conversation(
        current_user=current_user,
        opening_message=payload.opening_message,
        meal_type=payload.meal_type,
        country_code=payload.country_code,
    )
    logger.debug(
        "planner.create_conversation.completed trace_id=%s user_id=%s duration_ms=%s response=%s",
        trace_id or "-",
        current_user.id,
        int((time.perf_counter() - started_at) * 1000),
        _json_payload(response.model_dump(mode="json")),
    )
    return response


@router.get("/current", response_model=CurrentConversationResponse, status_code=status.HTTP_200_OK)
def get_current_conversation(
    request: Request,
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
) -> CurrentConversationResponse:
    trace_id = request.headers.get("x-meal-trace-id", "")
    started_at = time.perf_counter()
    logger.info(
        "planner.get_current.received trace_id=%s user_id=%s",
        trace_id or "-",
        current_user.id,
    )
    response = meal_conversation_service.get_current_conversation(current_user=current_user)
    logger.debug(
        "planner.get_current.completed trace_id=%s user_id=%s duration_ms=%s response=%s",
        trace_id or "-",
        current_user.id,
        int((time.perf_counter() - started_at) * 1000),
        _json_payload(response.model_dump(mode="json")),
    )
    return response


@router.get("/{conversation_id}", response_model=ConversationSummaryResponse, status_code=status.HTTP_200_OK)
def get_conversation(
    request: Request,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
) -> ConversationSummaryResponse:
    trace_id = request.headers.get("x-meal-trace-id", "")
    started_at = time.perf_counter()
    logger.info(
        "planner.get_conversation.received trace_id=%s conversation_id=%s user_id=%s",
        trace_id or "-",
        conversation_id,
        current_user.id,
    )
    try:
        response = meal_conversation_service.get_conversation(
            current_user=current_user,
            conversation_id=conversation_id,
        )
        logger.debug(
            "planner.get_conversation.completed trace_id=%s conversation_id=%s duration_ms=%s response=%s",
            trace_id or "-",
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            _json_payload(response.model_dump(mode="json")),
        )
        return response
    except MealConversationNotFoundError as exc:
        logger.warning(
            "planner.get_conversation.not_found trace_id=%s conversation_id=%s duration_ms=%s response=%s",
            trace_id or "-",
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            _json_payload({"detail": "Conversation not found."}),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.") from exc


@router.post(
    "/{conversation_id}/messages",
    response_model=SendConversationMessageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def send_message(
    background_tasks: BackgroundTasks,
    request: Request,
    conversation_id: str,
    payload: SendConversationMessageRequest,
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
) -> SendConversationMessageAcceptedResponse:
    trace_id = request.headers.get("x-meal-trace-id", "")
    started_at = time.perf_counter()
    logger.debug(
        "planner.send_message.received trace_id=%s conversation_id=%s user_id=%s text_len=%s quick_action_type=%s quick_action_id=%s payload=%s",
        trace_id or "-",
        conversation_id,
        current_user.id,
        len((payload.text or "").strip()),
        payload.quick_action_type or "-",
        payload.quick_action_id or "-",
        _json_payload(payload.model_dump(mode="json")),
    )
    try:
        response = meal_conversation_service.accept_message(
            current_user=current_user,
            conversation_id=conversation_id,
            payload=payload,
            trace_id=trace_id or None,
        )
        background_tasks.add_task(
            _process_message_delivery,
            user_id=current_user.id,
            conversation_id=conversation_id,
            payload_data=payload.model_dump(mode="json"),
            trace_id=trace_id or None,
        )
        logger.debug(
            "planner.send_message.accepted trace_id=%s conversation_id=%s duration_ms=%s user_message_id=%s response=%s",
            trace_id or "-",
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            response.user_message.id,
            _json_payload(response.model_dump(mode="json")),
        )
        return response
    except MealConversationNotFoundError as exc:
        logger.warning(
            "planner.send_message.not_found trace_id=%s conversation_id=%s duration_ms=%s response=%s",
            trace_id or "-",
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            _json_payload({"detail": "Conversation not found."}),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.") from exc


@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
    status_code=status.HTTP_200_OK,
)
def list_messages(
    request: Request,
    conversation_id: str,
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    meal_conversation_service: MealConversationService = Depends(get_meal_conversation_service),
) -> ConversationMessagesResponse:
    trace_id = request.headers.get("x-meal-trace-id", "")
    started_at = time.perf_counter()
    logger.info(
        "planner.list_messages.received trace_id=%s conversation_id=%s user_id=%s before=%s limit=%s",
        trace_id or "-",
        conversation_id,
        current_user.id,
        before or "-",
        limit,
    )
    try:
        response = meal_conversation_service.list_messages(
            current_user=current_user,
            conversation_id=conversation_id,
            before=before,
            limit=limit,
        )
        logger.debug(
            "planner.list_messages.completed trace_id=%s conversation_id=%s duration_ms=%s response=%s",
            trace_id or "-",
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            _json_payload(response.model_dump(mode="json")),
        )
        return response
    except MealConversationNotFoundError as exc:
        logger.warning(
            "planner.list_messages.not_found trace_id=%s conversation_id=%s duration_ms=%s response=%s",
            trace_id or "-",
            conversation_id,
            int((time.perf_counter() - started_at) * 1000),
            _json_payload({"detail": "Conversation not found."}),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.") from exc
