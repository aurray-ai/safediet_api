from __future__ import annotations

import logging
from typing import Any

from bson import json_util

from app.cache.metrics import cache_metrics_store

try:
    from redis import Redis
except Exception:  # pragma: no cover - optional runtime dependency
    Redis = None

logger = logging.getLogger(__name__)


class RedisCache:
    def __init__(self, client: Redis | None, *, log_hits: bool = False) -> None:
        self._client = client
        self._log_hits = log_hits

    def is_available(self) -> bool:
        return self._client is not None

    def get_json(self, key: str) -> Any | None:
        if self._client is None:
            return None
        try:
            payload = self._client.get(key)
            if payload is None:
                return None
            return json_util.loads(payload)
        except Exception as exc:  # pragma: no cover - cache degradation path
            logger.warning("Redis get_json failed for key '%s': %s", key, exc)
            return None

    def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        if self._client is None:
            return
        try:
            self._client.set(key, json_util.dumps(value), ex=ttl_seconds)
        except Exception as exc:  # pragma: no cover - cache degradation path
            logger.warning("Redis set_json failed for key '%s': %s", key, exc)

    def delete_many(self, *keys: str) -> None:
        if self._client is None:
            return
        filtered_keys = [key for key in keys if key]
        if not filtered_keys:
            return
        try:
            self._client.delete(*filtered_keys)
        except Exception as exc:  # pragma: no cover - cache degradation path
            logger.warning("Redis delete failed for keys '%s': %s", filtered_keys, exc)

    def get_int(self, key: str, *, default: int = 0) -> int:
        if self._client is None:
            return default
        try:
            payload = self._client.get(key)
            if payload is None:
                return default
            return int(payload)
        except Exception as exc:  # pragma: no cover - cache degradation path
            logger.warning("Redis get_int failed for key '%s': %s", key, exc)
            return default

    def increment(self, key: str) -> int | None:
        if self._client is None:
            return None
        try:
            return int(self._client.incr(key))
        except Exception as exc:  # pragma: no cover - cache degradation path
            logger.warning("Redis increment failed for key '%s': %s", key, exc)
            return None

    def record_hit(self, cache_name: str, key: str) -> None:
        cache_metrics_store.record(cache_name, "hit")
        if self._log_hits:
            logger.info("Cache hit [%s] key=%s", cache_name, key)

    def record_miss(self, cache_name: str, key: str) -> None:
        cache_metrics_store.record(cache_name, "miss")
        if self._log_hits:
            logger.info("Cache miss [%s] key=%s", cache_name, key)

    def record_fill(self, cache_name: str, key: str) -> None:
        cache_metrics_store.record(cache_name, "fill")
        if self._log_hits:
            logger.info("Cache fill [%s] key=%s", cache_name, key)
