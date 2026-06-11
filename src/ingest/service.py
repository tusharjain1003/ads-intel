import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db import SessionLocal
from src.detection.brand_impersonation import run_brand_impersonation_detection
from src.ingest import get_adapter, get_all_adapters
from src.ingest.dedup import (
    build_snapshot,
    compute_changed_fields,
    compute_snapshot_hash,
    fallback_dedup_key,
)
from src.ingest.normalizer import normalize_ad
from src.models import Ad, AdVersion, Brand, IngestionRun

logger = logging.getLogger(__name__)


# ── Internal helpers ───────────────────────────────────────────────────────


def _load_search_terms(db: Session) -> List[str]:
    """Collect all brand names and aliases from the database."""
    brands = db.query(Brand).all()
    terms: List[str] = []
    for brand in brands:
        terms.append(brand.name)
        terms.extend(brand.aliases or [])
    return list(set(terms))


def _lookup_ad(db: Session, source_platform: str, source_ad_id: Optional[str]) -> Optional[Ad]:
    """Return an existing ad row by primary or fallback lookup.

    1. If ``source_ad_id`` is present, query by ``(source_platform, source_ad_id)``.
    2. Otherwise return ``None`` — the caller will handle fallback matching.
    """
    if source_ad_id:
        return (
            db.query(Ad)
            .filter(
                Ad.source_platform == source_platform,
                Ad.source_ad_id == source_ad_id,
            )
            .first()
        )
    return None


def _fallback_lookup_ad(db: Session, source_platform: str, normalized_ad: Any) -> Optional[Ad]:
    """Try to find an existing ad that matches on content rather than source ID.

    Matches on ``(source_platform, landing_domain, advertiser_name, ad_text)``.
    This handles sources that do not provide a stable ``source_ad_id``.
    """
    return (
        db.query(Ad)
        .filter(
            Ad.source_platform == source_platform,
            Ad.landing_domain == normalized_ad.landing_domain,
            Ad.advertiser_name == normalized_ad.advertiser_name,
            Ad.ad_text == normalized_ad.ad_text,
        )
        .first()
    )


def _latest_version_number(db: Session, ad_id: Any) -> int:
    """Return the highest version number for *ad_id*, or 0 if none exist."""
    result = (
        db.query(AdVersion.version_number)
        .filter(AdVersion.ad_id == ad_id)
        .order_by(AdVersion.version_number.desc())
        .first()
    )
    return result[0] if result else 0


def _upsert_ad(
    db: Session,
    run: IngestionRun,
    source_platform: str,
    normalized_ad: Any,
) -> Dict[str, Any]:
    """Normalise, deduplicate, and upsert a single ad.

    Returns a dict with keys ``action`` (``"new"`` / ``"updated"`` / ``"unchanged"``)
    and optionally ``ad_id``.
    """
    snapshot = build_snapshot(normalized_ad)
    snapshot_hash = compute_snapshot_hash(snapshot)
    now = datetime.utcnow()

    existing = _lookup_ad(db, source_platform, normalized_ad.source_ad_id)
    if existing is None:
        existing = _fallback_lookup_ad(db, source_platform, normalized_ad)

    if existing is None:
        ad = Ad(
            source_platform=source_platform,
            source_ad_id=normalized_ad.source_ad_id or None,
            advertiser_name=normalized_ad.advertiser_name,
            advertiser_verified=normalized_ad.advertiser_verified,
            ad_text=normalized_ad.ad_text,
            landing_url=normalized_ad.landing_url,
            landing_domain=normalized_ad.landing_domain,
            regions=normalized_ad.regions,
            platforms=normalized_ad.platforms,
            spend_range=normalized_ad.spend_range,
            impressions_range=normalized_ad.impressions_range,
            creative_urls_normalized=normalized_ad.creative_urls_normalized,
            first_seen_at=now,
            last_seen_at=now,
            status="NEW",
            snapshot_hash=snapshot_hash,
            raw_payload_json=normalized_ad.raw_payload_json,
        )
        db.add(ad)
        db.flush()
        version = AdVersion(
            ad_id=ad.id,
            version_number=1,
            snapshot_hash=snapshot_hash,
            changed_fields=list(snapshot.keys()),
            snapshot_json=snapshot,
            raw_payload_json=normalized_ad.raw_payload_json,
            seen_at=now,
            ingestion_run_id=run.id,
        )
        db.add(version)
        logger.info("NEW ad %s (%s/%s)", ad.id, source_platform, normalized_ad.source_ad_id or "no-id")
        return {"action": "new", "ad_id": ad.id}

    if existing.snapshot_hash == snapshot_hash:
        existing.last_seen_at = now
        existing.status = "ACTIVE"
        logger.debug("UNCHANGED ad %s (%s/%s)", existing.id, source_platform, normalized_ad.source_ad_id or "no-id")
        return {"action": "unchanged", "ad_id": existing.id}

    # Snapshot changed – upsert
    old_version = (
        db.query(AdVersion)
        .filter(AdVersion.ad_id == existing.id)
        .order_by(AdVersion.version_number.desc())
        .first()
    )
    old_snapshot = old_version.snapshot_json if old_version else {}
    changed = compute_changed_fields(old_snapshot, snapshot)

    existing.advertiser_name = normalized_ad.advertiser_name
    existing.advertiser_verified = normalized_ad.advertiser_verified
    existing.ad_text = normalized_ad.ad_text
    existing.landing_url = normalized_ad.landing_url
    existing.landing_domain = normalized_ad.landing_domain
    existing.regions = normalized_ad.regions
    existing.platforms = normalized_ad.platforms
    existing.spend_range = normalized_ad.spend_range
    existing.impressions_range = normalized_ad.impressions_range
    existing.creative_urls_normalized = normalized_ad.creative_urls_normalized
    existing.last_seen_at = now
    existing.status = "UPDATED"
    existing.snapshot_hash = snapshot_hash
    existing.raw_payload_json = normalized_ad.raw_payload_json

    next_ver = _latest_version_number(db, existing.id) + 1
    version = AdVersion(
        ad_id=existing.id,
        version_number=next_ver,
        snapshot_hash=snapshot_hash,
        changed_fields=changed,
        snapshot_json=snapshot,
        raw_payload_json=normalized_ad.raw_payload_json,
        seen_at=now,
        ingestion_run_id=run.id,
    )
    db.add(version)
    logger.info("UPDATED ad %s (%s/%s) fields=%s", existing.id, source_platform, normalized_ad.source_ad_id or "no-id", changed)
    return {"action": "updated", "ad_id": existing.id}


