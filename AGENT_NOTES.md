# AGENT NOTES

This file documents how I used an AI coding assistant (OpenCode) to build
this take-home assignment, what I corrected, and what I would improve.

---

## 1. Initial planning

I decomposed the assignment into sequential phases before writing any code:

1. **Schema + DB** — design the tables and relationships first
2. **Ingestion pipeline** — adapters, normalizer, dedup, upsert
3. **Detection engine** — scoring, relevance gate, persistence
4. **API layer** — FastAPI routes for demo access
5. **Docs + samples** — output artifacts for reviewers

I chose a **fixture-first approach** because the live ad library APIs (Meta,
TikTok, Microsoft) typically require business verification and app review.
Fixtures let me build and test the full pipeline without credentials, and the
adapter interface is identical in both modes — switching to live requires only
implementing the API call.

I chose **Postgres over SQLite or MongoDB** because the core entities (ads,
brands, ingestion runs, detections) are relational and need ACID-compliant
upserts with referential integrity and versioning.  JSONB columns on the same
Postgres tables still allow flexible source payloads, targeting regions,
detection signals, and reasons to be stored without a rigid schema — the best
of both worlds for an ingestion pipeline where raw payload shapes vary per
source.

---

## 2. Prompt sequence

The major steps I asked the agent to execute, in order:

1. **Project scaffold** — Docker Compose, FastAPI skeleton, config, DB session
2. **DB models + Alembic migration** — 6 tables with relationships
3. **Brand config loader** — YAML-based brand definitions, seeded at startup
4. **Fixture data** — realistic Meta/TikTok/Microsoft ads with genuine and scam variants
5. **Source adapters** — `BaseAdAdapter` interface, fixture-backed implementations
6. **Normalizer** — source-specific mappers → unified `NormalizedAd`
7. **Snapshot hash + changed_fields** — stable-field hashing for dedup/update tracking
8. **Ingestion service** — pipeline orchestration, upsert with primary/fallback dedup
9. **Detection scoring** — 6 rules, severity thresholds, explainable signals
10. **API endpoints** — 10 FastAPI routes for demo access
11. **Scheduler** — APScheduler integration (disabled by default)
12. **Sample outputs** — script to generate reviewer-friendly JSON artifacts
13. **Documentation** — README, schema, source analysis, detection logic, architecture

On the first pass, the agent correctly scaffolded the Docker Compose setup,
FastAPI app factory, SQLAlchemy engine/session, and the Pydantic-settings
config without needing structural corrections.  The adapter interface,
normalizer, and scheduler also came out close to the final version —
most corrections were in edge-case handling (idempotency, URL normalization,
false-positive guardrails) rather than fundamental architecture.

---

## 3. Important corrections I made to agent output

The agent produced reasonable first drafts, but several things needed fixing:

- **Schema redesign** — The initial output used a single `AdCreative` model
  with everything in one table.  I rejected it and specified the final
  6-table relational schema with `ads`, `ad_versions`, `ingestion_runs`,
  `brands`, `detections`, and `ad_sources`.

- **Docker/Python runtime issues** — `jellyfish` version was pinned wrong in
  requirements; `PYTHONPATH` missing in the Dockerfile; the Postgres service
  host was `localhost` instead of `postgres`; `POSTGRES_DB` env var was not
  passed.  Each of these broke `docker compose up` on the first attempt.

- **Update tracking instability** — The first version hashed the entire
  `raw_payload_json` to detect changes.  Source APIs embed volatile
  timestamps and request IDs, so every re-ingestion produced false updates.
  I changed it to a **stable snapshot** of 9 canonical fields, excluding
  `raw_payload_json`.

- **Creative URL normalization** — CDN URLs in fixture data contained
  `?expires=…&sig=…&token=…` query params.  Without normalization, the same
  asset re-fetched at a different time produced a different snapshot hash.
  I added query-param stripping to the normalizer.

- **Fixture duplicate source_ad_id** — Two fixture ads had the same
  `source_ad_id`, causing the second to be treated as an update of the first.
  Every re-ingestion produced a false update because the unique constraint
  forced a match against the wrong ad.  I fixed the fixture data to use
  distinct IDs.

- **False positives in detection** — Genuine ads on `www.hdfcbank.com` and
  `www.amazon.in` were flagged because `www.` was not stripped before
  comparison against official domains.  Similarly, "HDFC Bank" as an
  advertiser didn't match because of trailing whitespace or case mismatch.
  I fixed domain normalization and made advertiser matching case-insensitive.

- **Brand relevance gate** — Without a gate, every ad was scored against
  every brand.  A genuine HDFC ad with advertiser "HDFC Bank" on
  `www.hdfcbank.com` would be scored against SBI and Amazon India purely
  because it wasn't in *those* brands' approved lists, producing spurious
  MEDIUM detections.  I added a 5-condition relevance gate that silently
  skips unrelated brand/ad pairs.

- **Scheduler default** — The agent set `INGESTION_INTERVAL_MINUTES=15` in
  `.env`, which would start periodic ingestion during reviewer demos without
  warning.  I changed it to `0` (disabled) with a comment explaining how to
  enable it.

---

## 4. Manual review areas

I personally verified each of these after the agent produced the code:

- `docker compose down -v && docker compose up --build` starts Postgres and
  the API without errors
- Alembic migration creates all 6 tables and seeds `ad_sources` with 3 rows
- Brand loader seeds 3 brands (`config/brands.yaml`) on FastAPI startup
- First `run_ingestion(source="meta")` creates 5 new ads and 3 detections
- Second `run_ingestion(source="meta")` produces 0 new ads, 0 updated ads, and 5 unchanged ads
- Detection output lists the 3 expected scams (HDFC KYC 105, SBI blocked 75,
  Amazon gift card 150) and nothing else for the 5 Meta ads
- All 10 API endpoints return reviewer-friendly JSON with proper 404/400
  handling
- `scripts/generate_sample_outputs.py` writes pretty-printed output files

---

## 5. What I would improve with more time

With additional time (beyond the take-home scope), I would add:

- **Live API adapters** — Implement actual API calls for Meta, TikTok, and
  Microsoft using the adapter interface that already exists.
- **WHOIS / domain-age enrichment** — Cross-reference landing domains against
  WHOIS data; flag recently registered domains.
- **VirusTotal / Google Safe Browsing** — Check landing URLs against known
  threat intelligence feeds.
- **Cross-platform scam clustering** — Group detections by (advertiser SLD,
  creative text fingerprint) across platforms to identify coordinated
  campaigns.
- **Creative perceptual hashing** — Download and pHash creative images for
  visual dedup and clustering.
- **Analyst feedback loop** — Endpoint to mark detections as false
  positive/negative and use that feedback to tune per-brand thresholds.
