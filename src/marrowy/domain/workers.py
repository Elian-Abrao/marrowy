from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerProfile:
    key: str
    display_name: str
    summary: str


WORKER_PROFILES: dict[str, WorkerProfile] = {
    "summary": WorkerProfile(
        key="summary",
        display_name="Summary Worker",
        summary="Builds responsive conversational summaries and coordinator replies.",
    ),
    "specialist": WorkerProfile(
        key="specialist",
        display_name="Specialist Worker",
        summary="Executes technical diagnosis and implementation turns.",
    ),
    "qa": WorkerProfile(
        key="qa",
        display_name="QA Worker",
        summary="Executes validation-focused turns and reports testing progress.",
    ),
    "github": WorkerProfile(
        key="github",
        display_name="GitHub Worker",
        summary="Executes repository-oriented work and reports repo progress.",
    ),
    "devops": WorkerProfile(
        key="devops",
        display_name="DevOps Worker",
        summary="Executes environment and deployment-related work.",
    ),
    "planning": WorkerProfile(
        key="planning",
        display_name="Planning Worker",
        summary="Executes scope decomposition and delivery planning turns.",
    ),
}


def worker_key_for_agent(agent_key: str) -> str:
    return {
        "principal": "summary",
        "specialist": "specialist",
        "qa": "qa",
        "github": "github",
        "devops": "devops",
        "po_pm": "planning",
        "frontend": "specialist",
        "backend_python": "specialist",
    }.get(agent_key, "summary")
