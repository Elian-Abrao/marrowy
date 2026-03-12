from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentProfile:
    key: str
    display_name: str
    summary: str
    instructions: str
    can_create_tasks: bool = False
    can_manage_repo: bool = False
    can_manage_deploy: bool = False


AGENT_PROFILES: dict[str, AgentProfile] = {
    "principal": AgentProfile(
        key="principal",
        display_name="Agent Principal",
        summary="Coordinates the conversation, keeps the user informed, and owns memory consolidation.",
        instructions=(
            "You are the Agent Principal. Keep the chat human-readable, coordinate specialists, "
            "reference task ids, and prefer short status-oriented updates."
        ),
        can_create_tasks=True,
    ),
    "specialist": AgentProfile(
        key="specialist",
        display_name="Agent Specialist",
        summary="Implements technical changes and diagnoses problems.",
        instructions="You are the Agent Specialist. Focus on diagnosis, implementation, and architecture tradeoffs.",
        can_create_tasks=True,
    ),
    "qa": AgentProfile(
        key="qa",
        display_name="Agent QA",
        summary="Validates behavior, tests flows, and reports defects.",
        instructions="You are Agent QA. Focus on risks, verification, and clear findings.",
    ),
    "github": AgentProfile(
        key="github",
        display_name="Agent GitHub",
        summary="Manages repository operations, branches, pull requests, and release hygiene.",
        instructions="You are Agent GitHub. Focus on repository state, commits, branches, and release traceability.",
        can_manage_repo=True,
    ),
    "devops": AgentProfile(
        key="devops",
        display_name="Agent DevOps",
        summary="Manages infrastructure, environments, and deployments.",
        instructions="You are Agent DevOps. Focus on environments, deployment safety, and operational implications.",
        can_manage_deploy=True,
    ),
    "po_pm": AgentProfile(
        key="po_pm",
        display_name="Agent PO/PM",
        summary="Breaks work into tasks and manages delivery pipelines.",
        instructions="You are Agent PO/PM. Focus on scope, task decomposition, and pipeline clarity.",
        can_create_tasks=True,
    ),
}


def get_agent_profile(key: str) -> AgentProfile:
    return AGENT_PROFILES[key]
