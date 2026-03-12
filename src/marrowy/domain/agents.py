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
            "You are the Agent Principal. Coordinate the conversation, route complex tasks to specialized agents (e.g. Agent "
            "Frontend, Agent Backend Python, Agent QA, etc), and do NOT do the heavy lifting yourself. "
            "Focus on short, objective updates. When detailed work is needed, delegate it."
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
    "backend_python": AgentProfile(
        key="backend_python",
        display_name="Agent Backend Python",
        summary="Writes clean, modular Python backend code and respects existing architectures.",
        instructions=(
            "You are the Agent Backend Python. "
            "Write clean, modular, legible code. Do not over-engineer. "
            "Respect the existing architecture, files, tests, and formatting of existing projects. "
            "Produce clear logic with error handling as appropriate."
        ),
        can_create_tasks=True,
    ),
    "frontend": AgentProfile(
        key="frontend",
        display_name="Agent Frontend",
        summary="Acts as a Senior Frontend/UI Engineer handling system design and beautiful interfaces.",
        instructions=(
            "You are the Agent Frontend. Act as a Senior Frontend/Product UI Engineer. "
            "Treat UI as a system: think through layout, state, error states, performance, and accessibility. "
            "Follow modern design practices, use harmonious color palettes, and avoid generic or clunky aesthetics. "
            "Respect any existing project identity or tech stack (e.g., Tailwind, Vanilla CSS, React, etc). "
            "Do not output placeholders if a working UI can be demonstrated."
        ),
        can_create_tasks=True,
    ),
}


def get_agent_profile(key: str) -> AgentProfile:
    if key not in AGENT_PROFILES:
        raise KeyError(f"agent profile {key!r} not found")
    return AGENT_PROFILES[key]


def list_all_profiles() -> list[AgentProfile]:
    return list(AGENT_PROFILES.values())


def register_agent(
    *,
    key: str,
    display_name: str,
    summary: str,
    instructions: str,
    can_create_tasks: bool = False,
    can_manage_repo: bool = False,
    can_manage_deploy: bool = False,
) -> AgentProfile:
    """Register a new agent profile at runtime, making it available across all conversations."""
    if key in AGENT_PROFILES:
        return AGENT_PROFILES[key]
    profile = AgentProfile(
        key=key,
        display_name=display_name,
        summary=summary,
        instructions=instructions,
        can_create_tasks=can_create_tasks,
        can_manage_repo=can_manage_repo,
        can_manage_deploy=can_manage_deploy,
    )
    AGENT_PROFILES[key] = profile
    return profile
