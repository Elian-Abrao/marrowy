from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import ApprovalRequest
from marrowy.db.models import Conversation
from marrowy.db.models import ConversationMessage
from marrowy.db.models import ConversationParticipant
from marrowy.db.models import Job
from marrowy.db.models import Project
from marrowy.db.models import Task
from marrowy.domain.agents import AGENT_PROFILES
from marrowy.domain.agents import AgentProfile
from marrowy.domain.agents import get_agent_profile
from marrowy.domain.enums import ConversationStatus
from marrowy.domain.enums import JobStatus
from marrowy.domain.enums import MessageKind
from marrowy.domain.enums import MemoryScope
from marrowy.domain.enums import ParticipantActivityState
from marrowy.domain.enums import ParticipantKind
from marrowy.domain.enums import TaskKind
from marrowy.domain.enums import TaskStatus
from marrowy.domain.workers import worker_key_for_agent
from marrowy.providers.base import ModelProvider
from marrowy.services.events import EventService
from marrowy.services.jobs import JobService
from marrowy.services.memory import MemoryService
from marrowy.services.policies import PolicyService
from marrowy.services.tasks import TaskService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


@dataclass(slots=True)
class MessageContext:
    conversation: Conversation
    project: Project | None
    principal: ConversationParticipant
    participants: list[ConversationParticipant]
    pending_approvals: list[ApprovalRequest]
    tasks: list[Task]
    jobs: list[Job]


@dataclass(slots=True)
class ScheduledTurn:
    participant: ConversationParticipant
    worker_key: str
    summary: str
    task_id: str | None = None


@dataclass(slots=True)
class OrchestrationPlan:
    messages: list[ConversationMessage] = field(default_factory=list)
    scheduled_turns: list[ScheduledTurn] = field(default_factory=list)


