from __future__ import annotations

from collections import defaultdict
from threading import Lock


class CacheMetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._totals: dict[str, int] = defaultdict(int)
        self._by_cache: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, cache_name: str, event: str) -> None:
        with self._lock:
            self._totals[event] += 1
            self._by_cache[cache_name][event] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            totals = {key: int(value) for key, value in self._totals.items()}
            by_cache = {
                cache_name: {event: int(value) for event, value in metrics.items()}
                for cache_name, metrics in self._by_cache.items()
            }

        total_hits = totals.get("hit", 0)
        total_misses = totals.get("miss", 0)
        total_reads = total_hits + total_misses
        hit_rate = (float(total_hits) / float(total_reads)) if total_reads else None

        return {
            "totals": {
                "hits": total_hits,
                "misses": total_misses,
                "fills": totals.get("fill", 0),
                "reads": total_reads,
                "hit_rate": hit_rate,
            },
            "by_cache": {
                cache_name: {
                    "hits": metrics.get("hit", 0),
                    "misses": metrics.get("miss", 0),
                    "fills": metrics.get("fill", 0),
                    "reads": metrics.get("hit", 0) + metrics.get("miss", 0),
                    "hit_rate": (
                        float(metrics.get("hit", 0)) / float(metrics.get("hit", 0) + metrics.get("miss", 0))
                        if (metrics.get("hit", 0) + metrics.get("miss", 0))
                        else None
                    ),
                }
                for cache_name, metrics in by_cache.items()
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._totals.clear()
            self._by_cache.clear()


cache_metrics_store = CacheMetricsStore()
