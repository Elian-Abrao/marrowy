from __future__ import annotations

import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from marrowy.db.models import ConversationParticipant
from marrowy.db.models import Job
from marrowy.domain.enums import JobStatus
from marrowy.domain.enums import ParticipantActivityState
from marrowy.services.events import EventService


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = EventService(db)

    def list_for_conversation(self, conversation_id: str) -> list[Job]:
        stmt = select(Job).where(Job.conversation_id == conversation_id).order_by(Job.created_at, Job.priority)
        return list(self.db.scalars(stmt))

    def enqueue(
        self,
        *,
        conversation_id: str | None,
        worker_key: str,
        summary: str,
        agent_key: str | None = None,
        participant_id: str | None = None,
        task_id: str | None = None,
        source_message_id: str | None = None,
        payload: dict | None = None,
        idempotency_key: str | None = None,
        priority: int = 100,
        available_at: datetime | None = None,
    ) -> tuple[Job, bool]:
        existing = None
        if idempotency_key:
            existing = self.db.scalar(
                select(Job).where(
                    Job.idempotency_key == idempotency_key,
                    Job.status.in_(
                        [
                            JobStatus.QUEUED.value,
                            JobStatus.CLAIMED.value,
                            JobStatus.RUNNING.value,
                            JobStatus.WAITING.value,
                        ]
                    ),
                )
            )
        if existing is not None:
            return existing, False
        job = Job(
            conversation_id=conversation_id,
            task_id=task_id,
            participant_id=participant_id,
            source_message_id=source_message_id,
            worker_key=worker_key,
            agent_key=agent_key,
            status=JobStatus.QUEUED.value,
            summary=summary,
            payload_json=payload or {},
            result_json={"progress": []},
            idempotency_key=idempotency_key,
            priority=priority,
            available_at=available_at or _now(),
        )
        self.db.add(job)
        self.db.flush()
        self.events.emit(
            "job.queued",
            conversation_id=conversation_id,
            task_id=task_id,
            payload={"jobId": job.id, "workerKey": worker_key, "agentKey": agent_key, "summary": summary},
        )
        self._set_participant_activity(
            participant_id=participant_id,
            state=ParticipantActivityState.QUEUED,
            summary=summary,
        )
        return job, True

    def claim_next(self, *, worker_id: str, worker_keys: list[str] | None = None, lease_seconds: int = 300) -> Job | None:
        now = _now()
        stmt = select(Job).where(
            Job.status == JobStatus.QUEUED.value,
            Job.available_at <= now,
        )
        if worker_keys:
            stmt = stmt.where(Job.worker_key.in_(worker_keys))
        stmt = stmt.order_by(Job.priority, Job.created_at)
        candidates = list(self.db.scalars(stmt.limit(10)))
        for candidate in candidates:
            token = str(uuid.uuid4())
            result = self.db.execute(
                update(Job)
                .where(Job.id == candidate.id, Job.status == JobStatus.QUEUED.value)
                .values(
                    status=JobStatus.CLAIMED.value,
                    claim_token=token,
                    claimed_by=worker_id,
                    claimed_at=now,
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                self.db.flush()
                job = self.db.get(Job, candidate.id)
                if job is None:
                    return None
                self.events.emit(
                    "job.claimed",
                    conversation_id=job.conversation_id,
                    task_id=job.task_id,
                    payload={"jobId": job.id, "workerKey": job.worker_key, "claimedBy": worker_id},
                )
                return job
        return None

    def mark_running(self, job: Job, *, summary: str | None = None) -> Job:
        now = _now()
        job.status = JobStatus.RUNNING.value
        job.started_at = job.started_at or now
        job.attempt_count += 1
        if summary:
            job.summary = summary
        self.db.flush()
        self.events.emit(
            "job.started",
            conversation_id=job.conversation_id,
            task_id=job.task_id,
            payload={"jobId": job.id, "summary": job.summary, "workerKey": job.worker_key},
        )
        self._set_participant_activity(
            participant_id=job.participant_id,
            state=ParticipantActivityState.WORKING,
            summary=job.summary,
        )
        return job

    def append_progress(self, job: Job, *, text: str, progress_type: str = "status") -> Job:
        result = dict(job.result_json or {})
        progress = list(result.get("progress", []))
        progress.append({"type": progress_type, "text": text, "createdAt": _now().isoformat()})
        result["progress"] = progress[-20:]
        result["latest"] = text
        job.result_json = result
        self.db.flush()
        self.events.emit(
            "job.progress",
            conversation_id=job.conversation_id,
            task_id=job.task_id,
            payload={"jobId": job.id, "progressType": progress_type, "text": text},
        )
        self._set_participant_activity(
            participant_id=job.participant_id,
            state=ParticipantActivityState.WORKING,
            summary=text[:240],
        )
        return job

    def mark_waiting(self, job: Job, *, summary: str) -> Job:
        job.status = JobStatus.WAITING.value
        job.summary = summary
        self.db.flush()
        self.events.emit(
            "job.waiting",
            conversation_id=job.conversation_id,
            task_id=job.task_id,
            payload={"jobId": job.id, "summary": summary},
        )
        self._set_participant_activity(
            participant_id=job.participant_id,
            state=ParticipantActivityState.WAITING,
            summary=summary,
        )
        return job

    def succeed(self, job: Job, *, result: dict | None = None, summary: str | None = None) -> Job:
        now = _now()
        job.status = JobStatus.SUCCEEDED.value
        job.finished_at = now
        if summary:
            job.summary = summary
        if result:
            merged = dict(job.result_json or {})
            merged.update(result)
            job.result_json = merged
        self.db.flush()
        self.events.emit(
            "job.completed",
            conversation_id=job.conversation_id,
            task_id=job.task_id,
            payload={"jobId": job.id, "summary": job.summary},
        )
        self._set_participant_activity(
            participant_id=job.participant_id,
            state=ParticipantActivityState.IDLE,
            summary="Idle",
        )
        return job

    def fail(self, job: Job, *, error: str) -> Job:
        now = _now()
        job.status = JobStatus.FAILED.value
        job.finished_at = now
        job.last_error = error
        self.db.flush()
        self.events.emit(
            "job.failed",
            conversation_id=job.conversation_id,
            task_id=job.task_id,
            payload={"jobId": job.id, "error": error},
        )
        self._set_participant_activity(
            participant_id=job.participant_id,
            state=ParticipantActivityState.ERROR,
            summary=error[:240],
        )
        return job

    def has_pending_for_source(self, *, source_message_id: str, participant_id: str) -> bool:
        return self.db.scalar(
            select(Job.id).where(
                Job.source_message_id == source_message_id,
                Job.participant_id == participant_id,
                Job.status.in_(
                    [
                        JobStatus.QUEUED.value,
                        JobStatus.CLAIMED.value,
                        JobStatus.RUNNING.value,
                        JobStatus.WAITING.value,
                    ]
                ),
            )
        ) is not None

    def _set_participant_activity(
        self,
        *,
        participant_id: str | None,
        state: ParticipantActivityState,
        summary: str | None,
    ) -> None:
        if participant_id is None:
            return
        participant = self.db.get(ConversationParticipant, participant_id)
        if participant is None:
            return
        participant.activity_state = state.value
        participant.activity_summary = summary
        participant.last_activity_at = _now()
        self.db.flush()
        self.events.emit(
            "participant.activity.updated",
            conversation_id=participant.conversation_id,
            payload={
                "participantId": participant.id,
                "displayName": participant.display_name,
                "activityState": participant.activity_state,
                "activitySummary": participant.activity_summary,
            },
        )
