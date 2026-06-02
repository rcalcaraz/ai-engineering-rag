"""Persist ingestion documents per job.

Revision ID: 0002_ingestion_documents
Revises: 0001_session6_initial
Create Date: 2026-06-02 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "0002_ingestion_documents"
down_revision: Union[str, None] = "0001_session6_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.String(length=512), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["ingestion_jobs.job_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "job_id", "document_id", name="uq_ingestion_documents_job_doc"
        ),
    )
    op.create_index(
        "idx_ingestion_documents_job_id",
        "ingestion_documents",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_ingestion_documents_job_id", table_name="ingestion_documents"
    )
    op.drop_table("ingestion_documents")
