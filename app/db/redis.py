from __future__ import annotations

import logging

from app.core.config import get_settings

try:
    from redis import Redis
except Exception:  # pragma: no cover - optional runtime dependency
    Redis = None

logger = logging.getLogger(__name__)


class RedisManager:
    def __init__(self) -> None:
        self._client: Redis | None = None

    def connect(self) -> None:
        if self._client is not None:
            return

        settings = get_settings()
        if not settings.redis_url:
            logger.info("Redis cache disabled because REDIS_URL is not configured.")
            return
        if Redis is None:
            logger.warning("Redis cache disabled because the redis client dependency is unavailable.")
            return

        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
        try:
            client.ping()
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("Redis connection failed; continuing without cache: %s", exc)
            client.close()
            return

        self._client = client
        logger.info("Connected to Redis cache.")

    def close(self) -> None:
        if self._client is None:
            return
        self._client.close()
        self._client = None
        logger.info("Closed Redis cache connection.")

    def client(self) -> Redis | None:
        return self._client


redis_manager = RedisManager()
