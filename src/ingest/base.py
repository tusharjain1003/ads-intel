from abc import ABC, abstractmethod
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BaseAdAdapter(ABC):
    """Common interface for all ad-source adapters.

    Subclasses must define *source_platform* and implement
    :meth:`fetch_ads`.  When ``USE_FIXTURES=true`` the adapter
    loads pre-recorded JSON from *fixture_path* and filters it
    against the requested search terms.  Live API calls are not
    implemented in this MVP.
    """

    @property
    @abstractmethod
    def source_platform(self) -> str:
        """Machine-friendly source name, e.g. ``"meta"``."""
        ...

    @property
    @abstractmethod
    def fixture_path(self) -> Path:
        """Path to the fixture JSON file for this source."""

    @abstractmethod
    def fetch_ads(self, search_terms: list[str]) -> list[dict]:
        """Return raw ad payloads matching at least one *search_term*.

        Parameters
        ----------
        search_terms : list[str]
            Brand-related terms (names, aliases, keywords) used to
            scope what is fetched.  Only ads that mention at least
            one term (case-insensitive match on text, advertiser
            name, landing URL, or raw payload) are returned.

        Returns
        -------
        list[dict]
            Source-native ad dicts, **not** normalised yet.
        """
        ...

    def _load_and_filter(self, search_terms: list[str]) -> list[dict]:
        """Load fixture JSON and keep only records matching *search_terms*."""
        if not self.fixture_path.exists():
            logger.warning("Fixture file %s not found", self.fixture_path)
            return []

        with open(self.fixture_path) as f:
            ads = json.load(f)

        if not search_terms:
            return ads

        terms_lower = [t.lower() for t in search_terms]

        def _flatten(ad: dict) -> str:
            """Recursively flatten ad dict into a single lowercase string."""
            parts = []
            for v in ad.values():
                if isinstance(v, dict):
                    parts.append(_flatten(v))
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            parts.append(_flatten(item))
                        else:
                            parts.append(str(item))
                else:
                    parts.append(str(v))
            return " ".join(parts).lower()

        filtered = []
        for ad in ads:
            haystack = _flatten(ad)
            if any(t in haystack for t in terms_lower):
                filtered.append(ad)

        logger.info(
            "%s: %d/%d ads matched search terms",
            self.source_platform,
            len(filtered),
            len(ads),
        )
        return filtered
