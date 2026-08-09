from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackgroundJobDefinition:
    name: str
    interval_seconds: float
    run: Callable[[], Awaitable[None]]
    run_immediately: bool = True


class BackgroundTaskRunnerService:
    def __init__(self, jobs: list[BackgroundJobDefinition]) -> None:
        self._jobs = list(jobs)
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run_job(job), name=f"background-job:{job.name}")
            for job in self._jobs
        ]
        logger.info("Background task runner started jobs=%s", ",".join(job.name for job in self._jobs) or "-")

    async def stop(self) -> None:
        if not self._tasks:
            return
        tasks = list(self._tasks)
        self._tasks = []
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("Background task runner stopped.")

    async def _run_job(self, job: BackgroundJobDefinition) -> None:
        if not job.run_immediately:
            await asyncio.sleep(job.interval_seconds)

        while True:
            try:
                logger.info("Background job started name=%s", job.name)
                await job.run()
                logger.info("Background job completed name=%s", job.name)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background job failed name=%s", job.name)
            await asyncio.sleep(job.interval_seconds)
