from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.mongodb import mongo_manager
from app.db.redis import redis_manager
from app.dependencies import (
    get_grocery_repository,
    get_inventory_repository,
    get_inventory_service,
    get_meal_conversation_repository,
    get_meal_repository,
    get_measurement_repository,
    get_notification_repository,
    get_push_device_repository,
    get_saved_meal_plan_repository,
    get_user_repository,
)
from app.repositories.meal_planner_monitoring_repository import MealPlannerMonitoringRepository
from app.services.background_task_runner_service import (
    BackgroundJobDefinition,
    BackgroundTaskRunnerService,
)
from app.services.media_storage_service import resolve_local_media_directory
from app.services.meal_planner_monitoring_service import meal_planner_monitoring_service
from app.services.meal_schedule_reminder_service import MealScheduleReminderService
from app.services.notification_service import NotificationService
from app.services.realtime_delivery_service import realtime_delivery_service
from app.services.push_notification_service import PushNotificationService, build_push_notification_sender

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
media_directory = resolve_local_media_directory(settings)
media_directory.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    mongo_manager.connect()
    try:
        mongo_manager.ensure_indexes()
    except (PyMongoError, RuntimeError) as exc:
        logger.warning("MongoDB index bootstrap skipped due to database error: %s", exc)
    redis_manager.connect()
    get_measurement_repository().ensure_seed_data()
    get_grocery_repository().ensure_seed_data()
    get_meal_repository().ensure_seed_data()
    get_inventory_service(
        inventory_repository=get_inventory_repository(),
        grocery_repository=get_grocery_repository(),
        settings=settings,
    ).ensure_seed_inventory_defaults()
    notification_service = NotificationService(
        notification_repository=get_notification_repository(),
        saved_meal_plan_repository=get_saved_meal_plan_repository(),
    )
    meal_schedule_reminder_service = MealScheduleReminderService(
        user_repository=get_user_repository(),
        meal_conversation_repository=get_meal_conversation_repository(),
        saved_meal_plan_repository=get_saved_meal_plan_repository(),
        notification_service=notification_service,
        default_timezone_name=settings.background_meal_slot_default_timezone,
        reminder_windows=MealScheduleReminderService.windows_from_settings(settings),
    )
    background_task_runner = BackgroundTaskRunnerService(
        jobs=[
            BackgroundJobDefinition(
                name="unsaved-meal-plan-reminders",
                interval_seconds=settings.background_unsaved_plan_scan_interval_seconds,
                run=lambda: notification_service.scan_and_deliver_unsaved_plan_reminders(
                    scan_limit=settings.background_unsaved_plan_scan_batch_limit
                ),
                run_immediately=True,
            ),
            BackgroundJobDefinition(
                name="meal-slot-reminders",
                interval_seconds=settings.background_meal_slot_reminder_scan_interval_seconds,
                run=lambda: meal_schedule_reminder_service.scan_and_deliver_current_slot_reminders(
                    scan_limit=settings.background_meal_slot_reminder_scan_batch_limit
                ),
                run_immediately=True,
            )
        ]
    )
    meal_planner_monitoring_service.configure(
        repository=MealPlannerMonitoringRepository(
            runs_collection=mongo_manager.meal_planner_monitoring_runs_collection(),
            events_collection=mongo_manager.meal_planner_monitoring_events_collection(),
        ),
        enabled=settings.meal_planner_monitoring_enabled,
        capture_payloads=settings.meal_planner_monitoring_capture_payloads,
        event_preview_limit=settings.meal_planner_monitoring_event_preview_limit,
    )
    realtime_delivery_service.configure_push_notifications(
        PushNotificationService(
            push_device_repository=get_push_device_repository(),
            sender=build_push_notification_sender(settings),
        )
    )
    await meal_planner_monitoring_service.start()
    await realtime_delivery_service.start()
    await background_task_runner.start()
    logger.info("Application startup complete.")
    yield
    await background_task_runner.stop()
    await meal_planner_monitoring_service.stop()
    await realtime_delivery_service.stop()
    redis_manager.close()
    mongo_manager.close()
    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.mount(settings.local_media_url_prefix, StaticFiles(directory=media_directory), name="media")


@app.get("/", status_code=200)
def root() -> dict[str, str]:
    return {"message": f"{settings.app_name} is running."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
