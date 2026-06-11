from pathlib import Path

from src.config import settings
from src.ingest.base import BaseAdAdapter


class TikTokAdapter(BaseAdAdapter):
    """Adapter for TikTok Commercial Content Library.

    Fixture mode reads ``data/sample_raw/tiktok_ads.json``.
    Live mode is not implemented and raises ``NotImplementedError``.
    """

    @property
    def source_platform(self) -> str:
        return "tiktok"

    @property
    def fixture_path(self) -> Path:
        return Path("data/sample_raw/tiktok_ads.json")

    def fetch_ads(self, search_terms: list[str]) -> list[dict]:
        if settings.use_fixtures:
            return self._load_and_filter(search_terms)
        raise NotImplementedError(
            "Live API mode is not implemented for TikTok. "
            "Set USE_FIXTURES=true or provide a TIKTOK_API_KEY."
        )
