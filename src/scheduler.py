import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(daemon=True)

_JOB_ID = "periodic_ingestion"


def _scheduled_ingestion():
    """Wrapper around ``run_ingestion`` that logs outcomes and never raises."""
    from src.ingest.service import run_ingestion

    logger.info("Scheduled ingestion started")
    try:
        result = run_ingestion(source=None)
        logger.info(
            "Scheduled ingestion finished: seen=%d new=%d updated=%d unchanged=%d failed=%d detections=%d",
            result["ads_seen"],
            result["ads_new"],
            result["ads_updated"],
            result["ads_unchanged"],
            result["ads_failed"],
            result["detections_triggered"],
        )
    except Exception:
        logger.exception("Scheduled ingestion failed")


def start_scheduler():
    interval = settings.ingestion_interval_minutes
    if interval <= 0:
        logger.info("INGESTION_INTERVAL_MINUTES=%d — periodic ingestion disabled", interval)
        return

    # Idempotency guard: avoid duplicate jobs on Uvicorn reload
    if scheduler.get_job(_JOB_ID) is not None:
        logger.info("Scheduled ingestion job already exists — skipping")
        return

    scheduler.add_job(
        _scheduled_ingestion,
        trigger=IntervalTrigger(minutes=interval),
        id=_JOB_ID,
        replace_existing=False,
        name="Periodic ingestion (all sources)",
    )
    scheduler.start()
    logger.info("Periodic ingestion scheduled every %d minute(s)", interval)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
