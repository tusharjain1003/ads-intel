# Ads Intel Repository — Ad Aggregation + Brand Impersonation Detection

This MVP aggregates ads from Meta, TikTok, and Microsoft-style ad libraries
into a unified repository and runs explainable brand impersonation detection on
new/updated ads.

## What is implemented

- Fixture-backed adapters for Meta, TikTok, Microsoft
- Config-driven scope using `config/brands.yaml`
- Unified Postgres schema (6 tables, Alembic migrations)
- Snapshot-based new/updated/unchanged tracking
- Brand impersonation detection with explainable signals
- FastAPI demo endpoints (10 routes)
- APScheduler integration (disabled by default for demos)
- Sample outputs in `data/sample_outputs/`

## Architecture (text flow)

```
brands.yaml
    │
    ▼
source adapters ──► normalizer ──► snapshot hash + dedup/upsert ──► Postgres
    │                                                                    │
    └── scope control via search terms                                   │
                                                                         ▼
                                                                 detection engine
                                                                         │
                                                                         ▼
                                                                   API / report
```

## How to run

```bash
cp .env.example .env              # uses fixtures by default
docker compose up --build
```

The API is at `http://localhost:8000`.  See `docs/` for deep dives.

## Demo flow

```bash
# 1. Trigger ingestion for Meta ads
curl -X POST "http://localhost:8000/ingest/run?source=meta"

# 2. Check the ingestion run summary
curl -s "http://localhost:8000/ingestion-runs" | python3 -m json.tool

# 3. View detections with signals and reasons
curl -s "http://localhost:8000/detections" | python3 -m json.tool
```

Expected: 5 Meta ads ingested → 3 impersonation detections (HDFC KYC scam
105 HIGH, SBI account-blocked 75 HIGH, Amazon gift-card scam 150 HIGH).

Running all sources by omitting the `source` parameter ingests the
fixture-backed Meta, TikTok, and Microsoft datasets.  Exact counts may differ
as fixtures evolve, but the response includes `ads_seen`, `ads_new`,
`ads_updated`, `ads_unchanged`, `ads_failed`, and `detections_triggered` for
verification.

## Important endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/ingest/run?source=meta` | Trigger ingestion (omit source for all) |
| GET | `/ingestion-runs` | Latest 50 runs |
| GET | `/ingestion-runs/{id}/summary` | Single run summary |
| GET | `/ads` | Latest 100 ads |
| GET | `/ads/{id}` | Full ad with raw payload |
| GET | `/ad-versions/{id}` | Version history for an ad |
| GET | `/brands` | Configured brands |
| GET | `/detections` | Detection list with ad+brand context |
| GET | `/detections/{id}` | Single detection |

## Source choices

- **Meta + TikTok** — dominant social ad platforms with public/partner APIs.
- **Microsoft** — search / native / display ad network; complements social coverage.

All three expose advertiser name, landing URL, creative assets, targeting
regions, and spend ranges — enough for meaningful impersonation analysis.

## Known limitations

- **Fixture mode by default** — Ad library APIs often require business
  verification and app review; fixtures let you evaluate the full pipeline
  without credentials.  Set `USE_FIXTURES=false` and provide API keys for
  live mode (currently raises `NotImplementedError`).
- **No cross-platform clustering** — Dedup runs within a source only.
  The same campaign on Meta and TikTok produces two separate ad records.
- **No enrichment** — WHOIS, VirusTotal, domain-age lookups are not
  implemented.  Detection relies solely on ad metadata and brand config.
- **No frontend** — API-only.  Review outputs via curl or a REST client.
- **Simplified domain parsing** — `_extract_sld` uses a simple heuristic for
  two-part TLDs; some edge cases (`.com.au`, `.co.uk`) are covered but
  the full Public Suffix List is not used.

## Production scaling path

```
Source fetchers  ──►  queue (Kafka / SQS)
                         │
                    normalizer workers  ──►  dedup / upsert workers
                         │                         │
                         │                    detection workers
                         │                         │
                         │                    enrichment / alerting
                         │
                    ──►  DLQ for malformed / repeated failures
```

- Per-source rate-limit polling with backpressure.
- Domain enrichment via WHOIS, VirusTotal, Google Safe Browsing.
- Creative perceptual hashing (pHash) to cluster visual duplicates.
- Cross-platform campaign clustering by advertiser + domain + creative hash.
- Analyst feedback loop (false-positive reporting, threshold tuning).
