from fastapi import APIRouter, Depends, Query, status

from app.dependencies import get_current_user, get_notification_service
from app.models.user import User
from app.schemas.notification import NotificationListResponse, NotificationReadResponse
from app.services.notification_service import NotificationNotFoundError, NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse, status_code=status.HTTP_200_OK)
def list_notifications(
    before: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    return notification_service.list_notifications(
        current_user=current_user,
        before=before,
        limit=limit,
    )


@router.post("/{notification_id}/read", response_model=NotificationReadResponse, status_code=status.HTTP_200_OK)
def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
) -> NotificationReadResponse:
    try:
        return notification_service.mark_read(
            current_user=current_user,
            notification_id=notification_id,
        )
    except NotificationNotFoundError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.") from exc
