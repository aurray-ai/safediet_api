from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MealPlannerMonitoringRunResponse(BaseModel):
    id: str
    user_id: str
    trace_id: str | None = None
    request_type: str | None = None
    view_mode: str | None = None
    effective_date: str | None = None
    status: str
    root_step_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    last_event_at: datetime | None = None
    last_step_key: str | None = None
    last_step_status: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class MealPlannerMonitoringEventResponse(BaseModel):
    id: str
    run_id: str
    user_id: str
    trace_id: str | None = None
    event_kind: str
    step_id: str
    parent_step_id: str | None = None
    branch_key: str | None = None
    step_key: str
    step_type: str
    status: str
    input: Any = None
    output: Any = None
    metrics: Any = None
    error: Any = None
    tags: Any = None
    created_at: datetime


class MealPlannerMonitoringRunDetailResponse(BaseModel):
    run: MealPlannerMonitoringRunResponse
    events: list[MealPlannerMonitoringEventResponse] = Field(default_factory=list)
