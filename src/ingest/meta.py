from pathlib import Path

from src.config import settings
from src.ingest.base import BaseAdAdapter


class MetaAdapter(BaseAdAdapter):
    """Adapter for Meta (Facebook/Instagram) Ads Library.

    Fixture mode reads ``data/sample_raw/meta_ads.json``.
    Live mode is not implemented and raises ``NotImplementedError``.
    """

    @property
    def source_platform(self) -> str:
        return "meta"

    @property
    def fixture_path(self) -> Path:
        return Path("data/sample_raw/meta_ads.json")

    def fetch_ads(self, search_terms: list[str]) -> list[dict]:
        if settings.use_fixtures:
            return self._load_and_filter(search_terms)
        raise NotImplementedError(
            "Live API mode is not implemented for Meta. "
            "Set USE_FIXTURES=true or provide a META_API_TOKEN."
        )
