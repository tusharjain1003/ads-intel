import logging

import yaml
from sqlalchemy.orm import Session

from src.models import Brand

logger = logging.getLogger(__name__)

BRANDS_YAML_PATH = "config/brands.yaml"


def load_brands_from_yaml(db: Session, path: str = BRANDS_YAML_PATH) -> int:
    with open(path) as f:
        data = yaml.safe_load(f)

    brands_data = data.get("brands", [])
    count = 0

    for entry in brands_data:
        name = entry["name"]
        existing = db.query(Brand).filter_by(name=name).first()
        if existing:
            existing.aliases = entry.get("aliases", [])
            existing.official_domains = entry.get("official_domains", [])
            existing.approved_advertisers = entry.get("approved_advertisers", [])
            existing.suspicious_keywords = entry.get("suspicious_keywords", [])
        else:
            brand = Brand(
                name=name,
                aliases=entry.get("aliases", []),
                official_domains=entry.get("official_domains", []),
                approved_advertisers=entry.get("approved_advertisers", []),
                suspicious_keywords=entry.get("suspicious_keywords", []),
            )
            db.add(brand)
        count += 1

    db.commit()
    logger.info("Loaded %d brands from %s", count, path)
    return count
