"""add jobs, participant activity, and idempotency columns

Revision ID: 1fe9c0d5c7ab
Revises: 5097540f182c
Create Date: 2026-03-12 05:15:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1fe9c0d5c7ab"
down_revision = "5097540f182c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_participants", sa.Column("activity_state", sa.String(length=40), nullable=False, server_default="idle"))
    op.add_column("conversation_participants", sa.Column("activity_summary", sa.String(length=240), nullable=True))
    op.add_column("conversation_participants", sa.Column("last_activity_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_conversation_participants_activity_state"), "conversation_participants", ["activity_state"], unique=False)

    op.add_column("tasks", sa.Column("idempotency_key", sa.String(length=200), nullable=True))
    op.create_index(op.f("ix_tasks_idempotency_key"), "tasks", ["idempotency_key"], unique=False)

    op.add_column("approval_requests", sa.Column("idempotency_key", sa.String(length=200), nullable=True))
    op.create_index(op.f("ix_approval_requests_idempotency_key"), "approval_requests", ["idempotency_key"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("participant_id", sa.String(length=36), nullable=True),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("worker_key", sa.String(length=80), nullable=False),
        sa.Column("agent_key", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("claim_token", sa.String(length=120), nullable=True),
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["conversation_participants.id"]),
        sa.ForeignKeyConstraint(["source_message_id"], ["conversation_messages.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_agent_key"), "jobs", ["agent_key"], unique=False)
    op.create_index(op.f("ix_jobs_available_at"), "jobs", ["available_at"], unique=False)
    op.create_index(op.f("ix_jobs_claim_token"), "jobs", ["claim_token"], unique=False)
    op.create_index(op.f("ix_jobs_conversation_id"), "jobs", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_jobs_idempotency_key"), "jobs", ["idempotency_key"], unique=False)
    op.create_index(op.f("ix_jobs_participant_id"), "jobs", ["participant_id"], unique=False)
    op.create_index(op.f("ix_jobs_source_message_id"), "jobs", ["source_message_id"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_task_id"), "jobs", ["task_id"], unique=False)
    op.create_index(op.f("ix_jobs_worker_key"), "jobs", ["worker_key"], unique=False)

    op.alter_column("conversation_participants", "activity_state", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_worker_key"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_task_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_source_message_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_participant_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_idempotency_key"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_conversation_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_claim_token"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_available_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_agent_key"), table_name="jobs")
    op.drop_table("jobs")

    op.drop_index(op.f("ix_approval_requests_idempotency_key"), table_name="approval_requests")
    op.drop_column("approval_requests", "idempotency_key")

    op.drop_index(op.f("ix_tasks_idempotency_key"), table_name="tasks")
    op.drop_column("tasks", "idempotency_key")

    op.drop_index(op.f("ix_conversation_participants_activity_state"), table_name="conversation_participants")
    op.drop_column("conversation_participants", "last_activity_at")
    op.drop_column("conversation_participants", "activity_summary")
    op.drop_column("conversation_participants", "activity_state")
