# Schema — 6 Tables

## `ad_sources`

Registers each platform with its mode (`LIVE` | `FIXTURE`) and base URL.
Seeded during `alembic upgrade head`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `platform_name` | VARCHAR(50) | `meta`, `tiktok`, `microsoft` (unique) |
| `base_url` | VARCHAR(255) | API endpoint |
| `adapter_mode` | VARCHAR(10) | `LIVE` or `FIXTURE` |
| `last_successful_run_at` | TIMESTAMP | Updated after each successful ingestion |

---

## `ads`

The unified ad record.  Each row represents one ad from one platform.
Joins to `ad_versions` (1:N) and `detections` (1:N).

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `source_platform` | VARCHAR(20) | `meta`, `tiktok`, `microsoft` |
| `source_ad_id` | VARCHAR(255) | Native ID from the source (nullable for sources without stable IDs) |
| `advertiser_name` | VARCHAR(255) | Normalized advertiser |
| `advertiser_verified` | BOOLEAN | Whether the source marks the advertiser as verified |
| `ad_text` | TEXT | Concatenated headline + body |
| `landing_url` | TEXT | Raw destination URL |
| `landing_domain` | VARCHAR(255) | Extracted domain (scheme + path stripped) |
| `regions` | JSONB | List of target region codes |
| `platforms` | JSONB | List of ad distribution channels |
| `spend_range` | JSONB | `{"min": …, "max": …}` |
| `impressions_range` | JSONB | `{"min": …, "max": …}` |
| `creative_urls_normalized` | JSONB | List of asset URLs with query params stripped |
| `first_seen_at` | TIMESTAMP | When this ad was first observed |
| `last_seen_at` | TIMESTAMP | When this ad was last observed |
| `status` | VARCHAR(20) | `NEW` → `ACTIVE` → `UPDATED` → `INACTIVE` |
| `snapshot_hash` | VARCHAR(64) | SHA-256 of canonical fields (see below) |
| `raw_payload_json` | JSONB | Full original payload from the source |
| `created_at` / `updated_at` | TIMESTAMP | Audit timestamps |

### Unique constraint

`(source_platform, source_ad_id)` — if the source provides an ID, it is the
primary dedup key.  A content-based fallback exact match
(`source_platform + landing_domain + advertiser_name + ad_text`) is used when
`source_ad_id` is NULL.

A composite index `ix_ads_fallback_dedup` on
`(source_platform, landing_domain, advertiser_name)` accelerates the fallback
lookup.  `ad_text` is excluded from the index (it is a large `TEXT` column)
and remains a final exact-match filter applied after the indexed columns are
matched.

### `snapshot_hash`

SHA-256 over a canonical JSON document of **stable fields only**:

```
ad_text, landing_url, advertiser_name, advertiser_verified,
regions, platforms, spend_range, impressions_range,
creative_urls_normalized
```

`landing_domain` is not included in the snapshot hash — it is derived from
`landing_url` and stored separately in the `ads` table for performant querying
and detection lookup.

`raw_payload_json` is **excluded** because source APIs often embed volatile
timestamps, request IDs, or caching metadata that would cause false-positive
hash mismatches on every poll.

### Creative URL normalization

Before hashing, each creative URL has its query parameters stripped
(`?expires=…&sig=…&token=…`).  This prevents CDN tokens from triggering false
updates when the asset itself hasn't changed.

### Status transitions

```
                 ┌────► UPDATED ◄────┐
                 │        │          │
NEW ──► ACTIVE ──┘        │          │
                           │          │
                      INACTIVE ◄──────┘
```

- **NEW** — first appearance.
- **ACTIVE** — persisted after the first ingestion run completes successfully.
- **UPDATED** — a re-ingestion finds a different `snapshot_hash`.  Prior
  snapshots are preserved in `ad_versions`.
- **INACTIVE** — not seen for `INACTIVE_AFTER_DAYS` days (not triggered
  automatically in MVP; reserved for a background sweep job).

---

## `ingestion_runs`

Each call to `run_ingestion()` creates one row.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `source_platform` | VARCHAR(20) | `meta`, `tiktok`, `microsoft`, or `all` |
| `started_at` / `completed_at` | TIMESTAMP | Run lifecycle |
| `status` | VARCHAR(20) | `RUNNING` → `SUCCESS` / `PARTIAL_SUCCESS` / `FAILED` |
| `ads_seen` / `_new` / `_updated` / `_unchanged` / `_failed` | INTEGER | Counters |
| `detections_triggered` | INTEGER | Number of detection rows created |
| `error_message` | TEXT | Concise adapter/per-record error summary for `FAILED` or `PARTIAL_SUCCESS` runs |

---

## `ad_versions`

Immutable history of every snapshot for an ad.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `ad_id` | UUID FK → `ads.id` | Parent ad |
| `version_number` | INTEGER | Monotonically increasing per ad |
| `snapshot_hash` | VARCHAR(64) | Hash at the time of capture |
| `changed_fields` | JSONB | `["ad_text", "spend_range", …]` List of field names that differ from the previous version |
| `snapshot_json` | JSONB | Full canonical snapshot at this version |
| `raw_payload_json` | JSONB | Original payload at the time of capture |
| `seen_at` | TIMESTAMP | When this version was observed |
| `ingestion_run_id` | UUID FK → `ingestion_runs.id` | The run that produced this version |

For the first version, `changed_fields` contains all snapshot fields.
Subsequent versions list only the fields whose normalized values differ.

---

## `brands`

Monitored brands loaded from `config/brands.yaml` at startup.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `name` | VARCHAR(255) | Display name (unique) |
| `aliases` | JSONB | `["HDFC", "HDFC Bank", "HDFCBank"]` |
| `official_domains` | JSONB | `["hdfcbank.com"]` |
| `approved_advertisers` | JSONB | `["HDFC Bank"]` |
| `suspicious_keywords` | JSONB | `["kyc", "urgent", "account blocked"]` |

---

## `detections`

Output of the brand-impersonation engine.  One row per (ad, brand, run) where
`risk_score >= 40`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `ad_id` | UUID FK → `ads.id` | Flagged ad |
| `brand_id` | UUID FK → `brands.id` | Impersonated brand |
| `triggered_by_run_id` | UUID FK → `ingestion_runs.id` | The run that created this |
| `risk_score` | INTEGER | Sum of triggered signal weights (max possible ~200+) |
| `severity` | VARCHAR(10) | `LOW` / `MEDIUM` / `HIGH` |
| `signals` | JSONB | Machine-readable list: `[{"name": "…", "weight": N, "matched_value": "…"}]` |
| `reasons` | JSONB | Human-readable list: `["Brand alias 'hdfc' found in ad text", …]` |

A fresh run never duplicates an existing `(ad_id, brand_id, triggered_by_run_id)`.

---

## Why `content_hash` is not used

A separate `content_hash` (perceptual hash of the creative image) would be
valuable for cross-platform visual dedup.  It is omitted from MVP because:

1. Creative images are URLs, not binaries — downloading every asset at
   ingestion time adds latency and failure modes.
2. The live API stubs don't return real images.
3. Cross-platform clustering is explicitly out of scope for this release.

If added, `content_hash` would live on the `ads` table and participate in a
separate dedup step after a background download worker fetches the creative
URLs.
