import hashlib
import json
from typing import Any, Dict, List, Optional

from src.ingest.normalizer import NormalizedAd


# ── Canonicalisation helpers ───────────────────────────────────────────────


def _canonicalize(value: Any) -> Any:
    """Recursively prepare a value for deterministic JSON serialisation.

    - Strings are lowercased and stripped.
    - Lists are sorted (when all elements are strings) and each element is
      canonicalised recursively.
    - Dict keys are sorted and values canonicalised recursively.
    - ``None`` remains ``None``.
    """
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        items = [_canonicalize(v) for v in value]
        if items and all(isinstance(i, str) for i in items):
            items.sort()
        return items
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in sorted(value.items())}
    return value


# ── Public API ─────────────────────────────────────────────────────────────


STABLE_FIELDS = [
    "ad_text",
    "landing_url",
    "advertiser_name",
    "advertiser_verified",
    "regions",
    "platforms",
    "spend_range",
    "impressions_range",
    "creative_urls_normalized",
]


def build_snapshot(normalized_ad: NormalizedAd) -> Dict[str, Any]:
    """Build a stable snapshot dict from a ``NormalizedAd``.

    Only fields listed in ``STABLE_FIELDS`` are included.
    ``raw_payload_json`` is intentionally excluded because the raw
    payload often contains noisy timestamps, request metadata, or
    CDN tokens that would produce false-positive snapshot changes.
    """
    return {field: getattr(normalized_ad, field) for field in STABLE_FIELDS}


def _canonical_json(snapshot: Dict[str, Any]) -> str:
    """Return a deterministic JSON string for *snapshot*.

    The output is suitable for hashing — it is not meant for human
    consumption.  The canonical form lowercases strings, trims
    whitespace, sorts arrays, sorts dict keys, and uses compact
    separators.
    """
    return json.dumps(
        _canonicalize(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_snapshot_hash(snapshot: Dict[str, Any]) -> str:
    """Return a SHA-256 hex digest of the canonical snapshot JSON.

    This hash is used to detect meaningful changes in an ad's content.
    Creative URLs are already normalised by the normalizer before they
    reach this function, so changes in CDN tokens or query parameters
    will not trigger false-positive hash mismatches.
    """
    return hashlib.sha256(_canonical_json(snapshot).encode()).hexdigest()


def compute_changed_fields(
    old_snapshot_json: Dict[str, Any],
    new_snapshot_json: Dict[str, Any],
) -> List[str]:
    """Return top-level field names that differ between two snapshots.

    Example
    -------
    >>> old = {"regions": ["IN"], "platforms": ["facebook"]}
    >>> new = {"regions": ["IN", "US"], "platforms": ["facebook"]}
    >>> compute_changed_fields(old, new)
    ['regions']
    """
    changed: List[str] = []
    all_keys = set(old_snapshot_json) | set(new_snapshot_json)
    for key in sorted(all_keys):
        if _canonicalize(old_snapshot_json.get(key)) != _canonicalize(new_snapshot_json.get(key)):
            changed.append(key)
    return changed


def fallback_dedup_key(normalized_ad: NormalizedAd) -> str:
    """Return a SHA-256 hex digest used as a fallback deduplication key.

    The key is computed from:
    ``ad_text + advertiser_name + landing_domain + first_normalized_creative_url``

    This is useful for sources that do not provide a stable ``source_ad_id``.
    The current MVP does not include a separate ``content_hash`` field.
    """
    parts = [
        normalized_ad.ad_text.strip().lower(),
        normalized_ad.advertiser_name.strip().lower(),
        normalized_ad.landing_domain.strip().lower(),
    ]
    if normalized_ad.creative_urls_normalized:
        parts.append(normalized_ad.creative_urls_normalized[0].strip().lower())
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()
