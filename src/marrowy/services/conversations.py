from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy import delete
from sqlalchemy.orm import Session

from marrowy.db.models import ApprovalRequest
from marrowy.db.models import Conversation
from marrowy.db.models import ConversationMessage
from marrowy.db.models import ConversationParticipant
from marrowy.db.models import Job
from marrowy.db.models import Project
from marrowy.db.models import Task
from marrowy.db.models import DomainEvent
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
from marrowy.services.domain_actions import AddAgentContract
from marrowy.services.domain_actions import AgentProfileContract
from marrowy.services.domain_actions import DomainActionService
from marrowy.services.domain_actions import SubtaskContract
from marrowy.services.domain_actions import TaskContract
from marrowy.services.domain_actions import TaskUpdateContract
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


@dataclass(slots=True)
class RequestedAgentAction:
    agent_key: str | None = None
    display_name: str | None = None
    should_create_profile: bool = False


class ConversationService:
    def __init__(self, db: Session, provider: ModelProvider) -> None:
        self.db = db
        self.provider = provider
        self.events = EventService(db)
        self.tasks = TaskService(db)
        self.domain_actions = DomainActionService(db)
        self.policies = PolicyService(db)
        self.memory = MemoryService(db)
        self.jobs = JobService(db)

    def list_conversations(self) -> list[Conversation]:
        return list(self.db.scalars(select(Conversation).order_by(Conversation.updated_at.desc())))

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return self.db.get(Conversation, conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            return False

        self.db.execute(delete(Job).where(Job.conversation_id == conversation_id))
        self.db.execute(delete(ApprovalRequest).where(ApprovalRequest.conversation_id == conversation_id))
        self.db.execute(delete(DomainEvent).where(DomainEvent.conversation_id == conversation_id))
        self.db.execute(delete(Task).where(Task.conversation_id == conversation_id))
        self.db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id))
        self.db.execute(delete(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id))
        self.db.delete(conversation)
        self.db.flush()
        return True

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
        result = self.domain_actions.add_agent_to_room(
            conversation_id=conversation_id,
            contract=AddAgentContract(agent_key=agent_key),
        )
        if result.added:
            result.participant.last_activity_at = _utcnow()
        return result.participant

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
                f"Approval {approval_id} was {'approved' if decision == 'approve' else 'rejected'}. "
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

        local_status_reply = self._maybe_build_local_status_reply(context, content)
        if local_status_reply is not None:
            created_messages.append(local_status_reply)
            self._refresh_conversation_state(conversation_id)
            context.conversation.updated_at = _utcnow()
            self.db.flush()
            return created_messages

        plan = self._derive_orchestration_plan(context, content, user_message)
        created_messages.extend(plan.messages)

        scheduled_ids: set[str] = set()
        for turn in plan.scheduled_turns:
            if turn.participant.id in scheduled_ids:
                continue
            scheduled_ids.add(turn.participant.id)
            if turn.task_id and turn.participant.agent_key:
                self._mark_task_visible_progress(turn.task_id, turn.participant.agent_key)
            job, _ = self.jobs.enqueue(
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
            stream_message = self._ensure_stream_message(
                conversation_id=context.conversation.id,
                participant=turn.participant,
                job=job,
            )
            payload_json = dict(job.payload_json or {})
            payload_json["streamMessageId"] = stream_message.id
            job.payload_json = payload_json
            created_messages.append(stream_message)

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
        stream_message = self._ensure_stream_message(
            conversation_id=conversation.id,
            participant=participant,
            job=job,
        )
        self.jobs.mark_running(job, summary=job.summary)
        self._set_stream_state(stream_message, "thinking")
        self._maybe_transition_task_on_job_start(job)
        self._refresh_conversation_state(conversation.id)
        self.db.commit()

        async def on_provider_event(event_type: str, text: str) -> None:
            if event_type == "final":
                return
            progress_text = text.strip()
            if not progress_text:
                return
            if event_type == "assistant_delta":
                self._append_stream_content(stream_message, progress_text)
            else:
                if event_type not in {"status"} or progress_text not in {"Thread started.", "Turn started."}:
                    self.jobs.append_progress(job, text=progress_text, progress_type=event_type)
                    self._append_stream_thinking(stream_message, event_type, progress_text)
            self.db.commit()

        try:
            result, thread_id = await self.provider.complete(
                role_name=profile.display_name,
                instructions=profile.instructions,
                prompt=prompt,
                thread_id=participant.bridge_thread_id,
                cwd=self._select_cwd(self.db.get(Project, conversation.project_id) if conversation.project_id else None),
                effort=profile.effort,
                event_handler=on_provider_event,
            )
        except Exception as exc:
            error_text = self._describe_provider_failure(exc)
            self.jobs.fail(job, error=error_text)
            self._set_stream_state(stream_message, "error")
            self.add_message(
                conversation_id=conversation.id,
                author_name=profile.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content=f"I could not complete my turn because the provider failed: {error_text}",
                message_type=MessageKind.AGENT.value,
                participant_id=participant.id,
                metadata={"jobId": job.id, "error": error_text},
            )
            self._maybe_transition_task_on_job_failure(job)
            self._add_failure_follow_up(
                conversation=conversation,
                participant=participant,
                job=job,
                error_text=error_text,
            )
            self._refresh_conversation_state(conversation.id)
            self.db.commit()
            return

        if thread_id and participant.bridge_thread_id != thread_id:
            participant.bridge_thread_id = thread_id
        content = result.text.strip()
        content, applied_updates, task_update_errors = self._apply_task_update_directives(
            participant=participant,
            conversation=conversation,
            content=content,
            job=job,
        )
        self._finalize_stream_message(
            stream_message,
            content=content,
            metadata_updates={
                "commentary": result.commentary,
                "actions": result.actions,
                "taskUpdates": applied_updates,
                "taskUpdateErrors": task_update_errors,
            },
        )
        if applied_updates:
            summary = ", ".join(f"{item['taskId']} ({', '.join(item['updatedFields'])})" for item in applied_updates)
            self.add_message(
                conversation_id=conversation.id,
                author_name="Marrowy",
                author_kind=ParticipantKind.AGENT.value,
                content=f"Applied task updates: {summary}",
                message_type=MessageKind.SYSTEM.value,
                metadata={"jobId": job.id, "domainAction": "update_task", "updates": applied_updates},
            )
        for error_text in task_update_errors:
            self.add_message(
                conversation_id=conversation.id,
                author_name="Marrowy",
                author_kind=ParticipantKind.AGENT.value,
                content=f"Task update could not be applied: {error_text}",
                message_type=MessageKind.SYSTEM.value,
                metadata={"jobId": job.id, "domainAction": "update_task_error"},
            )
        self.jobs.succeed(
            job,
            result={
                "threadId": thread_id,
                "commentary": result.commentary,
                "actions": result.actions,
                "taskUpdates": applied_updates,
                "taskUpdateErrors": task_update_errors,
            },
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

    @staticmethod
    def _describe_provider_failure(exc: Exception) -> str:
        detail = str(exc).strip()
        if detail:
            return detail
        return f"{exc.__class__.__name__}: the provider ended the turn without a final response."

    def _add_failure_follow_up(
        self,
        *,
        conversation: Conversation,
        participant: ConversationParticipant,
        job: Job,
        error_text: str,
    ) -> None:
        principal = next(
            (
                item
                for item in self.list_participants(conversation.id)
                if item.agent_key == "principal"
            ),
            None,
        )
        if principal is None:
            return
        task_note = ""
        if job.task_id:
            task = self.tasks.get(job.task_id)
            if task is not None:
                task_note = f" Task `{task.id}` is now in `{task.status}`."
        if participant.agent_key and participant.agent_key != "principal":
            direct_hint = f" If you want to talk directly to them next, mention `@{participant.agent_key}`."
            content = (
                f"{participant.display_name} hit an execution problem and could not finish the last turn.\n\n"
                f"Error recorded: {error_text}\n\n"
                f"We can retry, reduce the scope, or continue with another agent.{task_note}{direct_hint}"
            )
        else:
            content = (
                "I hit an execution problem while preparing the last reply.\n\n"
                f"Error recorded: {error_text}\n\n"
                "You can ask me to retry, narrow the request, or ask for a room status update instead."
            )
        self.add_message(
            conversation_id=conversation.id,
            author_name=principal.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content=content,
            message_type=MessageKind.AGENT.value,
            participant_id=principal.id,
            metadata={"jobId": job.id, "failureFollowUp": True, "failedAgentKey": participant.agent_key},
        )

    def _derive_orchestration_plan(
        self,
        context: MessageContext,
        content: str,
        created_by_message: ConversationMessage,
    ) -> OrchestrationPlan:
        text = _normalize_text(content)
        plan = OrchestrationPlan()

        for requested in self._requested_agent_actions(text, content):
            profile_message: ConversationMessage | None = None
            agent_key = requested.agent_key
            if requested.should_create_profile:
                contract = self._agent_profile_contract_from_label(requested.display_name or requested.agent_key or "Custom Agent")
                if agent_key:
                    contract = contract.model_copy(update={"key": agent_key})
                profile_result = self.domain_actions.create_agent_profile(contract)
                agent_key = profile_result.profile.key
                if profile_result.created:
                    profile_message = self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=(
                            f"Created new agent profile `{profile_result.profile.key}` "
                            f"({profile_result.profile.display_name}) and made it available to the room."
                        ),
                        message_type=MessageKind.SYSTEM.value,
                        participant_id=context.principal.id,
                        metadata={"agentKey": profile_result.profile.key, "domainAction": "create_agent_profile"},
                    )
                else:
                    profile_message = self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=(
                            f"Reusing existing agent profile `{profile_result.profile.key}` "
                            f"({profile_result.profile.display_name}) instead of creating a duplicate."
                        ),
                        message_type=MessageKind.SYSTEM.value,
                        participant_id=context.principal.id,
                        metadata={"agentKey": profile_result.profile.key, "domainAction": "reuse_agent_profile"},
                    )
            if agent_key is None:
                continue
            if profile_message is not None:
                plan.messages.append(profile_message)
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
                            f"Created pipeline task {root_task.id} with {len(stage_tasks)} delivery stages. "
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
                        content=f"Reusing active pipeline task {root_task.id} instead of creating a duplicate.",
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
                        content=f"Created task {task.id} and mapped it to Agent Specialist.",
                        message_type=MessageKind.AGENT.value,
                        participant_id=context.principal.id,
                        metadata={"taskId": task.id},
                    )
                )
            else:
                plan.messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=f"Reusing existing task {task.id} instead of creating a duplicate.",
                        message_type=MessageKind.SYSTEM.value,
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
                        f"{'Created' if created else 'Reused'} {len(subtasks)} subtasks under task {root_task.id} "
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
                    content=f"Production deploy is blocked pending approval {approval.id}.",
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

    def _maybe_build_local_status_reply(self, context: MessageContext, content: str) -> ConversationMessage | None:
        text = _normalize_text(content)
        task_tokens = [
            "temos task aberta",
            "tem task aberta",
            "tem tarefa aberta",
            "temos tarefa aberta",
            "have an open task",
            "open task",
            "what task is open",
            "quais tasks estao abertas",
            "quais tarefas estao abertas",
        ]
        status_tokens = [
            "ele finalizou",
            "ele terminou",
            "o que ele disse",
            "oq ele disse",
            "did he finish",
            "what did he say",
            "still running",
            "status do especialista",
        ]
        direct_tokens = [
            "como eu faco para falar diretamente",
            "como eu faço para falar diretamente",
            "how do i talk directly",
            "how can i talk directly",
        ]
        if not any(token in text for token in [*task_tokens, *status_tokens, *direct_tokens]):
            return None

        active_tasks = [
            task
            for task in context.tasks
            if task.status not in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}
        ]
        if any(token in text for token in task_tokens):
            if active_tasks:
                lines = ["Sim, ja existe trabalho aberto nesta conversa:"]
                for task in active_tasks[:5]:
                    owner = task.assigned_agent_key or "unassigned"
                    lines.append(f"- `{task.id}` [{task.status}] {task.title} -> {owner}")
                if len(active_tasks) > 5:
                    lines.append(f"- e mais {len(active_tasks) - 5} task(s) ativas")
            else:
                lines = ["Nao ha task aberta no momento nesta conversa."]
            return self.add_message(
                conversation_id=context.conversation.id,
                author_name=context.principal.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content="\n".join(lines),
                message_type=MessageKind.AGENT.value,
                participant_id=context.principal.id,
                metadata={"localStatusReply": True, "replyKind": "task-status"},
            )

        non_principal_participants = [
            participant
            for participant in self.list_participants(context.conversation.id)
            if participant.agent_key and participant.agent_key != "principal"
        ]
        if not non_principal_participants:
            return None

        active_statuses = {
            JobStatus.QUEUED.value,
            JobStatus.CLAIMED.value,
            JobStatus.RUNNING.value,
            JobStatus.WAITING.value,
        }
        jobs_by_agent = {
            participant.agent_key: [
                job for job in self.jobs.list_for_conversation(context.conversation.id) if job.agent_key == participant.agent_key
            ]
            for participant in non_principal_participants
        }
        target = non_principal_participants[-1]
        active_job = next((job for job in reversed(jobs_by_agent.get(target.agent_key, [])) if job.status in active_statuses), None)
        last_job = next(iter(reversed(jobs_by_agent.get(target.agent_key, []))), None)
        latest_message = next(
            (
                message
                for message in reversed(self.list_messages(context.conversation.id))
                if message.participant_id == target.id and message.message_type == MessageKind.AGENT.value
            ),
            None,
        )

        lines: list[str] = []
        if active_job is not None:
            lines.append(
                f"{target.display_name} ainda nao finalizou. O worker atual esta em `{active_job.status}` com resumo: {active_job.summary}"
            )
        elif latest_message is not None:
            preview = latest_message.content.strip().splitlines()
            snippet = " ".join(preview[1:] if len(preview) > 1 else preview)[:280]
            lines.append(f"Ultima resposta registrada de {target.display_name}: {snippet}")
        elif last_job is not None and last_job.status == JobStatus.FAILED.value:
            error = (last_job.last_error or "").strip() or "The previous turn failed before a final response was produced."
            lines.append(f"{target.display_name} nao conseguiu concluir o ultimo turno. Motivo registrado: {error}")
        else:
            lines.append(f"Ainda nao existe uma resposta final registrada de {target.display_name} nesta conversa.")

        if any(token in text for token in direct_tokens):
            lines.append(
                "Para falar diretamente com esse agente, mencione `@specialist` ou escreva algo como `Agent Specialist, analise este frontend...`."
            )
        elif target.agent_key:
            lines.append(
                f"Se quiser falar direto com ele no proximo turno, mencione `@{target.agent_key}` ou use o nome `{target.display_name}` no pedido."
            )

        return self.add_message(
            conversation_id=context.conversation.id,
            author_name=context.principal.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content="\n\n".join(lines),
            message_type=MessageKind.AGENT.value,
            participant_id=context.principal.id,
            metadata={"localStatusReply": True, "targetAgentKey": target.agent_key},
        )

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
        participant = self.domain_actions.add_agent_to_room(
            conversation_id=context.conversation.id,
            contract=AddAgentContract(agent_key=agent_key, reason=source_content),
        ).participant
        participant.last_activity_at = _utcnow()
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
                content=f"Added {participant.display_name} to the room.",
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
        role_tokens = self._agent_aliases()
        for key, tokens in role_tokens.items():
            if any(token in text for token in tokens + [f"@{key}"]):
                ordered_keys.append(key)
        participants_by_key = {participant.agent_key: participant for participant in self.list_participants(context.conversation.id) if participant.agent_key}
        return [participants_by_key[key] for key in ordered_keys if key in participants_by_key]

    def _requested_agent_actions(self, text: str, source_content: str) -> list[RequestedAgentAction]:
        additions: list[RequestedAgentAction] = []
        action_intents = [
            "add",
            "bring in",
            "hire",
            "create agent",
            "create a new agent",
            "talk with",
            "talk to",
            "ask",
            "have",
            "contrate",
            "adicione",
            "adiciona",
            "crie um agent",
            "crie um agente",
            "crie um novo agent",
            "crie um novo agente",
            "falar com",
            "trocar uma ideia com",
            "quero um agente",
            "quero um agent",
            "preciso de um agente",
            "preciso de um agent",
        ]
        if not any(token in text for token in action_intents):
            return additions

        seen: set[str] = set()
        aliases = self._agent_aliases()
        for key, tokens in aliases.items():
            if any(token in text for token in tokens):
                seen.add(key)
                additions.append(RequestedAgentAction(agent_key=key))

        pattern = re.compile(
            r"(?:create|add|hire|bring in|contrate|adicione|crie)\s+(?:a\s+|an\s+|um\s+|uma\s+|novo\s+|nova\s+|new\s+)?(?:agent|agente)\s+([a-z0-9/_ -]{3,80})",
            re.IGNORECASE,
        )
        for match in pattern.findall(source_content):
            label = self._trim_agent_label_candidate(match)
            if not label:
                continue
            mapped = self._map_agent_label(label)
            if mapped is not None:
                if mapped not in seen:
                    seen.add(mapped)
                    additions.append(RequestedAgentAction(agent_key=mapped))
                continue
            display_name = self._display_name_for_agent_label(label)
            key = self._agent_key_for_label(label)
            if key in seen:
                continue
            seen.add(key)
            additions.append(
                RequestedAgentAction(
                    agent_key=key,
                    display_name=display_name,
                    should_create_profile=True,
                )
            )
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
        contract = self._task_contract_from_content(context=context, content=content, kind=TaskKind.PIPELINE.value)
        result = self.domain_actions.create_task(
            conversation_id=context.conversation.id,
            project_id=context.conversation.project_id,
            contract=contract,
            created_by_message_id=message_id,
        )
        return result.task, result.subtasks, result.created

    def _ensure_simple_task(self, context: MessageContext, content: str, message_id: str) -> tuple[Task, bool]:
        contract = self._task_contract_from_content(context=context, content=content, kind=TaskKind.SIMPLE.value)
        result = self.domain_actions.create_task(
            conversation_id=context.conversation.id,
            project_id=context.conversation.project_id,
            contract=contract,
            created_by_message_id=message_id,
        )
        return result.task, result.created

    def _ensure_decomposition(self, context: MessageContext, root_task: Task, message_id: str) -> tuple[list[Task], bool]:
        result = self.domain_actions.create_subtasks(
            conversation_id=context.conversation.id,
            project_id=context.conversation.project_id,
            parent_task_id=root_task.id,
            created_by_message_id=message_id,
            contracts=[
                SubtaskContract(
                    title="Clarify scope and acceptance criteria",
                    goal="Clarify v1 boundaries and capture acceptance criteria for the task.",
                    assigned_agent_key="po_pm",
                    acceptance_criteria_markdown=root_task.acceptance_criteria_markdown,
                    repository_name=root_task.repository_name,
                    branch_name=root_task.branch_name,
                    environment_name=root_task.environment_name,
                    gmud_reference=root_task.gmud_reference,
                ),
                SubtaskContract(
                    title="Implement the core happy path",
                    goal="Build the main user flow and core implementation slice.",
                    assigned_agent_key="specialist",
                    repository_name=root_task.repository_name,
                    branch_name=root_task.branch_name,
                    environment_name=root_task.environment_name,
                ),
                SubtaskContract(
                    title="Validate the critical path",
                    goal="Confirm the core flow works and document evidence.",
                    assigned_agent_key="qa",
                    repository_name=root_task.repository_name,
                    branch_name=root_task.branch_name,
                    environment_name=root_task.environment_name,
                ),
                SubtaskContract(
                    title="Prepare repo and delivery hygiene",
                    goal="Capture repository, release, and deployment follow-up.",
                    assigned_agent_key="github",
                    repository_name=root_task.repository_name,
                    branch_name=root_task.branch_name,
                    environment_name=root_task.environment_name,
                    approval_required=root_task.approval_required,
                    gmud_reference=root_task.gmud_reference,
                ),
            ],
        )
        return result.subtasks, result.created

    def _wants_pipeline_creation(self, text: str) -> bool:
        return (
            ("pipeline" in text and any(token in text for token in ["create", "set up", "build", "prepare", "start", "crie", "monta", "prepare"]))
            or any(token in text for token in ["create project", "new mvp", "crie um projeto", "crie o pipeline", "task pipeline", "pipeline de task", "pipeline de tarefas"])
        )

    def _wants_simple_task_creation(self, text: str) -> bool:
        return any(
            token in text
            for token in [
                "create task",
                "create a task",
                "create tasks",
                "separate task",
                "follow-up task",
                "crie a task",
                "crie uma task",
                "crie as tasks",
                "crie a tarefa",
                "crie uma tarefa",
                "crie as tarefas",
                "abra uma task",
                "abrir uma task",
            ]
        )

    def _wants_decomposition(self, text: str) -> bool:
        return any(
            token in text
            for token in [
                "decompose",
                "break down",
                "refine the mvp",
                "refine into",
                "small incremental steps",
                "subtasks",
                "crie subtasks",
                "sub tarefas",
                "subtarefas",
                "quebre em etapas",
                "quebre em subtasks",
                "quebre em subtarefas",
                "decomponha",
            ]
        )

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
        visible_messages = [
            message
            for message in list(messages)
            if not message.metadata_json.get("streamMessage")
        ]
        transcript = "\n".join(f"{message.author_name}: {message.content}" for message in visible_messages[-10:])
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
            f"Task update directive contract for {participant.display_name}:\n{self._task_update_tool_contract(participant.agent_key or 'principal')}\n\n"
            "Keep the response human-readable. If you are blocked, explain why. If work is ongoing, summarize progress clearly. "
            "Important: Marrowy domain actions such as creating tasks, creating subtasks, adding agents, or creating agent profiles "
            "are executed outside the model. Do not claim those actions happened unless the transcript already shows that Marrowy confirmed them. "
            "If you need to update an existing task, use the task update directive exactly as documented and Marrowy will apply it."
        )

    def _ensure_stream_message(
        self,
        *,
        conversation_id: str,
        participant: ConversationParticipant,
        job: Job,
    ) -> ConversationMessage:
        stream_message_id = (job.payload_json or {}).get("streamMessageId")
        if isinstance(stream_message_id, str):
            existing = self.db.get(ConversationMessage, stream_message_id)
            if existing is not None:
                return existing
        message = self.add_message(
            conversation_id=conversation_id,
            author_name=participant.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content="",
            message_type=MessageKind.AGENT.value,
            participant_id=participant.id,
            metadata={
                "jobId": job.id,
                "streamMessage": True,
                "streamState": "waiting",
                "thinking": [],
            },
        )
        payload_json = dict(job.payload_json or {})
        payload_json["streamMessageId"] = message.id
        job.payload_json = payload_json
        self.db.flush()
        return message

    def _update_message(self, message: ConversationMessage, *, content: str | None = None, metadata: dict | None = None) -> None:
        if content is not None:
            message.content = content
        if metadata is not None:
            message.metadata_json = metadata
        self.db.flush()
        self.events.emit(
            "conversation.message.updated",
            conversation_id=message.conversation_id,
            payload={"messageId": message.id, "messageType": message.message_type},
        )

    def _set_stream_state(self, message: ConversationMessage, state: str) -> None:
        metadata = dict(message.metadata_json or {})
        metadata["streamState"] = state
        self._update_message(message, metadata=metadata)

    def _append_stream_content(self, message: ConversationMessage, delta: str) -> None:
        metadata = dict(message.metadata_json or {})
        metadata["streamState"] = "streaming"
        content = f"{message.content}{delta}"
        self._update_message(message, content=content, metadata=metadata)

    def _append_stream_thinking(self, message: ConversationMessage, progress_type: str, text: str) -> None:
        metadata = dict(message.metadata_json or {})
        thinking = list(metadata.get("thinking", []))
        entry = {"type": progress_type, "text": text}
        if not thinking or thinking[-1] != entry:
            thinking.append(entry)
        metadata["thinking"] = thinking[-20:]
        if metadata.get("streamState") != "streaming":
            metadata["streamState"] = "thinking"
        self._update_message(message, metadata=metadata)

    def _finalize_stream_message(self, message: ConversationMessage, *, content: str, metadata_updates: dict | None = None) -> None:
        metadata = dict(message.metadata_json or {})
        metadata["streamState"] = "final"
        if metadata_updates:
            metadata.update(metadata_updates)
        self._update_message(message, content=content, metadata=metadata)

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

    def _task_contract_from_content(self, *, context: MessageContext, content: str, kind: str) -> TaskContract:
        lowered = _normalize_text(content)
        default_agent = {
            TaskKind.PIPELINE.value: "po_pm",
            TaskKind.SIMPLE.value: "specialist",
            TaskKind.SUBTASK.value: "specialist",
        }.get(kind, "specialist")
        approval_required = "aprova" in lowered or "approval" in lowered or "production" in lowered or "gmud" in lowered
        repository_name = self._primary_repository_name(context.project)
        environment_name = self._default_environment_name(context.project, lowered)
        acceptance = None
        if "acceptance criteria" in lowered or "criterios de aceite" in lowered or "critérios de aceite" in lowered:
            acceptance = "Honor the acceptance criteria explicitly requested in the user prompt."
        return TaskContract(
            title=self._task_title_from_content(content),
            goal=content.strip(),
            kind=kind,  # type: ignore[arg-type]
            scope=content.strip(),
            acceptance_criteria_markdown=acceptance,
            repository_name=repository_name,
            branch_name="main" if repository_name else None,
            environment_name=environment_name,
            assigned_agent_key=default_agent,
            details_markdown=f"Requested from chat:\n\n{content.strip()}",
            approval_required=approval_required,
            observations_markdown="Created from natural-language chat request via Marrowy domain actions.",
        )

    @staticmethod
    def _agent_aliases() -> dict[str, list[str]]:
        return {
            "specialist": [
                "@specialist",
                "agent specialist",
                "agente especialista",
                "specialist",
                "especialista",
            ],
            "qa": ["@qa", "agent qa", "agente qa", "qa", "quality assurance", "qualidade"],
            "github": ["@github", "agent github", "agente github", "github"],
            "devops": ["@devops", "agent devops", "agente devops", "devops", "infra", "platform"],
            "po_pm": [
                "@po",
                "@pm",
                "agent po/pm",
                "agent pm",
                "agent po",
                "agente po/pm",
                "agente pm",
                "agente po",
                "po/pm",
                "product",
                "discovery",
            ],
            "frontend": ["@frontend", "agent frontend", "agente frontend", "frontend", "front-end", "ui engineer"],
            "backend_python": ["@backend", "agent backend", "agente backend", "backend", "back-end", "backend python"],
        }

    def _map_agent_label(self, label: str) -> str | None:
        normalized = _normalize_text(label)
        for key, tokens in self._agent_aliases().items():
            if normalized == key or any(normalized == token or normalized in token or token in normalized for token in tokens):
                return key
        return None

    def _agent_key_for_label(self, label: str) -> str:
        mapped = self._map_agent_label(label)
        if mapped is not None:
            return mapped
        sanitized = re.sub(r"[^a-z0-9]+", "_", _normalize_text(label)).strip("_")
        return sanitized or "custom_agent"

    @staticmethod
    def _trim_agent_label_candidate(value: str) -> str:
        label = _normalize_text(value)
        for separator in [" para ", " to ", " and ", " e ", ",", ".", " na room", " in the room"]:
            if separator in label:
                label = label.split(separator, 1)[0]
        return label.strip()

    def _display_name_for_agent_label(self, label: str) -> str:
        mapped = self._map_agent_label(label)
        if mapped is not None:
            return get_agent_profile(mapped).display_name
        normalized = " ".join(part.capitalize() for part in re.split(r"[^a-z0-9]+", _normalize_text(label)) if part)
        if normalized.lower().startswith("agent "):
            return normalized
        return f"Agent {normalized}"

    def _agent_profile_contract_from_label(self, label: str) -> AgentProfileContract:
        display_name = self._display_name_for_agent_label(label)
        agent_key = self._agent_key_for_label(label)
        lowered = _normalize_text(label)
        can_create_tasks = any(token in lowered for token in ["pm", "po", "product", "specialist", "engineer", "developer", "frontend", "backend"])
        can_manage_repo = any(token in lowered for token in ["github", "git", "repo"])
        can_manage_deploy = any(token in lowered for token in ["devops", "infra", "platform", "deploy"])
        summary = f"Specialized agent focused on {label} work."
        instructions = (
            f"You are {display_name}. Focus on {label} responsibilities, keep updates clear, and only claim domain "
            "actions that Marrowy has actually confirmed in the room state."
        )
        return AgentProfileContract(
            key=agent_key,
            display_name=display_name,
            summary=summary,
            instructions=instructions,
            effort="medium",
            can_create_tasks=can_create_tasks,
            can_manage_repo=can_manage_repo,
            can_manage_deploy=can_manage_deploy,
        )

    @staticmethod
    def _primary_repository_name(project: Project | None) -> str | None:
        if project is None:
            return None
        for repo in project.repositories:
            if repo.is_primary:
                return repo.name
        if project.repositories:
            return project.repositories[0].name
        return None

    @staticmethod
    def _default_environment_name(project: Project | None, lowered_text: str) -> str | None:
        if project is None or not project.environments:
            return None
        if "production" in lowered_text or "producao" in lowered_text or "produção" in lowered_text:
            for env in project.environments:
                if env.name.lower() == "production":
                    return env.name
        return project.environments[0].name

    @staticmethod
    def _select_cwd(project: Project | None) -> str | None:
        if project is None:
            return None
        for repo in project.repositories:
            if repo.is_primary and repo.local_path:
                return repo.local_path
        return None

    def _apply_task_update_directives(
        self,
        *,
        participant: ConversationParticipant,
        conversation: Conversation,
        content: str,
        job: Job,
    ) -> tuple[str, list[dict[str, object]], list[str]]:
        applied: list[dict[str, object]] = []
        errors: list[str] = []
        cleaned = content
        for raw in self._extract_task_update_payloads(content):
            try:
                payload = json.loads(raw)
                contract = TaskUpdateContract(**payload)
                result = self.domain_actions.update_task(
                    actor_agent_key=participant.agent_key or "principal",
                    contract=contract,
                )
                if result.updated_fields:
                    applied.append({"taskId": result.task.id, "updatedFields": result.updated_fields})
            except Exception as exc:
                errors.append(str(exc).strip() or exc.__class__.__name__)
        cleaned = re.sub(r"\[marrowy-task-update\s+\{.*?\}\]", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if not cleaned:
            cleaned = f"[{participant.display_name}]"
        return cleaned, applied, errors

    @staticmethod
    def _extract_task_update_payloads(content: str) -> list[str]:
        return re.findall(r"\[marrowy-task-update\s+(\{.*?\})\]", content, flags=re.DOTALL)

    def _task_update_tool_contract(self, agent_key: str) -> str:
        allowed = {
            "principal": "scope, acceptance_criteria_markdown, assigned_agent_key, updates_markdown, blockers_markdown, observations_markdown",
            "po_pm": "scope, acceptance_criteria_markdown, assigned_agent_key, updates_markdown, blockers_markdown, observations_markdown",
            "specialist": "updates_markdown, blockers_markdown, result_markdown, observations_markdown",
            "qa": "updates_markdown, blockers_markdown, result_markdown, observations_markdown, evidence_markdown",
            "github": "repository_name, branch_name, updates_markdown, observations_markdown, evidence_markdown",
            "devops": "environment_name, updates_markdown, blockers_markdown, observations_markdown, evidence_markdown, gmud_reference",
            "frontend": "updates_markdown, blockers_markdown, result_markdown, observations_markdown, evidence_markdown",
            "backend_python": "updates_markdown, blockers_markdown, result_markdown, observations_markdown, evidence_markdown",
        }.get(agent_key, "updates_markdown, observations_markdown")
        return (
            "When you need to edit an existing task, append a single-line directive like "
            "`[marrowy-task-update {\"task_id\":\"<task-id>\",\"updates_markdown\":\"...\"}]` to the end of your reply. "
            f"Allowed fields for this role: {allowed}. "
            "Do not try to change title, goal, project, kind, or arbitrary status through this directive."
        )
