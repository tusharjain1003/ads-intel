# Detection Logic

## Brand configuration format

Brands are defined in `config/brands.yaml`:

```yaml
- id: hdfc-bank
  name: HDFC Bank
  aliases:
    - HDFC Bank
    - HDFC
    - hdfcbank
  official_domains:
    - hdfcbank.com
  approved_advertisers:
    - HDFC Bank
  suspicious_keywords:
    - kyc
    - urgent
    - account blocked
    - verification
    - update required
    - free gift
```

## Scoring rules

Each rule fires independently and adds its weight to the total `risk_score`.

| # | Rule | Weight | Condition |
|---|------|--------|-----------|
| 1 | Brand in ad text | +20 | Brand name or alias found in ad body (case-insensitive substring) |
| 2 | Unapproved advertiser | +25 | Advertiser not in brand's `approved_advertisers` list |
| 3 | Unofficial domain | +30 | Landing domain not in `official_domains` (and not a subdomain) |
| 4 | Lookalike domain | +35 | Landing domain's SLD resembles an official domain (jaro-winkler ≥ 0.85) AND domain is not already official |
| 5 | Suspicious keyword | +10 each | Each suspicious keyword found in ad text |
| 6 | Advertiser similar to brand | +20 | Advertiser name matches brand name/alias at ≥ 0.85 jaro-winkler but is not an exact match |

Maximum theoretical score with all signals: ~200+ (unbounded keyword hits).

## Severity thresholds

| Score | Severity |
|-------|----------|
| 0–39 | (no detection created) |
| 40–69 | MEDIUM |
| 70+ | HIGH |

Detections below 40 are discarded — the row is never written to the database.

## Signals vs reasons — why both?

- **Signals** — machine-readable `[{name, weight, matched_value}]`.  Designed
  for automated triage: "which rules fired and what did they match?"
- **Reasons** — human-readable sentences.  Designed for analyst review:
  "Suspicious keyword 'kyc' found in ad text."

Both are stored as JSONB on the `detections` row.

## Brand relevance gate

Before scoring, `_is_relevant_to_brand()` checks whether the ad is even
plausibly related to the brand.  This prevents genuine HDFC ads (advertiser
"HDFC Bank", domain "www.hdfcbank.com") from being flagged against SBI or
Amazon India just because they're not in those brands' approved lists.

Returns `True` if **any** of these holds:

1. Brand name/alias appears in ad text (substring).
2. Advertiser name is similar to brand name/alias (jaro-winkler ≥ 0.85).
3. Landing domain's SLD resembles an official domain SLD (≥ 0.85).
4. Landing domain contains a brand token at a word boundary (e.g. `\bhdfc\b`
   in `hdfc-kyc-help.com`, but not `\bbank\b` inside `hdfcbank` without a
   boundary).
5. A suspicious keyword hits **and** a brand alias appears anywhere in ad
   text, advertiser name, or domain.

If the gate returns `False`, `score_ad_against_brand` returns `(0, [], [])`
immediately — no scoring work is done.

## Domain normalization

```python
def normalize_domain(domain: str) -> str:
    d = domain.lower().strip()
    if d.startswith("www."):
        d = d[4:]
    d = d.rstrip("/ ")
    return d
```

Official domain matching uses `d == od or d.endswith("." + od)`, so
`login.hdfcbank.com` matches `hdfcbank.com` but `hdfc-kyc-help.com` does not.

## Lookalike domain detection

Uses `jellyfish.jaro_winkler_similarity` on the **second-level domain** (SLD)
after handling two-part TLDs (`co.in`, `com.au`, etc.).  `_extract_sld` covers
common country-coded TLDs but does not use the full Public Suffix List.

Threshold: `>= 0.85`.  This catches:

- `hdfc-kyc-help.com` → SLD `hdfc-kyc-help` vs `hdfcbank` → 0.90 ✅
- `amazon-rewards-gift.net` → `amazon-rewards-gift` vs `amazon` → 0.87 ✅
- `sbi-accountverify.net` → `sbi-accountverify` vs `sbi` → 0.86 ✅

## False-positive / false-negative tradeoffs

| Direction | Cause | Mitigation |
|-----------|-------|------------|
| **False positive** | Genuine ad from unapproved advertiser on unofficial domain but real product | Relevance gate filters unrelated brands; score threshold ≥ 40 removes low-signal matches; official domain matching (including subdomains) reduces unofficial-domain flags for legitimate partners. |
| **False positive** | Short domain SLD accidentally similar to brand | `_extract_sld` ignores SLDs ≤ 2 chars; the relevance gate requires brand token in domain at a word boundary rather than loose substring. |
| **False negative** | Scammer uses exact official domain (subdomain takeover or cloaking) | Domain is marked official → no `unofficial_domain` or `lookalike_domain` signal.  Mitigated by other signals: unapproved advertiser (+25), suspicious keywords (+10 each). |
| **False negative** | Scam ad doesn't mention any brand alias | No `brand_in_ad_text` (+20) and relevance gate fails → ad never scored against that brand.  Scope control via `brands.yaml` is the intended mechanism. |

## Example walkthrough — HDFC KYC phishing ad

**Input**:
- `ad_text`: "URGENT: Update your HDFC account KYC verification now to avoid
  suspension. Click here: https://hdfc-kyc-help.com"
- `advertiser_name`: "KYC Update Centre"
- `landing_domain`: "hdfc-kyc-help.com"

**Brand config** (HDFC Bank):
- `aliases`: `["HDFC Bank", "HDFC", "hdfcbank"]`
- `official_domains`: `["hdfcbank.com"]`
- `approved_advertisers`: `["HDFC Bank"]`
- `suspicious_keywords`: `["kyc", "urgent", "verification"]`

**Relevance gate**: `"hdfc"` in ad text → **passes**.

| Signal | Weight | Reason |
|--------|--------|--------|
| Brand in ad text | +20 | `"hdfc"` found in text |
| Unapproved advertiser | +25 | `"KYC Update Centre"` not in approved list |
| Unofficial domain | +30 | `"hdfc-kyc-help.com"` ≠ `"hdfcbank.com"` |
| Lookalike domain | +35 | SLD `hdfc-kyc-help` ~ `hdfcbank` ≥ 0.85 |
| Suspicious keyword `"kyc"` | +10 | Found in text |
| Suspicious keyword `"urgent"` | +10 | Found in text |
| Suspicious keyword `"verification"` | +10 | Found in text |
| **Total** | **140** | |

**Severity**: 140 ≥ 70 → **HIGH**.  Detection is inserted.
