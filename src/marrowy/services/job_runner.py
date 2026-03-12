from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from marrowy.db.models import Job
from marrowy.domain.enums import JobStatus
from marrowy.providers.base import ModelProvider
from marrowy.services.conversations import ConversationService
from marrowy.services.jobs import JobService

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        provider_factory: Callable[[], ModelProvider],
        poll_interval: float = 0.5,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider_factory = provider_factory
        self.poll_interval = poll_interval
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_forever(), name=f"marrowy-job-runner:{self.worker_id}")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def run_forever(self) -> None:
        while not self._stop_event.is_set():
            processed = await self.run_once()
            if not processed:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
                except TimeoutError:
                    continue

    async def run_until_idle(self, *, timeout: float = 15.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            processed = await self.run_once()
            if not processed:
                session = self.session_factory()
                try:
                    active = session.scalar(
                        select(Job.id).where(
                            Job.status.in_(
                                [
                                    JobStatus.QUEUED.value,
                                    JobStatus.CLAIMED.value,
                                    JobStatus.RUNNING.value,
                                    JobStatus.WAITING.value,
                                ]
                            )
                        )
                    )
                finally:
                    session.close()
                if active is None:
                    return
                await asyncio.sleep(self.poll_interval)
        raise TimeoutError("job runner did not become idle in time")

    async def run_once(self) -> bool:
        session = self.session_factory()
        try:
            jobs = JobService(session)
            job = jobs.claim_next(worker_id=self.worker_id)
            if job is None:
                session.commit()
                return False
            session.commit()
            provider = self.provider_factory()
            service = ConversationService(session, provider)
            await service.process_job(job.id, worker_id=self.worker_id)
            session.commit()
            return True
        except Exception:
            session.rollback()
            logger.exception("job runner failed while processing a job")
            return False
        finally:
            session.close()
