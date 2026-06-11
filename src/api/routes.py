from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from src.db import get_db
from src.ingest.service import run_ingestion
from src.models import Ad, AdVersion, Brand, Detection, IngestionRun

router = APIRouter()

VALID_SOURCES = {"meta", "tiktok", "microsoft"}


# ── helpers ─────────────────────────────────────────────────────────────


def _ingestion_run_dict(run: IngestionRun) -> dict:
    return {
        "run_id": str(run.id),
        "source": run.source_platform,
        "status": run.status,
        "ads_seen": run.ads_seen,
        "ads_new": run.ads_new,
        "ads_updated": run.ads_updated,
        "ads_unchanged": run.ads_unchanged,
        "ads_failed": run.ads_failed,
        "detections_triggered": run.detections_triggered,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
    }


def _ad_dict(ad: Ad) -> dict:
    return {
        "id": str(ad.id),
        "source_platform": ad.source_platform,
        "source_ad_id": ad.source_ad_id,
        "advertiser_name": ad.advertiser_name,
        "ad_text": ad.ad_text,
        "landing_domain": ad.landing_domain,
        "status": ad.status,
        "first_seen_at": ad.first_seen_at.isoformat() if ad.first_seen_at else None,
        "last_seen_at": ad.last_seen_at.isoformat() if ad.last_seen_at else None,
    }


def _detection_dict(detection: Detection) -> dict:
    ad = detection.ad
    brand = detection.brand
    return {
        "id": str(detection.id),
        "ad_id": str(detection.ad_id),
        "brand_name": brand.name if brand else None,
        "source_platform": ad.source_platform if ad else None,
        "source_ad_id": ad.source_ad_id if ad else None,
        "advertiser_name": ad.advertiser_name if ad else None,
        "landing_domain": ad.landing_domain if ad else None,
        "risk_score": detection.risk_score,
        "severity": detection.severity,
        "signals": detection.signals,
        "reasons": detection.reasons,
        "triggered_by_run_id": str(detection.triggered_by_run_id) if detection.triggered_by_run_id else None,
        "created_at": detection.created_at.isoformat() if detection.created_at else None,
    }


# ── endpoints ───────────────────────────────────────────────────────────


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/ingest/run")
def trigger_ingestion(source: str = Query(None, description="Source platform (meta, tiktok, microsoft)")):
    if source is not None and source not in VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source '{source}'. Allowed: {', '.join(sorted(VALID_SOURCES))}",
        )
    result = run_ingestion(source=source)
    return result


@router.get("/ingestion-runs")
def list_ingestion_runs(db: Session = Depends(get_db)):
    runs = db.query(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(50).all()
    return [_ingestion_run_dict(r) for r in runs]


@router.get("/ingestion-runs/{run_id}/summary")
def get_ingestion_run_summary(run_id: UUID, db: Session = Depends(get_db)):
    run = db.query(IngestionRun).filter(IngestionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Ingestion run not found")
    return _ingestion_run_dict(run)


@router.get("/ads")
def list_ads(db: Session = Depends(get_db)):
    ads = db.query(Ad).order_by(Ad.last_seen_at.desc()).limit(100).all()
    return [_ad_dict(a) for a in ads]


@router.get("/ads/{ad_id}")
def get_ad(ad_id: UUID, db: Session = Depends(get_db)):
    ad = db.query(Ad).filter(Ad.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    return {
        **_ad_dict(ad),
        "landing_url": ad.landing_url,
        "advertiser_verified": ad.advertiser_verified,
        "regions": ad.regions,
        "platforms": ad.platforms,
        "spend_range": ad.spend_range,
        "impressions_range": ad.impressions_range,
        "creative_urls_normalized": ad.creative_urls_normalized,
        "snapshot_hash": ad.snapshot_hash,
        "raw_payload_json": ad.raw_payload_json,
        "created_at": ad.created_at.isoformat() if ad.created_at else None,
        "updated_at": ad.updated_at.isoformat() if ad.updated_at else None,
    }


@router.get("/ad-versions/{ad_id}")
def list_ad_versions(ad_id: UUID, db: Session = Depends(get_db)):
    ad = db.query(Ad).filter(Ad.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    versions = (
        db.query(AdVersion)
        .filter(AdVersion.ad_id == ad_id)
        .order_by(AdVersion.version_number.desc())
        .all()
    )
    return [
        {
            "id": str(v.id),
            "ad_id": str(v.ad_id),
            "version_number": v.version_number,
            "snapshot_hash": v.snapshot_hash,
            "changed_fields": v.changed_fields,
            "snapshot_json": v.snapshot_json,
            "raw_payload_json": v.raw_payload_json,
            "seen_at": v.seen_at.isoformat() if v.seen_at else None,
            "ingestion_run_id": str(v.ingestion_run_id) if v.ingestion_run_id else None,
        }
        for v in versions
    ]


@router.get("/brands")
def list_brands(db: Session = Depends(get_db)):
    brands = db.query(Brand).order_by(Brand.name).all()
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "aliases": b.aliases,
            "official_domains": b.official_domains,
            "approved_advertisers": b.approved_advertisers,
            "suspicious_keywords": b.suspicious_keywords,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        }
        for b in brands
    ]


@router.get("/detections")
def list_detections(db: Session = Depends(get_db)):
    detections = (
        db.query(Detection)
        .options(joinedload(Detection.ad), joinedload(Detection.brand))
        .order_by(Detection.created_at.desc())
        .limit(100)
        .all()
    )
    return [_detection_dict(d) for d in detections]


@router.get("/detections/{detection_id}")
def get_detection(detection_id: UUID, db: Session = Depends(get_db)):
    detection = (
        db.query(Detection)
        .options(joinedload(Detection.ad), joinedload(Detection.brand))
        .filter(Detection.id == detection_id)
        .first()
    )
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    return _detection_dict(detection)