def _run_single_source(
    db: Session,
    run: IngestionRun,
    source_platform: str,
    search_terms: List[str],
) -> Dict[str, int]:
    """Execute the fetch–normalise–upsert pipeline for one source.

    Returns a dict of counters for this source alone.
    """
    counters: Dict[str, int] = {
        "ads_seen": 0,
        "ads_new": 0,
        "ads_updated": 0,
        "ads_unchanged": 0,
        "ads_failed": 0,
    }

    adapter = get_adapter(source_platform)
    try:
        raw_ads = adapter.fetch_ads(search_terms)
    except Exception as exc:
        logger.error("Adapter %s failed: %s", source_platform, exc)
        raise

    counters["ads_seen"] = len(raw_ads)

    for raw_ad in raw_ads:
        try:
            normalized = normalize_ad(source_platform, raw_ad)
            result = _upsert_ad(db, run, source_platform, normalized)
            action = result["action"]
            if action == "new":
                counters["ads_new"] += 1
            elif action == "updated":
                counters["ads_updated"] += 1
            else:
                counters["ads_unchanged"] += 1
        except Exception as exc:
            ad_id = raw_ad.get("id") or raw_ad.get("ad_id") or raw_ad.get("adId") or "<unknown>"
            logger.warning("Failed to process %s ad %s: %s", source_platform, ad_id, exc)
            counters["ads_failed"] += 1

    return counters


# ── Public API ─────────────────────────────────────────────────────────────


def run_ingestion(source: Optional[str] = None) -> Dict[str, Any]:
    """Run the ad ingestion pipeline for one or all sources.

    Parameters
    ----------
    source : str or None
        One of ``"meta"``, ``"tiktok"``, ``"microsoft"``, or ``None`` for all.

    Returns
    -------
    dict
        Summary with keys ``run_id``, ``source``, ``status``, and counters.
    """
    db = SessionLocal()
    try:
        sources: List[str]
        if source and source.lower() in ("meta", "tiktok", "microsoft"):
            sources = [source.lower()]
            run_source_label = source.lower()
        elif source is None:
            sources = ["meta", "tiktok", "microsoft"]
            run_source_label = "all"
        else:
            raise ValueError(f"Unknown source '{source}'. Use meta, tiktok, microsoft, or None.")

        run = IngestionRun(
            source_platform=run_source_label,
            status="RUNNING",
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.flush()

        search_terms = _load_search_terms(db)

        totals: Dict[str, int] = {
            "ads_seen": 0,
            "ads_new": 0,
            "ads_updated": 0,
            "ads_unchanged": 0,
            "ads_failed": 0,
        }
        errors: List[str] = []

        for sp in sources:
            try:
                counters = _run_single_source(db, run, sp, search_terms)
                for key in totals:
                    totals[key] += counters[key]
            except Exception as exc:
                logger.error("Source %s failed entirely: %s", sp, exc)
                errors.append(f"{sp}: {exc}")

        run.ads_seen = totals["ads_seen"]
        run.ads_new = totals["ads_new"]
        run.ads_updated = totals["ads_updated"]
        run.ads_unchanged = totals["ads_unchanged"]
        run.ads_failed = totals["ads_failed"]

        db.flush()

        # Run brand-impersonation detection on ads touched by this run
        detection_count = run_brand_impersonation_detection(db, run.id)

        run.completed_at = datetime.utcnow()
        run.status = "SUCCESS" if not errors else "FAILED"
        if errors:
            run.error_message = "; ".join(errors)

        db.commit()
        logger.info(
            "Ingestion run %s (%s) finished: seen=%d new=%d updated=%d unchanged=%d failed=%d detections=%d",
            run.id,
            run_source_label,
            totals["ads_seen"],
            totals["ads_new"],
            totals["ads_updated"],
            totals["ads_unchanged"],
            totals["ads_failed"],
            detection_count,
        )

        return {
            "run_id": str(run.id),
            "source": run_source_label,
            "status": run.status,
            "ads_seen": totals["ads_seen"],
            "ads_new": totals["ads_new"],
            "ads_updated": totals["ads_updated"],
            "ads_unchanged": totals["ads_unchanged"],
            "ads_failed": totals["ads_failed"],
            "detections_triggered": detection_count,
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
