from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import ApprovalRequest
from marrowy.db.models import Conversation
from marrowy.db.models import ConversationMessage
from marrowy.db.models import ConversationParticipant
from marrowy.db.models import Project
from marrowy.domain.agents import AGENT_PROFILES
from marrowy.domain.agents import AgentProfile
from marrowy.domain.agents import get_agent_profile
from marrowy.domain.enums import ConversationStatus
from marrowy.domain.enums import MessageKind
from marrowy.domain.enums import MemoryScope
from marrowy.domain.enums import ParticipantKind
from marrowy.domain.enums import TaskStatus
from marrowy.providers.base import ModelProvider
from marrowy.services.events import EventService
from marrowy.services.memory import MemoryService
from marrowy.services.policies import PolicyService
from marrowy.services.tasks import TaskService


@dataclass(slots=True)
class MessageContext:
    conversation: Conversation
    project: Project | None
    principal: ConversationParticipant
    participants: list[ConversationParticipant]
    pending_approvals: list[ApprovalRequest]


class ConversationService:
    def __init__(self, db: Session, provider: ModelProvider) -> None:
        self.db = db
        self.provider = provider
        self.events = EventService(db)
        self.tasks = TaskService(db)
        self.policies = PolicyService(db)
        self.memory = MemoryService(db)

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
        )
        principal = ConversationParticipant(
            conversation_id=conversation.id,
            kind=ParticipantKind.AGENT.value,
            agent_key="principal",
            display_name=AGENT_PROFILES["principal"].display_name,
        )
        self.db.add_all([user, principal])
        self.db.flush()
        self.events.emit("conversation.created", conversation_id=conversation.id, payload={"conversationId": conversation.id})
        self.events.emit("agent.joined", conversation_id=conversation.id, payload={"agentKey": "principal"})
        self.add_message(
            conversation_id=conversation.id,
            author_name=principal.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content="I am online as Agent Principal. I will coordinate this conversation, tasks, and approvals.",
            message_type=MessageKind.SYSTEM.value,
            participant_id=principal.id,
        )
        return conversation

    def add_agent(self, conversation_id: str, agent_key: str) -> ConversationParticipant:
        profile = get_agent_profile(agent_key)
        existing = self.db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.agent_key == agent_key,
            )
        )
        if existing is not None:
            return existing
        participant = ConversationParticipant(
            conversation_id=conversation_id,
            kind=ParticipantKind.AGENT.value,
            agent_key=agent_key,
            display_name=profile.display_name,
        )
        self.db.add(participant)
        self.db.flush()
        self.events.emit("agent.joined", conversation_id=conversation_id, payload={"agentKey": agent_key})
        return participant

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

    def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        stmt = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id).order_by(ConversationMessage.created_at)
        return list(self.db.scalars(stmt))

    def list_participants(self, conversation_id: str) -> list[ConversationParticipant]:
        stmt = select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id).order_by(ConversationParticipant.joined_at)
        return list(self.db.scalars(stmt))

    def _message_context(self, conversation_id: str) -> MessageContext:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"conversation {conversation_id!r} not found")
        project = self.db.get(Project, conversation.project_id) if conversation.project_id else None
        participants = self.list_participants(conversation_id)
        principal = next(p for p in participants if p.agent_key == "principal")
        pending = self.policies.pending_for_conversation(conversation_id)
        return MessageContext(
            conversation=conversation,
            project=project,
            principal=principal,
            participants=participants,
            pending_approvals=pending,
        )

    async def handle_user_message(self, conversation_id: str, *, content: str, user_name: str) -> list[ConversationMessage]:
        context = self._message_context(conversation_id)
        user = next(p for p in context.participants if p.kind == ParticipantKind.USER.value)
        user_message = self.add_message(
            conversation_id=conversation_id,
            author_name=user_name,
            author_kind=ParticipantKind.USER.value,
            content=content,
            message_type=MessageKind.USER.value,
            participant_id=user.id,
        )

        created_messages: list[ConversationMessage] = [user_message]
        orchestration_notes = self._derive_orchestration_actions(context, content, user_message.id)
        for note in orchestration_notes:
            created_messages.append(note)

        for participant in self._participants_to_invoke(context, content):
            role_messages = await self._invoke_agent(
                conversation=context.conversation,
                project=context.project,
                participant=participant,
                user_prompt=content,
                context_messages=self.list_messages(conversation_id),
            )
            created_messages.extend(role_messages)

        context.conversation.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return created_messages

    def _derive_orchestration_actions(self, context: MessageContext, content: str, created_by_message_id: str) -> list[ConversationMessage]:
        text = content.lower()
        messages: list[ConversationMessage] = []
        if any(phrase in text for phrase in ["add qa", "bring in qa", "hire qa", "@qa"]):
            qa = self.add_agent(context.conversation.id, "qa")
            messages.append(
                self.add_message(
                    conversation_id=context.conversation.id,
                    author_name=context.principal.display_name,
                    author_kind=ParticipantKind.AGENT.value,
                    content=f"[Agent Principal] Added {qa.display_name} to the conversation and shared current task context.",
                    message_type=MessageKind.AGENT.value,
                    participant_id=context.principal.id,
                )
            )
        if any(phrase in text for phrase in ["add specialist", "bring in specialist", "@specialist"]):
            specialist = self.add_agent(context.conversation.id, "specialist")
            messages.append(
                self.add_message(
                    conversation_id=context.conversation.id,
                    author_name=context.principal.display_name,
                    author_kind=ParticipantKind.AGENT.value,
                    content=f"[Agent Principal] Added {specialist.display_name} and sent an implementation handoff.",
                    message_type=MessageKind.AGENT.value,
                    participant_id=context.principal.id,
                )
            )
        if any(phrase in text for phrase in ["add github", "bring in github", "@github"]):
            github = self.add_agent(context.conversation.id, "github")
            messages.append(
                self.add_message(
                    conversation_id=context.conversation.id,
                    author_name=context.principal.display_name,
                    author_kind=ParticipantKind.AGENT.value,
                    content=f"[Agent Principal] Added {github.display_name} to handle repository operations.",
                    message_type=MessageKind.AGENT.value,
                    participant_id=context.principal.id,
                )
            )
        if any(phrase in text for phrase in ["add devops", "bring in devops", "@devops"]):
            decision = self.policies.evaluate(project_id=context.conversation.project_id, agent_key="principal", action_type="agent.join.devops")
            if decision.requires_approval:
                approval = self.policies.create_approval(
                    conversation=context.conversation,
                    agent_key="principal",
                    action_type="agent.join.devops",
                    summary="Approve bringing Agent DevOps into this conversation.",
                    details={"reason": decision.reason},
                )
                messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=f"[Agent Principal] Approval required before adding Agent DevOps. Approval ID: {approval.id}",
                        message_type=MessageKind.APPROVAL.value,
                        participant_id=context.principal.id,
                        metadata={"approvalId": approval.id},
                    )
                )
            else:
                devops = self.add_agent(context.conversation.id, "devops")
                messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=f"[Agent Principal] Added {devops.display_name} for infrastructure and deploy work.",
                        message_type=MessageKind.AGENT.value,
                        participant_id=context.principal.id,
                    )
                )

        if any(token in text for token in ["task", "build", "create project", "mvp", "pipeline", "feature"]):
            if "pipeline" in text or "deploy" in text or "mvp" in text or "create project" in text:
                root, stages = self.tasks.create_pipeline_task(
                    conversation_id=context.conversation.id,
                    project_id=context.conversation.project_id,
                    title=self._task_title_from_content(content),
                    goal=content,
                    created_by_message_id=created_by_message_id,
                )
                messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=(
                            f"[Agent Principal] Created pipeline task {root.id} with {len(stages)} stages. "
                            "I will coordinate diagnosis, implementation, QA, and deploy readiness through the task board."
                        ),
                        message_type=MessageKind.AGENT.value,
                        participant_id=context.principal.id,
                        metadata={"taskId": root.id},
                    )
                )
            else:
                task = self.tasks.create_simple_task(
                    conversation_id=context.conversation.id,
                    project_id=context.conversation.project_id,
                    title=self._task_title_from_content(content),
                    goal=content,
                    assigned_agent_key="specialist",
                    created_by_message_id=created_by_message_id,
                )
                messages.append(
                    self.add_message(
                        conversation_id=context.conversation.id,
                        author_name=context.principal.display_name,
                        author_kind=ParticipantKind.AGENT.value,
                        content=f"[Agent Principal] Created task {task.id} and assigned it to Agent Specialist.",
                        message_type=MessageKind.AGENT.value,
                        participant_id=context.principal.id,
                        metadata={"taskId": task.id},
                    )
                )
        if "deploy" in text or "production" in text:
            latest_pipeline = next((task for task in self.tasks.list_for_conversation(context.conversation.id) if task.kind == "pipeline"), None)
            approval = self.policies.create_approval(
                conversation=context.conversation,
                agent_key="principal",
                action_type="deploy.production",
                summary="Approve production deployment for the active workstream.",
                details={"environment": "production"},
                task_id=latest_pipeline.id if latest_pipeline else None,
            )
            if latest_pipeline is not None:
                self.tasks.set_status(latest_pipeline, TaskStatus.WAITING_APPROVAL)
            messages.append(
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
        return messages

    async def _invoke_agent(
        self,
        *,
        conversation: Conversation,
        project: Project | None,
        participant: ConversationParticipant,
        user_prompt: str,
        context_messages: Iterable[ConversationMessage],
    ) -> list[ConversationMessage]:
        profile = get_agent_profile(participant.agent_key or "principal")
        progress_messages = self._advance_tasks_for_agent(conversation.id, profile)
        prompt = self._build_agent_prompt(
            conversation=conversation,
            project=project,
            participant=participant,
            user_prompt=user_prompt,
            messages=context_messages,
        )
        try:
            result, thread_id = await self.provider.complete(
                role_name=profile.display_name,
                instructions=profile.instructions,
                prompt=prompt,
                thread_id=participant.bridge_thread_id,
                cwd=self._select_cwd(project),
            )
        except Exception as exc:
            failure = self.add_message(
                conversation_id=conversation.id,
                author_name=profile.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content=f"[{profile.display_name}]\nI could not complete my turn because the provider failed: {exc}",
                message_type=MessageKind.AGENT.value,
                participant_id=participant.id,
            )
            return [*progress_messages, failure]
        if thread_id and participant.bridge_thread_id != thread_id:
            participant.bridge_thread_id = thread_id
        content = f"[{profile.display_name}]\n{result.text}".strip()
        message = self.add_message(
            conversation_id=conversation.id,
            author_name=profile.display_name,
            author_kind=ParticipantKind.AGENT.value,
            content=content,
            message_type=MessageKind.AGENT.value,
            participant_id=participant.id,
            metadata={"commentary": result.commentary, "actions": result.actions},
        )
        return [*progress_messages, message]

    def _build_agent_prompt(
        self,
        *,
        conversation: Conversation,
        project: Project | None,
        participant: ConversationParticipant,
        user_prompt: str,
        messages: Iterable[ConversationMessage],
    ) -> str:
        transcript = "\n".join(
            f"{message.author_name}: {message.content}"
            for message in list(messages)[-10:]
        )
        open_tasks = self.tasks.list_for_conversation(conversation.id)
        task_lines = "\n".join(
            f"- {task.id} [{task.status}] {task.title}"
            for task in open_tasks[-6:]
        ) or "- no tasks yet"
        project_memories = self.memory.list_memory(MemoryScope.PROJECT, project.id) if project is not None else []
        conversation_memories = self.memory.list_memory(MemoryScope.CONVERSATION, conversation.id)
        user_memories = self.memory.list_memory(MemoryScope.USER, participant.display_name)
        project_line = f"Project: {project.name if project is not None else 'none'}"
        project_context = project.context_markdown if project is not None and project.context_markdown else "No explicit project context."
        memory_lines = "\n".join(
            f"- {entry.scope_type}:{entry.category}: {entry.content}"
            for entry in [*project_memories[-3:], *conversation_memories[-3:], *user_memories[-2:]]
        ) or "- no persisted memory"
        return (
            f"{project_line}\n"
            f"Conversation title: {conversation.title}\n"
            f"Project context:\n{project_context}\n\n"
            f"Recent transcript:\n{transcript}\n\n"
            f"Open tasks:\n{task_lines}\n\n"
            f"Relevant memory:\n{memory_lines}\n\n"
            f"Current user message:\n{user_prompt}"
        )

    def _participants_to_invoke(self, context: MessageContext, content: str) -> list[ConversationParticipant]:
        text = content.lower()
        ordered_keys = ["principal"]
        if any(token in text for token in ["bug", "fix", "implement", "diagnose", "project", "mvp", "task"]):
            ordered_keys.append("specialist")
        if any(token in text for token in ["test", "validate", "qa", "@qa"]):
            ordered_keys.append("qa")
        if any(token in text for token in ["commit", "branch", "pull request", "repo", "@github"]):
            ordered_keys.append("github")
        if any(token in text for token in ["deploy", "infra", "environment", "@devops"]):
            ordered_keys.append("devops")
        if any(token in text for token in ["plan", "scope", "roadmap", "@po", "@pm"]):
            ordered_keys.append("po_pm")
        participants_by_key = {participant.agent_key: participant for participant in context.participants if participant.agent_key}
        invoked: list[ConversationParticipant] = []
        for key in ordered_keys:
            participant = participants_by_key.get(key)
            if participant is None and key != "principal":
                participant = self.add_agent(context.conversation.id, key)
                participants_by_key[key] = participant
                self.add_message(
                    conversation_id=context.conversation.id,
                    author_name=context.principal.display_name,
                    author_kind=ParticipantKind.AGENT.value,
                    content=f"[Agent Principal] Added {participant.display_name} and shared the relevant context.",
                    message_type=MessageKind.AGENT.value,
                    participant_id=context.principal.id,
                )
            if participant is not None:
                invoked.append(participant)
        return invoked

    def resolve_approval(self, approval_id: str, *, actor_name: str, decision: str) -> ApprovalRequest:
        approval = self.db.get(ApprovalRequest, approval_id)
        if approval is None:
            raise ValueError(f"approval {approval_id!r} not found")
        resolved = self.policies.resolve(approval, actor_name=actor_name, decision=decision)
        message = self.add_message(
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
                new_status = TaskStatus.DEPLOYING if decision == "approve" else TaskStatus.BLOCKED
                self.tasks.set_status(task, new_status)
        self.add_message(
            conversation_id=resolved.conversation_id,
            author_name="Agent Principal",
            author_kind=ParticipantKind.AGENT.value,
            content=(
                f"[Agent Principal]\nApproval {approval_id} was {'approved' if decision == 'approve' else 'rejected'}. "
                "I updated the relevant task state and will continue the coordination flow."
            ),
            message_type=MessageKind.AGENT.value,
        )
        return resolved

    @staticmethod
    def _task_title_from_content(content: str) -> str:
        trimmed = content.strip().rstrip(".")
        if len(trimmed) > 72:
            trimmed = trimmed[:69] + "..."
        return trimmed[:1].upper() + trimmed[1:]

    def _advance_tasks_for_agent(self, conversation_id: str, profile: AgentProfile) -> list[ConversationMessage]:
        task = next(
            (
                item
                for item in self.tasks.list_for_conversation(conversation_id)
                if item.assigned_agent_key == profile.key and item.status in {TaskStatus.CREATED.value, TaskStatus.PLANNED.value, TaskStatus.IN_PROGRESS.value, TaskStatus.TESTING.value, TaskStatus.DEPLOYING.value}
            ),
            None,
        )
        if task is None:
            return []
        target_status = {
            "principal": TaskStatus.IN_PROGRESS,
            "specialist": TaskStatus.IN_PROGRESS if task.status != TaskStatus.IN_PROGRESS.value else TaskStatus.TESTING,
            "qa": TaskStatus.TESTING if task.status != TaskStatus.TESTING.value else TaskStatus.DONE,
            "github": TaskStatus.IN_PROGRESS,
            "devops": TaskStatus.DEPLOYING,
            "po_pm": TaskStatus.PLANNED,
        }.get(profile.key, TaskStatus.IN_PROGRESS)
        if task.status == target_status.value:
            return []
        self.tasks.set_status(task, target_status)
        return [
            self.add_message(
                conversation_id=conversation_id,
                author_name=profile.display_name,
                author_kind=ParticipantKind.AGENT.value,
                content=f"[{profile.display_name}]\nTask {task.id} moved to {target_status.value}.",
                message_type=MessageKind.SYSTEM.value,
            )
        ]

    @staticmethod
    def _select_cwd(project: Project | None) -> str | None:
        if project is None:
            return None
        for repo in project.repositories:
            if repo.is_primary and repo.local_path:
                return repo.local_path
        return None
