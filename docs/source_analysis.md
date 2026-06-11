# Source Analysis — Meta, TikTok, Microsoft

## Meta (Facebook Ad Library)

| Aspect | Details |
|--------|---------|
| **Access** | [Meta Ad Library API](https://www.facebook.com/ads/library/api/) — public, no special approval needed for basic access. Requires a Facebook App + access token. |
| **Coverage** | All active ads about social issues, elections, or politics, plus all ads from Pages with a verified Page owner. |
| **Available fields** | Ad creative (title, body, image/video), advertiser name, landing URL, regions, impressions range, spend range, delivery dates, advertiser verification status. |
| **Limitations** | API rate-limited per app; only _active_ ads are queryable; no direct access to targeting criteria via this API; image/video assets expire. |
| **Fixture** | `data/sample_raw/meta_ads.json` — 5 ads (3 scams, 1 genuine HDFC, 1 genuine Amazon). |
| **Why selected** | Largest social ad platform; most impersonation activity reported by Indian banks. |

---

## TikTok (TikTok Ad Library)

| Aspect | Details |
|--------|---------|
| **Access** | [TikTok Ad Library API](https://library.tiktok.com/) — requires a TikTok for Business account + API key. |
| **Coverage** | Ads that ran on TikTok, including those from non-political advertisers. Broader than Meta's library in some regions. |
| **Available fields** | Ad text, advertiser name, landing URL, targeting regions, estimated impressions/spend, ad format, creative assets. |
| **Limitations** | Smaller market share in some demographics; API key requires business verification; fewer historical ads than Meta. |
| **Fixture** | `data/sample_raw/tiktok_ads.json` — 4 ads mirroring the Meta scenarios. |
| **Why selected** | Fast-growing ad platform with distinct user base; scammers increasingly use short-form video. |

---

## Microsoft (Microsoft Ad Library)

| Aspect | Details |
|--------|---------|
| **Access** | [Microsoft Ad Library API](https://about.ads.microsoft.com/en-us/tools/ad-library) — public API with fewer restrictions. |
| **Coverage** | Search, native, and display ads from Microsoft Advertising (Bing, MSN, Outlook.com). |
| **Available fields** | Ad title/description, display URL, destination URL, advertiser name, impressions, spend, ad formats, markets. |
| **Limitations** | No advertiser verification status; fewer fields than Meta/TikTok; primarily search intent rather than interest-based targeting. |
| **Fixture** | `data/sample_raw/microsoft_ads.json` — 4 ads mirroring the Meta scenarios. |
| **Why selected** | Covers search/browser ad surface that social APIs miss; many phishing campaigns use Bing Ads. |

---

## Ingestion scope — how `brands.yaml` controls adapter behaviour

Each adapter implements `fetch_ads(search_terms: List[str])`.  The terms come
from brand names and aliases in `config/brands.yaml`.  At fetch time, the
adapter filters its available ads to those where **any term** appears in:

- `ad_text` (headline + body)
- `advertiser_name`
- `landing_url` or `destination_url`
- Raw JSON payload (recursive string search)

This keeps the ingestion pipeline focused on relevant ads.  Ads that don't
mention any branded term are dropped at the source adapter, before any
normalization or detection work.

## Fixture vs live mode

| Mode | Config | Behaviour |
|------|--------|-----------|
| **Fixture** | `USE_FIXTURES=true` | Reads JSON from `data/sample_raw/{source}_ads.json`; applies the same search-term filter; returns typed models. All MVP development uses this. |
| **Live** | `USE_FIXTURES=false` + API key | Calls the actual API; raises `NotImplementedError` in the provided stubs. The adapter interface is identical — only the fetch backend changes. |
