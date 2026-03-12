from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from marrowy.db.models import ApprovalRequest
from marrowy.db.models import Conversation
from marrowy.db.models import ProjectEnvironment
from marrowy.domain.enums import ApprovalStatus
from marrowy.domain.enums import TaskStatus
from marrowy.services.events import EventService


@dataclass(slots=True)
class PolicyDecision:
    requires_approval: bool
    reason: str | None = None


class PolicyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = EventService(db)

    def evaluate(self, *, project_id: str | None, agent_key: str, action_type: str, environment_name: str | None = None) -> PolicyDecision:
        if action_type == "deploy.production":
            return PolicyDecision(True, "Production deployments require user approval.")
        if action_type == "github.push":
            return PolicyDecision(True, "Repository push actions require explicit approval in this MVP.")
        if action_type == "agent.join.devops" and environment_name == "production":
            return PolicyDecision(True, "Production-scoped DevOps participation requires approval.")
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
    ) -> ApprovalRequest:
        approval = ApprovalRequest(
            conversation_id=conversation.id,
            task_id=task_id,
            status=ApprovalStatus.PENDING.value,
            action_type=action_type,
            requested_by_agent_key=agent_key,
            summary=summary,
            details_json=details or {},
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

    def resolve(self, approval: ApprovalRequest, *, actor_name: str, decision: str) -> ApprovalRequest:
        approval.status = ApprovalStatus.APPROVED.value if decision == "approve" else ApprovalStatus.REJECTED.value
        approval.resolved_by = actor_name
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
