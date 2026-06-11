import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI

from src.api.routes import router
from src.brand_loader import load_brands_from_yaml
from src.db import SessionLocal
from src.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    db = SessionLocal()
    try:
        count = load_brands_from_yaml(db)
        logger.info("Startup brand seeding complete: %d brands processed", count)
    except Exception:
        logger.warning("Brand seeding skipped (config/brands.yaml may be missing)")
    finally:
        db.close()
    yield
    stop_scheduler()


app = FastAPI(title="Ads Intel API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
