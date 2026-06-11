import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.detection.scoring import score_ad_against_brand, severity_from_score
from src.models import Ad, AdVersion, Brand, Detection, IngestionRun

logger = logging.getLogger(__name__)


def run_brand_impersonation_detection(
    db: Session,
    ingestion_run_id: UUID,
    ad_ids: Optional[List[UUID]] = None,
) -> int:
    """Run brand-impersonation detection for ads created or updated in *ingestion_run_id*.

    Only ads whose current ``status`` is ``NEW`` or ``UPDATED`` are evaluated.
    Each ad is scored against every brand in the database.  Detections are
    inserted only when ``risk_score >= 40``.

    Parameters
    ----------
    db : Session
        Active database session.
    ingestion_run_id : UUID
        The ingestion run whose ads should be checked.
    ad_ids : list of UUID or None
        Optional explicit list of ad IDs to evaluate.  When ``None``, all ads
        that have a version linked to this run are considered.

    Returns
    -------
    int
        Number of detections inserted.
    """
    run = db.query(IngestionRun).filter(IngestionRun.id == ingestion_run_id).first()
    if not run:
        logger.warning("Ingestion run %s not found", ingestion_run_id)
        return 0

    # Gather candidate ad IDs
    if ad_ids is not None:
        candidate_ids = ad_ids
    else:
        rows = (
            db.query(AdVersion.ad_id)
            .filter(AdVersion.ingestion_run_id == ingestion_run_id)
            .distinct()
            .all()
        )
        candidate_ids = [row[0] for row in rows]

    if not candidate_ids:
        return 0

    ads = (
        db.query(Ad)
        .filter(Ad.id.in_(candidate_ids), Ad.status.in_(["NEW", "UPDATED"]))
        .all()
    )
    if not ads:
        return 0

    brands = db.query(Brand).all()
    if not brands:
        logger.info("No brands configured — skipping detection")
        return 0

    inserted = 0
    for ad in ads:
        for brand in brands:
            # ── Skip if detection already exists for this (ad, brand, run) ──
            existing = (
                db.query(Detection)
                .filter(
                    Detection.ad_id == ad.id,
                    Detection.brand_id == brand.id,
                    Detection.triggered_by_run_id == ingestion_run_id,
                )
                .first()
            )
            if existing is not None:
                continue

            risk_score, signals, reasons = score_ad_against_brand(
                ad_text=ad.ad_text or "",
                advertiser_name=ad.advertiser_name or "",
                landing_domain=ad.landing_domain or "",
                approved_advertisers=brand.approved_advertisers or [],
                official_domains=brand.official_domains or [],
                brand_name=brand.name or "",
                aliases=brand.aliases or [],
                suspicious_keywords=brand.suspicious_keywords or [],
            )

            if risk_score >= 40:
                detection = Detection(
                    ad_id=ad.id,
                    brand_id=brand.id,
                    triggered_by_run_id=ingestion_run_id,
                    risk_score=risk_score,
                    severity=severity_from_score(risk_score),
                    signals=signals,
                    reasons=reasons,
                )
                db.add(detection)
                inserted += 1
                logger.info(
                    "Detection: ad=%s brand=%s score=%d severity=%s",
                    ad.id,
                    brand.name,
                    risk_score,
                    severity_from_score(risk_score),
                )

    if inserted:
        run.detections_triggered = (run.detections_triggered or 0) + inserted

    logger.info("Brand impersonation detection complete: %d detections inserted", inserted)
    return inserted
