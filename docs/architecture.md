# Architecture

## MVP architecture

```
┌──────────────────────────────────────────────────────┐
│                     FastAPI App                        │
│                                                        │
│  ┌────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ /ingest/run │   │ /detections  │   │ /ads, /etc  │  │
│  │ (POST)      │   │ (GET)        │   │ (GET)        │  │
│  └─────┬───────┘   └──────┬───────┘   └──────┬──────┘  │
│        │                  │                   │         │
│  ┌─────┴──────────────────┴───────────────────┴──────┐  │
│  │              run_ingestion(source)                  │  │
│  │  Creates IngestionRun, coordinates pipeline        │  │
│  └─────────────────────┬──────────────────────────────┘  │
│                        │                                  │
└────────────────────────┼──────────────────────────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
    ▼                    ▼                    ▼
┌──────────┐      ┌──────────┐         ┌──────────┐
│  Meta    │      │  TikTok  │         │Microsoft │
│ Adapter  │      │ Adapter  │         │ Adapter  │
└────┬─────┘      └────┬─────┘         └────┬─────┘
     │ (fixture JSON    │  (fixture JSON     │  (fixture JSON
     │  or API call)    │   or API call)     │   or API call)
     └────────┬─────────┴─────────┬──────────┘
              │                   │
              ▼                   ▼
      ┌──────────────┐    ┌──────────────┐
      │  Normalizer  │    │   Detector   │
      │  → NormalizedAd   │  → score_ad_ │
      │  → snapshot hash  │    against_  │
      │  → dedup/upsert   │    brand()   │
      └───────┬───────┘    └──────┬───────┘
              │                   │
              ▼                   ▼
      ┌──────────────────────────────────┐
      │          PostgreSQL              │
      │  ads, ad_versions, detections,   │
      │  ingestion_runs, brands,         │
      │  ad_sources                      │
      └──────────────────────────────────┘
```

## Ingestion-time scope control

Adapters receive `search_terms` derived from `config/brands.yaml`.  Each
adapter filters its available ads to those mentioning a term in ad text,
advertiser name, landing URL, or raw JSON payload.  Result: the pipeline
only processes ads relevant to the monitored brands.

## Fixture vs live adapter interface

Both modes implement the same `BaseAdAdapter` abstract class:

```python
class BaseAdAdapter(ABC):
    source_platform: str
    fixture_path: str

    @abstractmethod
    def fetch_ads(self, search_terms: List[str]) -> List[Ad]:
        ...
```

- **Fixture mode** (`USE_FIXTURES=true`): reads pre-curated JSON from
  `data/sample_raw/`, applies the search-term filter, returns typed models.
- **Live mode** (`USE_FIXTURES=false`): calls the real API and processes the
  response identically.  The stubs raise `NotImplementedError` — implementing
  the API call is the only missing piece for production.

Switching modes requires no changes to the normalizer, dedup logic, or
detection engine.

## Failure handling

| Layer | Behaviour |
|-------|-----------|
| **Adapter fetch** | Errors are caught per source; other sources continue. The run is marked `FAILED` and `error_message` is set. |
| **Ad normalization** | Individual ad failures are counted (`ads_failed`) but do not halt the run. |
| **Detection** | Wrapped in try/except inside the scheduled job; never crashes the API. |
| **Connection** | DB pool uses `pool_pre_ping=True` to detect stale connections. |
| **Scheduler** | `_scheduled_ingestion` catches all exceptions and logs them. An ingestion error does not stop the scheduler. |

## Ingestion idempotency

1. Primary dedup: `(source_platform, source_ad_id)` unique constraint.
2. Fallback dedup: when `source_ad_id` is NULL, a content-based hash of
   `ad_text | advertiser_name | landing_domain | first_creative_url` is used.
3. Re-ingestion of unchanged ads produces `ads_seen += N`, `ads_unchanged += N`,
   but `ads_new = 0`, `ads_updated = 0`, and `detections_triggered = 0`.
4. The detection engine guards against duplicate `(ad_id, brand_id, run_id)`
   rows before inserting.

## Production scaling path

```
Source fetchers (per-platform, rate-limited)
       │
       ▼
Queue (Kafka / SQS)
       │
       ├──► Normalizer workers (horizontal scaling)
       │         │
       │         ├──► Dedup / upsert workers (batch writes)
       │         │
       │         └──► Detection workers
       │
       ├──► DLQ for persistent failures
       │
       └──► Enrichment workers (WHOIS, VirusTotal, Safe Browsing,
               creative pHash, domain-age lookup)
```

- **Per-source rate limits**: token-bucket per platform; backpressure via
  queue depth.
- **DLQ**: ads that consistently fail normalization are moved to a dead-letter
  queue for manual review.
- **Creative hashing**: download assets in a background worker, compute
  perceptual hash, store on the `ads` table, use for cross-platform
  visual dedup.
- **Cross-platform clustering**: group ads by (advertiser fingerprint +
  domain SLD + creative pHash) into campaign clusters.
- **Analyst feedback**: false-positive reporting endpoint to tune per-brand
  thresholds and approved lists.
- **Alerting**: send HIGH-severity detections to Slack/email/PagerDuty.