class ConversationService:
    def __init__(self, db: Session, provider: ModelProvider) -> None:
        self.db = db
        self.provider = provider
        self.events = EventService(db)
        self.tasks = TaskService(db)
        self.policies = PolicyService(db)
        self.memory = MemoryService(db)
        self.jobs = JobService(db)

    def list_conversations(self) -> list[Conversation]:
        return list(self.db.scalars(select(Conversation).order_by(Conversation.updated_at.desc())))

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.db.get(Conversation, conversation_id)

    def create_conversation(
        self,
        *,
        title: str,
        project_id: str | None = None,
        channel: str = "browser",
        external_ref: str | None = None,
        user_name: str = "User",
    ) -> Conversation:
        conversation = Conversation(
            title=title,
            status=ConversationStatus.ACTIVE.value,
            project_id=project_id,
            channel=channel,
            external_ref=external_ref,
        )
        self.db.add(conversation)
        self.db.flush()
        user = ConversationParticipant(
            conversation_id=conversation.id,
            kind=ParticipantKind.USER.value,
            display_name=user_name,
            activity_state=ParticipantActivityState.IDLE.value,
        )
        principal = ConversationParticipant(
            conversation_id=conversation.id,
            kind=ParticipantKind.AGENT.value,
            agent_key="principal",
            display_name=AGENT_PROFILES["principal"].display_name,
            activity_state=ParticipantActivityState.IDLE.value,
            activity_summary="Ready to coordinate.",
            last_activity_at=_utcnow(),
        )
        self.db.add_all([user, principal])
        self.db.flush()
        self.events.emit("conversation.created", conversation_id=conversation.id, payload={"conversationId": conversation.id})
        self.events.emit("agent.joined", conversation_id=conversation.id, payload={"agentKey": "principal"})
        self.add_message(
            conversation_id=conversation.id,
            author_name=principal.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content="I am online as Agent Principal. I will coordinate this conversation, tasks, approvals, and worker activity.",
            message_type=MessageKind.SYSTEM.value,
            participant_id=principal.id,
        )
        return conversation

    def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        stmt = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.created_at)
        return list(self.db.scalars(stmt))

    def list_participants(self, conversation_id: str) -> list[ConversationParticipant]:
        stmt = select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id).order_by(ConversationParticipant.joined_at)
        return list(self.db.scalars(stmt))

    def add_message(
        self,
        *,
        conversation_id: str,
        author_name: str,
        author_kind: str,
        content: str,
        message_type: str,
        participant_id: str | None = None,
        metadata: dict | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            participant_id=participant_id,
            author_name=author_name,
            author_kind=author_kind,
            content=content,
            message_type=message_type,
            metadata_json=metadata or {},
        )
        self.db.add(message)
        self.db.flush()
        self.events.emit(
            "conversation.message.created",
            conversation_id=conversation_id,
            payload={"messageId": message.id, "authorName": author_name, "messageType": message_type},
        )
        return message

    def add_agent(self, conversation_id: str, agent_key: str) -> ConversationParticipant:
        existing = self.db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.agent_key == agent_key,
            )
        )
        if existing is not None:
            return existing
        profile = get_agent_profile(agent_key)
        participant = ConversationParticipant(
            conversation_id=conversation_id,
            kind=ParticipantKind.AGENT.value,
            agent_key=agent_key,
            display_name=profile.display_name,
            activity_state=ParticipantActivityState.IDLE.value,
            activity_summary="Available for assignment.",
            last_activity_at=_utcnow(),
        )
        self.db.add(participant)
        self.db.flush()
        self.events.emit("agent.joined", conversation_id=conversation_id, payload={"agentKey": agent_key})
        return participant

    def resolve_approval(self, approval_id: str, *, actor_name: str, decision: str) -> ApprovalRequest:
        approval = self.db.get(ApprovalRequest, approval_id)
        if approval is None:
            raise ValueError(f"approval {approval_id!r} not found")
        resolved = self.policies.resolve(approval, actor_name=actor_name, decision=decision)
        self.add_message(
            conversation_id=resolved.conversation_id,
            author_name=actor_name,
            author_kind=ParticipantKind.USER.value,
            content=f"{decision.capitalize()}d approval {approval_id}.",
            message_type=MessageKind.APPROVAL.value,
            metadata={"approvalId": approval_id, "decision": decision},
        )
        if resolved.task_id:
            task = self.tasks.get(resolved.task_id)
            if task is not None:
                next_status = TaskStatus.DEPLOYING if decision == "approve" else TaskStatus.BLOCKED
                self._transition_task(task, next_status)
        self.add_message(
            conversation_id=resolved.conversation_id,
            author_name="Agent Principal",
            author_kind=ParticipantKind.AGENT.value,
            content=(
                f"[Agent Principal]\nApproval {approval_id} was {'approved' if decision == 'approve' else 'rejected'}. "
                "I updated the relevant task state and will continue coordination."
            ),
            message_type=MessageKind.AGENT.value,
        )
        self._refresh_conversation_state(resolved.conversation_id)
        return resolved

    async def handle_user_message(self, conversation_id: str, *, content: str, user_name: str) -> list[ConversationMessage]:
        context = self._message_context(conversation_id)
        user = next(participant for participant in context.participants if participant.kind == ParticipantKind.USER.value)
        user_message = self.add_message(
            conversation_id=conversation_id,
            author_name=user_name,
            author_kind=ParticipantKind.USER.value,
            content=content,
            message_type=MessageKind.USER.value,
            participant_id=user.id,
        )
        created_messages: list[ConversationMessage] = [user_message]
        created_messages.append(self._acknowledge_user_message(context, user_message))

        plan = self._derive_orchestration_plan(context, content, user_message)
        created_messages.extend(plan.messages)

        scheduled_ids: set[str] = set()
        for turn in plan.scheduled_turns:
            if turn.participant.id in scheduled_ids:
                continue
            scheduled_ids.add(turn.participant.id)
            if turn.task_id and turn.participant.agent_key:
                self._mark_task_visible_progress(turn.task_id, turn.participant.agent_key)
            self.jobs.enqueue(
                conversation_id=context.conversation.id,
                worker_key=turn.worker_key,
                agent_key=turn.participant.agent_key,
                participant_id=turn.participant.id,
                task_id=turn.task_id,
                source_message_id=user_message.id,
                summary=turn.summary,
                idempotency_key=f"agent-turn:{context.conversation.id}:{user_message.id}:{turn.participant.id}",
                payload={"prompt": content},
                priority=self._priority_for_agent(turn.participant.agent_key),
            )

        self._refresh_conversation_state(conversation_id)
        context.conversation.updated_at = _utcnow()
        self.db.flush()
        return created_messages

    async def process_job(self, job_id: str, *, worker_id: str) -> None:
        job = self.db.get(Job, job_id)
        if job is None:
            return
        if job.status not in {JobStatus.CLAIMED.value, JobStatus.QUEUED.value}:
            return
        participant = self.db.get(ConversationParticipant, job.participant_id) if job.participant_id else None
        conversation = self.get_conversation(job.conversation_id) if job.conversation_id else None
        if participant is None or conversation is None:
            self.jobs.fail(job, error="job references missing participant or conversation")
            return

        profile = get_agent_profile(participant.agent_key or "principal")
        prompt = self._build_agent_prompt(
            conversation=conversation,
            project=self.db.get(Project, conversation.project_id) if conversation.project_id else None,
            participant=participant,
            user_prompt=str(job.payload_json.get("prompt") or ""),
            messages=self.list_messages(conversation.id),
            current_task=self.tasks.get(job.task_id) if job.task_id else None,
        )
        self.jobs.mark_running(job, summary=job.summary)
        self._maybe_transition_task_on_job_start(job)
        self._refresh_conversation_state(conversation.id)
        self.db.commit()

        async def on_provider_event(event_type: str, text: str) -> None:
            if event_type == "final":
                return
            progress_text = text.strip()
            if not progress_text:
                return
            self.jobs.append_progress(job, text=progress_text, progress_type=event_type)
            self.db.commit()

        try:
            result, thread_id = await self.provider.complete(
                role_name=profile.display_name,
                instructions=profile.instructions,
                prompt=prompt,
                thread_id=participant.bridge_thread_id,
                cwd=self._select_cwd(self.db.get(Project, conversation.project_id) if conversation.project_id else None),
                event_handler=on_provider_event,
            )
        except Exception as exc:
            self.jobs.fail(job, error=str(exc))
            self.add_message(
                conversation_id=conversation.id,
                author_name=profile.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content=f"[{profile.display_name}]\nI could not complete my turn because the provider failed: {exc}",
                message_type=MessageKind.AGENT.value,
                participant_id=participant.id,
            )
            self._maybe_transition_task_on_job_failure(job)
            self._refresh_conversation_state(conversation.id)
            self.db.commit()
            return

        if thread_id and participant.bridge_thread_id != thread_id:
            participant.bridge_thread_id = thread_id
        content = f"[{profile.display_name}]\n{result.text}".strip()
        self.add_message(
            conversation_id=conversation.id,
            author_name=profile.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content=content,
            message_type=MessageKind.AGENT.value,
            participant_id=participant.id,
            metadata={"commentary": result.commentary, "actions": result.actions},
        )
        self.jobs.succeed(
            job,
            result={"threadId": thread_id, "commentary": result.commentary, "actions": result.actions},
            summary=f"{profile.display_name} completed the assigned turn.",
        )
        self._maybe_transition_task_on_job_success(job)
        self._refresh_conversation_state(conversation.id)
        self.db.commit()

    def _message_context(self, conversation_id: str) -> MessageContext:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"conversation {conversation_id!r} not found")
        project = self.db.get(Project, conversation.project_id) if conversation.project_id else None
        participants = self.list_participants(conversation_id)
        principal = next(participant for participant in participants if participant.agent_key == "principal")
        pending = self.policies.pending_for_conversation(conversation_id)
        tasks = self.tasks.list_for_conversation(conversation_id)
        jobs = self.jobs.list_for_conversation(conversation_id)
        return MessageContext(
            conversation=conversation,
            project=project,
            principal=principal,
            participants=participants,
            pending_approvals=pending,
            tasks=tasks,
            jobs=jobs,
        )

    def _acknowledge_user_message(self, context: MessageContext, user_message: ConversationMessage) -> ConversationMessage:
        summary = "I received your message. I am coordinating the next steps and will keep the room updated while the workers run."
        return self.add_message(
            conversation_id=context.conversation.id,
            author_name=context.principal.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content=f"[Agent Principal]\n{summary}",
            message_type=MessageKind.SYSTEM.value,
            participant_id=context.principal.id,
            metadata={"ackForMessageId": user_message.id},
        )

    def _derive_orchestration_plan(
        self,
        context: MessageContext,
        content: str,
        created_by_message: ConversationMessage,
    ) -> OrchestrationPlan:
        text = _normalize_text(content)
        plan = OrchestrationPlan()

        for agent_key in self._requested_agent_additions(text):
            participant, was_added = self._ensure_agent_with_handoff(
                context=context,
                agent_key=agent_key,
                source_content=content,
            )
            if was_added:
                plan.messages.extend(self._hand_off_messages(context, participant, source_content=content))
            if participant.agent_key:
                plan.scheduled_turns.append(
                    ScheduledTurn(
                        participant=participant,
                        worker_key=worker_key_for_agent(participant.agent_key),
                        summary=f"{participant.display_name} is joining the room and preparing a handoff response.",
                        task_id=self._select_task_for_agent(context.conversation.id, participant.agent_key),
                    )
                )

        root_task = self._select_target_root_task(context, text)
        if self._wants_pipeline_creation(text):
            if root_task is not None and not self._wants_new_project(text):
                stage_tasks = self.tasks.list_subtasks(root_task.id)
                created = False
            else:
                root_task, stage_tasks, created = self._ensure_pipeline(context, content, created_by_message.id)
            if created:
                plan.messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=(
                            f"[Agent Principal] Created pipeline task {root_task.id} with {len(stage_tasks)} delivery stages. "
                            "The work has been broken into coordinated execution units."
                        ),
                        message_type=MessageKind.AGENT.value,
                        participant_id=context.principal.id,
                        metadata={"taskId": root_task.id},
                    )
                )
            else:
                plan.messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=f"[Agent Principal] Reusing active pipeline task {root_task.id} instead of creating a duplicate.",
                        message_type=MessageKind.SYSTEM.value,
                        participant_id=context.principal.id,
                        metadata={"taskId": root_task.id},
                    )
                )

        if self._wants_simple_task_creation(text):
            task, created = self._ensure_simple_task(context, content, created_by_message.id)
            if created:
                plan.messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=f"[Agent Principal] Created task {task.id} and mapped it to Agent Specialist.",
                        message_type=MessageKind.AGENT.value,
                        participant_id=context.principal.id,
                        metadata={"taskId": task.id},
                    )
                )
            root_task = root_task or task

        if self._wants_decomposition(text) and root_task is not None:
            subtasks, created = self._ensure_decomposition(context, root_task, created_by_message.id)
            plan.messages.append(
                self.add_message(
                    conversation_id=context.conversation.id,
                    author_name=context.principal.display_name,
                    author_kind=ParticipantKind.AGENT.value,
                    content=(
                        f"[Agent Principal] {'Created' if created else 'Reused'} {len(subtasks)} subtasks under task {root_task.id} "
                        "to make the next execution steps explicit."
                    ),
                    message_type=MessageKind.AGENT.value,
                    participant_id=context.principal.id,
                    metadata={"taskId": root_task.id, "subtaskCount": len(subtasks)},
                )
            )
            if not any(turn.participant.agent_key == "po_pm" for turn in plan.scheduled_turns):
                po_pm, was_added = self._ensure_agent_with_handoff(context=context, agent_key="po_pm", source_content=content)
                if was_added:
                    plan.messages.extend(self._hand_off_messages(context, po_pm, source_content=content))
                plan.scheduled_turns.append(
                    ScheduledTurn(
                        participant=po_pm,
                        worker_key=worker_key_for_agent("po_pm"),
                        summary=f"{po_pm.display_name} is refining the task decomposition and rollout plan.",
                        task_id=root_task.id,
                    )
                )

        if self._wants_deploy_action(text):
            deploy_task = root_task or self._select_target_root_task(context, text)
            approval = self.policies.ensure_approval(
                conversation=context.conversation,
                agent_key="principal",
                action_type="deploy.production",
                summary="Approve production deployment for the active workstream.",
                details={"environment": "production", "tool": "deploy"},
                task_id=deploy_task.id if deploy_task else None,
                idempotency_key=f"approval:{context.conversation.id}:deploy.production:{deploy_task.id if deploy_task else 'none'}",
            )
            if deploy_task is not None:
                self._transition_task(deploy_task, TaskStatus.WAITING_APPROVAL)
            plan.messages.append(
                self.add_message(
                    conversation_id=context.conversation.id,
                    author_name=context.principal.display_name,
                    author_kind=ParticipantKind.AGENT.value,
                    content=f"[Agent Principal] Production deploy is blocked pending approval {approval.id}.",
                    message_type=MessageKind.APPROVAL.value,
                    participant_id=context.principal.id,
                    metadata={"approvalId": approval.id},
                )
            )

        for participant in self._participants_to_invoke(context, text):
            if participant.agent_key is None:
                continue
            if any(turn.participant.id == participant.id for turn in plan.scheduled_turns):
                continue
            plan.scheduled_turns.append(
                ScheduledTurn(
                    participant=participant,
                    worker_key=worker_key_for_agent(participant.agent_key),
                    summary=self._job_summary_for_participant(participant, text),
                    task_id=self._select_task_for_agent(context.conversation.id, participant.agent_key),
                )
            )
        return plan

    def _ensure_agent_with_handoff(
        self,
        *,
        context: MessageContext,
        agent_key: str,
        source_content: str,
    ) -> tuple[ConversationParticipant, bool]:
        existing = next((item for item in self.list_participants(context.conversation.id) if item.agent_key == agent_key), None)
        if existing is not None:
            return existing, False
        participant = self.add_agent(context.conversation.id, agent_key)
        self.events.emit(
            "agent.onboarded",
            conversation_id=context.conversation.id,
            payload={"agentKey": agent_key, "displayName": participant.display_name},
        )
        return participant, True

    def _hand_off_messages(
        self,
        context: MessageContext,
        participant: ConversationParticipant,
        *,
        source_content: str,
    ) -> list[ConversationMessage]:
        active_tasks = self.tasks.list_for_conversation(context.conversation.id)
        task_lines = "\n".join(f"- {task.id} [{task.status}] {task.title}" for task in active_tasks[:4]) or "- no active tasks yet"
        project_line = context.project.name if context.project is not None else "No linked project"
        return [
            self.add_message(
                conversation_id=context.conversation.id,
                author_name=context.principal.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content=f"[Agent Principal] Added {participant.display_name} to the room.",
                message_type=MessageKind.AGENT.value,
                participant_id=context.principal.id,
                metadata={"agentKey": participant.agent_key},
            ),
            self.add_message(
                conversation_id=context.conversation.id,
                author_name=context.principal.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content=(
                    f"[Onboarding for {participant.display_name}]\n"
                    f"Reason for joining: {source_content}\n"
                    f"Project: {project_line}\n"
                    f"Current open work:\n{task_lines}\n"
                    "Please pick up the relevant context, explain your approach clearly, and keep progress visible."
                ),
                message_type=MessageKind.HANDOFF.value,
                participant_id=context.principal.id,
                metadata={"handoffFor": participant.agent_key},
            ),
        ]

    def _participants_to_invoke(self, context: MessageContext, text: str) -> list[ConversationParticipant]:
        ordered_keys = ["principal"]
        role_tokens = {
            "specialist": ["@specialist", "agent specialist", "ask specialist", "have specialist", "bring in specialist", "add specialist"],
            "qa": ["@qa", "agent qa", "ask qa", "have qa", "bring in qa", "add qa"],
            "github": ["@github", "agent github", "ask github", "have github", "bring in github", "add github"],
            "devops": ["@devops", "agent devops", "ask devops", "have devops", "bring in devops", "add devops"],
            "po_pm": ["@po", "@pm", "agent po/pm", "agent pm", "agent po", "ask pm", "ask po", "have pm", "bring in pm", "add pm", "add po/pm"],
        }
        for key, tokens in role_tokens.items():
            if any(token in text for token in tokens):
                ordered_keys.append(key)
        participants_by_key = {participant.agent_key: participant for participant in self.list_participants(context.conversation.id) if participant.agent_key}
        return [participants_by_key[key] for key in ordered_keys if key in participants_by_key]

    def _requested_agent_additions(self, text: str) -> list[str]:
        additions: list[str] = []
        tokens = {
            "specialist": ["add specialist", "add agent specialist", "bring in specialist"],
            "qa": ["add qa", "add agent qa", "bring in qa"],
            "github": ["add github", "add agent github", "bring in github"],
            "devops": ["add devops", "add agent devops", "bring in devops"],
            "po_pm": ["add po", "add pm", "add po/pm", "bring in po", "bring in pm", "agent po/pm", "agent pm", "agent po"],
        }
        for key, phrases in tokens.items():
            if any(phrase in text for phrase in phrases):
                additions.append(key)
        return additions

    def _active_root_task(self, conversation_id: str) -> Task | None:
        tasks = self.tasks.list_for_conversation(conversation_id)
        return next(
            (
                task
                for task in tasks
                if task.parent_task_id is None and task.status not in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}
            ),
            None,
        )

    def _select_target_root_task(self, context: MessageContext, text: str) -> Task | None:
        root_tasks = [
            task
            for task in context.tasks
            if task.parent_task_id is None and task.status not in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}
        ]
        if not root_tasks:
            return None
        words = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 2}
        scored: list[tuple[int, datetime, Task]] = []
        for task in root_tasks:
            haystack = _normalize_text(f"{task.title} {task.goal}")
            overlap = sum(1 for word in words if word in haystack)
            scored.append((overlap, task.created_at, task))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if scored and scored[0][0] > 0:
            return scored[0][2]
        return root_tasks[-1]

    def _ensure_pipeline(self, context: MessageContext, content: str, message_id: str) -> tuple[Task, list[Task], bool]:
        key = f"pipeline:{context.conversation.id}:{self._task_title_from_content(content).lower()}"
        existing = self.tasks.find_active_by_idempotency(conversation_id=context.conversation.id, idempotency_key=key)
        if existing is not None:
            return existing, self.tasks.list_subtasks(existing.id), False
        root, stages = self.tasks.create_pipeline_task(
            conversation_id=context.conversation.id,
            project_id=context.conversation.project_id,
            title=self._task_title_from_content(content),
            goal=content,
            created_by_message_id=message_id,
            idempotency_key=key,
        )
        return root, stages, True

    def _ensure_simple_task(self, context: MessageContext, content: str, message_id: str) -> tuple[Task, bool]:
        key = f"task:{context.conversation.id}:{self._task_title_from_content(content).lower()}"
        existing = self.tasks.find_active_by_idempotency(conversation_id=context.conversation.id, idempotency_key=key)
        if existing is not None:
            return existing, False
        task = self.tasks.create_simple_task(
            conversation_id=context.conversation.id,
            project_id=context.conversation.project_id,
            title=self._task_title_from_content(content),
            goal=content,
            assigned_agent_key="specialist",
            created_by_message_id=message_id,
            idempotency_key=key,
        )
        return task, True

    def _ensure_decomposition(self, context: MessageContext, root_task: Task, message_id: str) -> tuple[list[Task], bool]:
        existing = [task for task in self.tasks.list_subtasks(root_task.id) if task.kind == TaskKind.SUBTASK.value]
        if existing:
            return existing, False
        subtasks = self.tasks.ensure_subtasks(
            conversation_id=context.conversation.id,
            project_id=context.conversation.project_id,
            parent_task_id=root_task.id,
            created_by_message_id=message_id,
            items=[
                {"title": "Clarify scope and acceptance criteria", "goal": "Clarify v1 boundaries", "assigned_agent_key": "po_pm"},
                {"title": "Implement the core happy path", "goal": "Build the main user flow", "assigned_agent_key": "specialist"},
                {"title": "Validate the critical path", "goal": "Confirm the core flow works", "assigned_agent_key": "qa"},
                {"title": "Prepare repo and delivery hygiene", "goal": "Capture release and repo follow-up", "assigned_agent_key": "github"},
            ],
        )
        return subtasks, True

    def _wants_pipeline_creation(self, text: str) -> bool:
        return (
            ("pipeline" in text and any(token in text for token in ["create", "set up", "build", "prepare", "start"]))
            or any(token in text for token in ["create project", "new mvp"])
        )

    def _wants_simple_task_creation(self, text: str) -> bool:
        return any(token in text for token in ["create task", "separate task", "follow-up task"])

    def _wants_decomposition(self, text: str) -> bool:
        return any(token in text for token in ["decompose", "break down", "refine the mvp", "refine into", "small incremental steps", "subtasks"])

    def _wants_deploy_action(self, text: str) -> bool:
        if "deploy" not in text and "production" not in text:
            return False
        intent_tokens = ["prepare a production deployment", "deploy to production", "prepare deployment", "start deployment", "production deployment"]
        return any(token in text for token in intent_tokens)

    def _wants_new_project(self, text: str) -> bool:
        return any(token in text for token in ["brand-new", "new project", "another project", "separate project"])

    def _job_summary_for_participant(self, participant: ConversationParticipant, text: str) -> str:
        role = participant.display_name
        if participant.agent_key == "principal":
            return "Agent Principal is preparing a coordinated reply."
        if participant.agent_key == "qa":
            return f"{role} is reviewing validation scope and risks."
        if participant.agent_key == "github":
            return f"{role} is preparing repository and release guidance."
        if participant.agent_key == "devops":
            return f"{role} is checking environment and deploy implications."
        if participant.agent_key == "po_pm":
            return f"{role} is decomposing the work into explicit next steps."
        return f"{role} is working on the latest request."

    def _select_task_for_agent(self, conversation_id: str, agent_key: str) -> str | None:
        tasks = self.tasks.list_for_conversation(conversation_id)
        for task in tasks:
            if task.assigned_agent_key == agent_key and task.status in {
                TaskStatus.CREATED.value,
                TaskStatus.PLANNED.value,
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.BLOCKED.value,
                TaskStatus.TESTING.value,
                TaskStatus.WAITING_APPROVAL.value,
            }:
                return task.id
        root = self._active_root_task(conversation_id)
        return root.id if root is not None else None

    def _build_agent_prompt(
        self,
        *,
        conversation: Conversation,
        project: Project | None,
        participant: ConversationParticipant,
        user_prompt: str,
        messages: Iterable[ConversationMessage],
        current_task: Task | None,
    ) -> str:
        transcript = "\n".join(f"{message.author_name}: {message.content}" for message in list(messages)[-10:])
        open_tasks = self.tasks.list_for_conversation(conversation.id)
        task_lines = "\n".join(
            f"- {task.id} [{task.status}] {task.title}"
            for task in open_tasks[-8:]
        ) or "- no tasks yet"
        project_memories = self.memory.list_memory(MemoryScope.PROJECT, project.id) if project is not None else []
        conversation_memories = self.memory.list_memory(MemoryScope.CONVERSATION, conversation.id)
        user_memories = self.memory.list_memory(MemoryScope.USER, participant.display_name)
        project_context = project.context_markdown if project is not None and project.context_markdown else "No explicit project context."
        memory_lines = "\n".join(
            f"- {entry.scope_type}:{entry.category}: {entry.content}"
            for entry in [*project_memories[-3:], *conversation_memories[-3:], *user_memories[-2:]]
        ) or "- no persisted memory"
        task_focus = (
            f"Current execution focus: {current_task.id} [{current_task.status}] {current_task.title}\n"
            f"Task goal: {current_task.goal}\n"
        ) if current_task is not None else "Current execution focus: general conversation coordination\n"
        return (
            f"Project: {project.name if project is not None else 'none'}\n"
            f"Conversation title: {conversation.title}\n"
            f"Project context:\n{project_context}\n\n"
            f"Recent transcript:\n{transcript}\n\n"
            f"Open tasks:\n{task_lines}\n\n"
            f"{task_focus}\n"
            f"Relevant memory:\n{memory_lines}\n\n"
            f"Current user message:\n{user_prompt}\n\n"
            "Keep the response human-readable. If you are blocked, explain why. If work is ongoing, summarize progress clearly."
        )

    def _refresh_conversation_state(self, conversation_id: str) -> None:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            return
        pending_approvals = self.policies.pending_for_conversation(conversation_id)
        active_jobs = [
            job
            for job in self.jobs.list_for_conversation(conversation_id)
            if job.status in {JobStatus.QUEUED.value, JobStatus.CLAIMED.value, JobStatus.RUNNING.value, JobStatus.WAITING.value}
        ]
        if pending_approvals:
            conversation.status = ConversationStatus.BLOCKED.value
        elif active_jobs:
            conversation.status = ConversationStatus.WAITING_AGENT.value
        else:
            conversation.status = ConversationStatus.ACTIVE.value
        conversation.updated_at = _utcnow()
        self.db.flush()

    def _maybe_transition_task_on_job_start(self, job: Job) -> None:
        if job.task_id is None or job.agent_key is None:
            return
        task = self.tasks.get(job.task_id)
        if task is None:
            return
        target = {
            "principal": TaskStatus.PLANNED,
            "specialist": TaskStatus.IN_PROGRESS,
            "qa": TaskStatus.TESTING,
            "github": TaskStatus.PLANNED,
            "devops": TaskStatus.BLOCKED,
            "po_pm": TaskStatus.PLANNED,
        }.get(job.agent_key)
        if target is not None:
            self._transition_task(task, target)

    def _mark_task_visible_progress(self, task_id: str, agent_key: str) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            return
        target = {
            "principal": None,
            "specialist": TaskStatus.IN_PROGRESS,
            "qa": TaskStatus.TESTING,
            "github": TaskStatus.PLANNED,
            "devops": TaskStatus.BLOCKED,
            "po_pm": TaskStatus.PLANNED,
        }.get(agent_key)
        if target is not None:
            self._transition_task(task, target)

    def _maybe_transition_task_on_job_success(self, job: Job) -> None:
        if job.task_id is None or job.agent_key is None:
            return
        task = self.tasks.get(job.task_id)
        if task is None:
            return
        target = {
            "specialist": TaskStatus.TESTING if task.kind != TaskKind.PIPELINE.value else TaskStatus.IN_PROGRESS,
            "qa": TaskStatus.DONE,
            "github": TaskStatus.PLANNED,
            "devops": TaskStatus.BLOCKED,
            "po_pm": TaskStatus.PLANNED,
            "principal": None,
        }.get(job.agent_key)
        if target is not None:
            self._transition_task(task, target)

    def _maybe_transition_task_on_job_failure(self, job: Job) -> None:
        if job.task_id is None:
            return
        task = self.tasks.get(job.task_id)
        if task is not None:
            self._transition_task(task, TaskStatus.FAILED)

    def _transition_task(self, task: Task, status: TaskStatus) -> None:
        try:
            self.tasks.set_status(task, status)
        except ValueError:
            return

    @staticmethod
    def _priority_for_agent(agent_key: str | None) -> int:
        return {
            "principal": 10,
            "po_pm": 20,
            "specialist": 30,
            "qa": 40,
            "github": 50,
            "devops": 60,
        }.get(agent_key or "", 100)

    @staticmethod
    def _task_title_from_content(content: str) -> str:
        trimmed = content.strip().rstrip(".")
        if len(trimmed) > 72:
            trimmed = trimmed[:69] + "..."
        return trimmed[:1].upper() + trimmed[1:]

    @staticmethod
    def _select_cwd(project: Project | None) -> str | None:
        if project is None:
            return None
        for repo in project.repositories:
            if repo.is_primary and repo.local_path:
                return repo.local_path
        return None
