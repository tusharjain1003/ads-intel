import json
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "sample_outputs")


def main():
    from src.db import SessionLocal
    from src.ingest.service import run_ingestion
    from src.models import Ad, Brand, Detection, IngestionRun

    # 1. Run ingestion for meta source
    logger.info("Running ingestion for source=meta ...")
    result = run_ingestion(source="meta")
    logger.info(
        "Ingestion complete: seen=%d new=%d updated=%d unchanged=%d failed=%d detections=%d",
        result["ads_seen"],
        result["ads_new"],
        result["ads_updated"],
        result["ads_unchanged"],
        result["ads_failed"],
        result["detections_triggered"],
    )

    db = SessionLocal()

    try:
        # 2. Query latest ingestion run
        latest_run = (
            db.query(IngestionRun)
            .order_by(IngestionRun.started_at.desc())
            .first()
        )

        if latest_run:
            ingestion_summary = {
                "run_id": str(latest_run.id),
                "source": latest_run.source_platform,
                "status": latest_run.status,
                "ads_seen": latest_run.ads_seen,
                "ads_new": latest_run.ads_new,
                "ads_updated": latest_run.ads_updated,
                "ads_unchanged": latest_run.ads_unchanged,
                "ads_failed": latest_run.ads_failed,
                "detections_triggered": latest_run.detections_triggered,
                "started_at": latest_run.started_at.isoformat() if latest_run.started_at else None,
                "completed_at": latest_run.completed_at.isoformat() if latest_run.completed_at else None,
                "error_message": latest_run.error_message,
            }
        else:
            ingestion_summary = {}

        # 3. Query detections with ad + brand context
        detections = db.query(Detection).order_by(Detection.created_at.desc()).all()
        detection_rows = []
        for d in detections:
            ad = db.query(Ad).filter(Ad.id == d.ad_id).first()
            brand = db.query(Brand).filter(Brand.id == d.brand_id).first()
            detection_rows.append({
                "id": str(d.id),
                "ad_id": str(d.ad_id),
                "brand_name": brand.name if brand else None,
                "source_platform": ad.source_platform if ad else None,
                "source_ad_id": ad.source_ad_id if ad else None,
                "advertiser_name": ad.advertiser_name if ad else None,
                "landing_domain": ad.landing_domain if ad else None,
                "risk_score": d.risk_score,
                "severity": d.severity,
                "signals": d.signals,
                "reasons": d.reasons,
                "triggered_by_run_id": str(d.triggered_by_run_id) if d.triggered_by_run_id else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            })

    finally:
        db.close()

    # 4. Write output files
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ingestion_path = os.path.join(OUTPUT_DIR, "ingestion_summary.json")
    with open(ingestion_path, "w") as f:
        json.dump(ingestion_summary, f, indent=2, default=str)
    logger.info("Wrote %s", ingestion_path)

    detections_path = os.path.join(OUTPUT_DIR, "detections.json")
    with open(detections_path, "w") as f:
        json.dump(detection_rows, f, indent=2, default=str)
    logger.info("Wrote %s", detections_path)

    print("\nSample outputs generated:")
    print(f"  {ingestion_path}")
    print(f"  {detections_path}")


if __name__ == "__main__":
    main()
