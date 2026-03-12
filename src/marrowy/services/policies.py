from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import ApprovalRequest
from marrowy.db.models import Conversation
from marrowy.db.models import Project
from marrowy.db.models import ProjectEnvironment
from marrowy.domain.enums import ApprovalStatus
from marrowy.services.events import EventService


@dataclass(slots=True)
class PolicyDecision:
    requires_approval: bool
    reason: str | None = None


class PolicyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = EventService(db)

    def evaluate(
        self,
        *,
        project_id: str | None,
        agent_key: str,
        action_type: str,
        environment_name: str | None = None,
        tool_name: str | None = None,
    ) -> PolicyDecision:
        project = self.db.get(Project, project_id) if project_id else None
        environment = self._find_environment(project_id=project_id, environment_name=environment_name)

        if environment is not None and environment.approval_policy_json.get("deploy_requires_approval") and action_type.startswith("deploy."):
            return PolicyDecision(True, f"{environment.name.capitalize()} deployment requires user approval.")
        if action_type == "deploy.production":
            return PolicyDecision(True, "Production deployments require user approval.")
        if action_type == "github.push":
            return PolicyDecision(True, "Repository push actions require explicit approval in this MVP.")
        if action_type == "agent.join.devops" and environment_name == "production":
            return PolicyDecision(True, "Production-scoped DevOps participation requires approval.")
        if tool_name in {"shell", "browser", "github"} and project is not None and project.metadata_json.get("alwaysApproveTools"):
            return PolicyDecision(True, f"Project policy requires approval for tool {tool_name}.")
        return PolicyDecision(False)

    def create_approval(
        self,
        *,
        conversation: Conversation,
        agent_key: str,
        action_type: str,
        summary: str,
        details: dict | None = None,
        task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ApprovalRequest:
        if idempotency_key:
            existing = self.find_pending(
                conversation_id=conversation.id,
                action_type=action_type,
                task_id=task_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing
        approval = ApprovalRequest(
            conversation_id=conversation.id,
            task_id=task_id,
            status=ApprovalStatus.PENDING.value,
            action_type=action_type,
            requested_by_agent_key=agent_key,
            summary=summary,
            details_json=details or {},
            idempotency_key=idempotency_key,
        )
        self.db.add(approval)
        self.db.flush()
        self.events.emit(
            "approval.requested",
            conversation_id=conversation.id,
            task_id=task_id,
            payload={"approvalId": approval.id, "actionType": action_type},
        )
        return approval

    def find_pending(
        self,
        *,
        conversation_id: str,
        action_type: str,
        task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ApprovalRequest | None:
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.conversation_id == conversation_id,
            ApprovalRequest.action_type == action_type,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
        if task_id is not None:
            stmt = stmt.where(ApprovalRequest.task_id == task_id)
        if idempotency_key is not None:
            stmt = stmt.where(ApprovalRequest.idempotency_key == idempotency_key)
        return self.db.scalar(stmt.order_by(ApprovalRequest.created_at.desc()))

    def ensure_approval(
        self,
        *,
        conversation: Conversation,
        agent_key: str,
        action_type: str,
        summary: str,
        details: dict | None = None,
        task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ApprovalRequest:
        return self.create_approval(
            conversation=conversation,
            agent_key=agent_key,
            action_type=action_type,
            summary=summary,
            details=details,
            task_id=task_id,
            idempotency_key=idempotency_key,
        )

    def resolve(self, approval: ApprovalRequest, *, actor_name: str, decision: str) -> ApprovalRequest:
        approval.status = ApprovalStatus.APPROVED.value if decision == "approve" else ApprovalStatus.REJECTED.value
        approval.resolved_by = actor_name
        approval.resolved_at = datetime.now(timezone.utc)
        self.db.flush()
        self.events.emit(
            "approval.granted" if approval.status == ApprovalStatus.APPROVED.value else "approval.rejected",
            conversation_id=approval.conversation_id,
            task_id=approval.task_id,
            payload={"approvalId": approval.id, "actorName": actor_name},
        )
        return approval

    def pending_for_conversation(self, conversation_id: str) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.conversation_id == conversation_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
        return list(self.db.scalars(stmt.order_by(ApprovalRequest.created_at)))

    def _find_environment(self, *, project_id: str | None, environment_name: str | None) -> ProjectEnvironment | None:
        if project_id is None or environment_name is None:
            return None
        return self.db.scalar(
            select(ProjectEnvironment).where(
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.name == environment_name,
            )
        )
