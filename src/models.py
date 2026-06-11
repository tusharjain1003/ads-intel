import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, BigInteger,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class AdSource(Base):
    __tablename__ = "ad_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_name = Column(String(50), unique=True, nullable=False)
    base_url = Column(String(255), nullable=False)
    adapter_mode = Column(String(10), nullable=False)  # LIVE | FIXTURE
    last_successful_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Ad(Base):
    __tablename__ = "ads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_platform = Column(String(20), nullable=False)
    source_ad_id = Column(String(255), nullable=True)
    advertiser_name = Column(String(255), nullable=True)
    advertiser_verified = Column(Boolean, nullable=True)
    ad_text = Column(Text, nullable=True)
    landing_url = Column(Text, nullable=True)
    landing_domain = Column(String(255), nullable=True)
    regions = Column(JSONB, nullable=False, default=list)
    platforms = Column(JSONB, nullable=False, default=list)
    spend_range = Column(JSONB, nullable=True)
    impressions_range = Column(JSONB, nullable=True)
    creative_urls_normalized = Column(JSONB, nullable=False, default=list)
    first_seen_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="NEW")  # NEW | ACTIVE | UPDATED | INACTIVE
    snapshot_hash = Column(String(64), nullable=False)
    raw_payload_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_platform", "source_ad_id", name="uq_ads_source"),
    )

    versions = relationship("AdVersion", backref="ad", lazy="select")
    detections = relationship("Detection", backref="ad", lazy="select")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_platform = Column(String(20), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="RUNNING")  # RUNNING | SUCCESS | FAILED
    ads_seen = Column(Integer, default=0, nullable=False)
    ads_new = Column(Integer, default=0, nullable=False)
    ads_updated = Column(Integer, default=0, nullable=False)
    ads_unchanged = Column(Integer, default=0, nullable=False)
    ads_failed = Column(Integer, default=0, nullable=False)
    detections_triggered = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    versions = relationship("AdVersion", backref="ingestion_run", lazy="select")
    detections = relationship("Detection", backref="ingestion_run", lazy="select")


class AdVersion(Base):
    __tablename__ = "ad_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ad_id = Column(UUID(as_uuid=True), ForeignKey("ads.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    snapshot_hash = Column(String(64), nullable=False)
    changed_fields = Column(JSONB, nullable=True)
    snapshot_json = Column(JSONB, nullable=False)
    raw_payload_json = Column(JSONB, nullable=True)
    seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=True)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    aliases = Column(JSONB, nullable=False, default=list)
    official_domains = Column(JSONB, nullable=False, default=list)
    approved_advertisers = Column(JSONB, nullable=False, default=list)
    suspicious_keywords = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    detections = relationship("Detection", backref="brand", lazy="select")


class Detection(Base):
    __tablename__ = "detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ad_id = Column(UUID(as_uuid=True), ForeignKey("ads.id"), nullable=False)
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=False)
    triggered_by_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=True)
    risk_score = Column(Integer, nullable=False, default=0)
    severity = Column(String(10), nullable=False, default="LOW")  # LOW | MEDIUM | HIGH
    signals = Column(JSONB, nullable=False, default=list)
    reasons = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
