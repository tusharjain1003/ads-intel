import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────


def normalize_text(value: Optional[str]) -> str:
    """Return a stripped string, falling back to empty string for ``None``."""
    return (value or "").strip()


def extract_domain(url: str) -> str:
    """Extract the domain (netloc) from *url*, lowercased.

    Returns empty string if the URL is empty or invalid.
    """
    if not url:
        return ""
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def normalize_url_for_snapshot(url: str) -> str:
    """Strip query strings and fragments from *url*.

    Returns ``scheme://netloc/path`` lowercased (scheme and host only).
    Returns empty string for invalid or missing URLs.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return urlunparse(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", "")
        )
    except Exception:
        return ""


# ── Pydantic model ─────────────────────────────────────────────────────────


class NormalizedAd(BaseModel):
    source_platform: str
    source_ad_id: Optional[str]
    advertiser_name: str
    advertiser_verified: Optional[bool]
    ad_text: str
    landing_url: str
    landing_domain: str
    regions: List[str]
    platforms: List[str]
    spend_range: Optional[Dict[str, Any]]
    impressions_range: Optional[Dict[str, Any]]
    creative_urls_normalized: List[str]
    raw_payload_json: Dict[str, Any]


# ── Source-specific normalizers ────────────────────────────────────────────


def _normalize_meta(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_ad_id": raw.get("id"),
        "advertiser_name": normalize_text(raw.get("page_name")),
        "advertiser_verified": raw.get("page_verified"),
        "ad_text": normalize_text(raw.get("ad_creative_body")),
        "landing_url": normalize_text(raw.get("landing_page_url")),
        "regions": raw.get("targeted_or_reached_countries", []),
        "platforms": raw.get("publisher_platforms", []),
        "spend_range": raw.get("spend"),
        "impressions_range": raw.get("impressions"),
        "creative_urls_normalized": sorted(
            normalize_url_for_snapshot(u) for u in raw.get("creative_media_urls", []) if u
        ),
    }


def _normalize_tiktok(raw: Dict[str, Any]) -> Dict[str, Any]:
    advertiser = raw.get("advertiser", {}) or {}
    media_list = raw.get("media", []) or []
    return {
        "source_ad_id": raw.get("ad_id"),
        "advertiser_name": normalize_text(advertiser.get("name")),
        "advertiser_verified": advertiser.get("verified"),
        "ad_text": normalize_text(raw.get("text")),
        "landing_url": normalize_text(raw.get("destination_url")),
        "regions": raw.get("countries", []),
        "platforms": raw.get("placements", []),
        "spend_range": (raw.get("metrics") or {}).get("spend_range"),
        "impressions_range": (raw.get("metrics") or {}).get("impression_range"),
        "creative_urls_normalized": sorted(
            normalize_url_for_snapshot(m.get("url", ""))
            for m in media_list
            if m.get("url")
        ),
    }


def _normalize_microsoft(raw: Dict[str, Any]) -> Dict[str, Any]:
    title = normalize_text(raw.get("adTitle"))
    desc = normalize_text(raw.get("adDescription"))
    ad_text = f"{title} {desc}".strip()

    return {
        "source_ad_id": raw.get("adId"),
        "advertiser_name": normalize_text(raw.get("advertiserName")),
        "advertiser_verified": raw.get("isAdvertiserVerified"),
        "ad_text": ad_text,
        "landing_url": normalize_text(raw.get("destinationUrl")),
        "regions": raw.get("markets", []),
        "platforms": raw.get("adFormats", []),
        "spend_range": raw.get("estimatedSpend"),
        "impressions_range": raw.get("estimatedImpressions"),
        "creative_urls_normalized": sorted(
            normalize_url_for_snapshot(u) for u in raw.get("assetUrls", []) if u
        ),
    }


_NORMALIZERS = {
    "meta": _normalize_meta,
    "tiktok": _normalize_tiktok,
    "microsoft": _normalize_microsoft,
}


# ── Public API ─────────────────────────────────────────────────────────────


def normalize_ad(source_platform: str, raw_ad: Dict[str, Any]) -> NormalizedAd:
    """Normalize a raw source ad dict into a ``NormalizedAd``.

    Parameters
    ----------
    source_platform : str
        One of ``"meta"``, ``"tiktok"``, or ``"microsoft"``.
    raw_ad : dict
        The source-native ad payload.

    Returns
    -------
    NormalizedAd

    Raises
    ------
    ValueError
        If *source_platform* is unknown or a required field is missing.
    """
    normalizer = _NORMALIZERS.get(source_platform)
    if normalizer is None:
        raise ValueError(
            f"Unknown source_platform '{source_platform}'. "
            "Supported: meta, tiktok, microsoft"
        )

    try:
        fields = normalizer(raw_ad)
    except (KeyError, TypeError, IndexError) as exc:
        ad_id = raw_ad.get("id") or raw_ad.get("ad_id") or raw_ad.get("adId") or "<unknown>"
        raise ValueError(
            f"Failed to normalize {source_platform} ad {ad_id}: {exc}"
        ) from exc

    if not fields.get("advertiser_name"):
        raise ValueError(
            f"Missing required field 'advertiser_name' for {source_platform} "
            f"ad {fields.get('source_ad_id', '<unknown>')}"
        )

    landing_url = fields["landing_url"]
    return NormalizedAd(
        source_platform=source_platform,
        source_ad_id=fields["source_ad_id"],
        advertiser_name=fields["advertiser_name"],
        advertiser_verified=fields["advertiser_verified"],
        ad_text=fields["ad_text"],
        landing_url=landing_url,
        landing_domain=extract_domain(landing_url),
        regions=fields["regions"],
        platforms=fields["platforms"],
        spend_range=fields["spend_range"],
        impressions_range=fields["impressions_range"],
        creative_urls_normalized=fields["creative_urls_normalized"],
        raw_payload_json=raw_ad,
    )
