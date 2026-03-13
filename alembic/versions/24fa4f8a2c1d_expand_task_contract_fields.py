"""expand task contract fields

Revision ID: 24fa4f8a2c1d
Revises: 1fe9c0d5c7ab
Create Date: 2026-03-12 19:15:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "24fa4f8a2c1d"
down_revision = "1fe9c0d5c7ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("acceptance_criteria_markdown", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("repository_name", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("branch_name", sa.String(length=200), nullable=True))
    op.add_column("tasks", sa.Column("environment_name", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("updates_markdown", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("blockers_markdown", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tasks", sa.Column("observations_markdown", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("evidence_markdown", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("gmud_reference", sa.String(length=120), nullable=True))
    op.alter_column("tasks", "approval_required", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "gmud_reference")
    op.drop_column("tasks", "evidence_markdown")
    op.drop_column("tasks", "observations_markdown")
    op.drop_column("tasks", "approval_required")
    op.drop_column("tasks", "blockers_markdown")
    op.drop_column("tasks", "updates_markdown")
    op.drop_column("tasks", "environment_name")
    op.drop_column("tasks", "branch_name")
    op.drop_column("tasks", "repository_name")
    op.drop_column("tasks", "acceptance_criteria_markdown")
