from fastapi import APIRouter, Depends, Query, status

from app.cache.metrics import cache_metrics_store
from app.core.config import get_settings
from app.db.redis import redis_manager
from app.dependencies import require_platform_user
from app.models.user import User

router = APIRouter(prefix="/admin/cache", tags=["admin-cache"])


@router.get("/metrics", status_code=status.HTTP_200_OK)
def get_cache_metrics(
    reset: bool = Query(default=False),
    _: User = Depends(require_platform_user),
) -> dict[str, object]:
    settings = get_settings()
    snapshot = cache_metrics_store.snapshot()
    response = {
        "redis": {
            "configured": bool(settings.redis_url),
            "connected": redis_manager.client() is not None,
            "cache_log_hits": settings.cache_log_hits,
        },
        "metrics": snapshot,
    }
    if reset:
        cache_metrics_store.reset()
    return response
