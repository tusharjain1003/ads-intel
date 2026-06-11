from src.ingest.base import BaseAdAdapter
from src.ingest.meta import MetaAdapter
from src.ingest.tiktok import TikTokAdapter
from src.ingest.microsoft import MicrosoftAdapter

_ADAPTER_MAP: dict[str, type[BaseAdAdapter]] = {
    "meta": MetaAdapter,
    "tiktok": TikTokAdapter,
    "microsoft": MicrosoftAdapter,
}


def get_adapter(source_platform: str) -> BaseAdAdapter:
    """Return a single adapter instance for *source_platform*.

    Raises ``ValueError`` if the platform is unknown.
    """
    cls = _ADAPTER_MAP.get(source_platform.lower())
    if cls is None:
        raise ValueError(
            f"Unknown source platform '{source_platform}'. "
            f"Available: {list(_ADAPTER_MAP)}"
        )
    return cls()


def get_all_adapters() -> list[BaseAdAdapter]:
    """Return one adapter instance for every registered source."""
    return [cls() for cls in _ADAPTER_MAP.values()]
