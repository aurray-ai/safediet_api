from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.notification import NotificationCategory, NotificationNavigationMode, NotificationType


class NotificationResponse(BaseModel):
    id: str
    category: NotificationCategory
    notification_type: NotificationType
    title: str = Field(min_length=1, max_length=160)
    message: str = Field(default="", max_length=2000)
    navigation_mode: NotificationNavigationMode
    is_read: bool = False
    target: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    next_cursor: str | None = None
    unread_count: int = Field(default=0, ge=0)


class NotificationReadResponse(BaseModel):
    notification: NotificationResponse
    unread_count: int = Field(default=0, ge=0)
