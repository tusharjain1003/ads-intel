"""create initial tables

Revision ID: 001
Revises:
Create Date: 2025-01-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    op.create_table(
        "ad_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("platform_name", sa.String(50), unique=True, nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("adapter_mode", sa.String(10), nullable=False),
        sa.Column("last_successful_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("aliases", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("official_domains", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("approved_advertisers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("suspicious_keywords", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_platform", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("ads_seen", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ads_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ads_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ads_unchanged", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ads_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("detections_triggered", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_table(
        "ads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_platform", sa.String(20), nullable=False),
        sa.Column("source_ad_id", sa.String(255), nullable=True),
        sa.Column("advertiser_name", sa.String(255), nullable=True),
        sa.Column("advertiser_verified", sa.Boolean(), nullable=True),
        sa.Column("ad_text", sa.Text(), nullable=True),
        sa.Column("landing_url", sa.Text(), nullable=True),
        sa.Column("landing_domain", sa.String(255), nullable=True),
        sa.Column("regions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("platforms", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("spend_range", postgresql.JSONB(), nullable=True),
        sa.Column("impressions_range", postgresql.JSONB(), nullable=True),
        sa.Column("creative_urls_normalized", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="NEW"),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_ads_source", "ads", ["source_platform", "source_ad_id"])
    op.create_index("ix_ads_fallback_dedup", "ads", ["source_platform", "landing_domain", "advertiser_name"])

    op.create_table(
        "ad_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("ad_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ads.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=True),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("raw_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id"), nullable=True),
    )

    op.create_table(
        "detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("ad_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ads.id"), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("triggered_by_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id"), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("severity", sa.String(10), nullable=False, server_default="LOW"),
        sa.Column("signals", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    op.execute(
        """
        INSERT INTO ad_sources (platform_name, base_url, adapter_mode) VALUES
        ('meta', 'https://www.facebook.com/ads/library', 'FIXTURE'),
        ('tiktok', 'https://library.tiktok.com/ads', 'FIXTURE'),
        ('microsoft', 'https://adlibrary.ads.microsoft.com', 'FIXTURE')
        """
    )


def downgrade() -> None:
    op.drop_table("detections")
    op.drop_table("ad_versions")
    op.drop_table("ads")
    op.drop_table("ingestion_runs")
    op.drop_table("brands")
    op.drop_table("ad_sources")
