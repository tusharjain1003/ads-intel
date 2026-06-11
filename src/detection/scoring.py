import re
from typing import List, Optional

import jellyfish


def normalize_domain(domain: str) -> str:
    """Lowercase, strip leading ``www.``, and remove trailing slash/space."""
    d = domain.lower().strip()
    if d.startswith("www."):
        d = d[4:]
    d = d.rstrip("/ ")
    return d


def is_official_domain(domain: str, official_domains: List[str]) -> bool:
    """Return ``True`` if *domain* is an exact match or subdomain of an official domain.

    ``login.hdfcbank.com`` matches ``hdfcbank.com``.
    ``www.hdfcbank.com`` matches ``hdfcbank.com``.
    ``hdfc-kyc-help.com`` does **not** match ``hdfcbank.com``.
    """
    d = normalize_domain(domain)
    for official in official_domains:
        od = normalize_domain(official)
        if d == od or d.endswith("." + od):
            return True
    return False


def _extract_sld(domain: str) -> str:
    """Extract the second-level (registrable) portion of a domain.

    Handles common two-part TLDs like ``co.in``, ``com.au``.
    """
    parts = normalize_domain(domain).split(".")
    parts = [p for p in parts if p]
    if len(parts) <= 2:
        return parts[0] if parts else ""
    if len(parts) >= 3 and parts[-1] in {"in", "uk", "au", "jp", "br", "kr", "nz"}:
        if parts[-2] in {"co", "org", "gov", "ac", "net", "com", "gen"}:
            return parts[-3] if len(parts) >= 4 else parts[-3]
    return parts[-2]


def is_lookalike_domain(domain: str, official_domains: List[str]) -> bool:
    """Return ``True`` if the registered SLD of *domain* resembles an official SLD.

    Uses ``jellyfish.jaro_winkler_similarity`` with a threshold of 0.85.
    """
    d_sld = _extract_sld(domain)
    if not d_sld:
        return False
    for official in official_domains:
        o_sld = _extract_sld(official)
        if o_sld and len(o_sld) > 2:
            similarity = jellyfish.jaro_winkler_similarity(d_sld, o_sld)
            if similarity >= 0.85:
                return True
    return False


def advertiser_similar_to_brand(advertiser_name: str, brand_name: str, aliases: List[str]) -> bool:
    """Return ``True`` if the advertiser name resembles the brand without being an exact match."""
    adv = advertiser_name.lower().strip()
    brand = brand_name.lower().strip()
    all_names = [brand] + [a.lower().strip() for a in (aliases or [])]
    for name in all_names:
        if adv == name:
            return False
    for name in all_names:
        similarity = jellyfish.jaro_winkler_similarity(adv, name)
        if similarity >= 0.85 and similarity < 1.0:
            return True
    return False


def _extract_brand_tokens(brand_name: str, aliases: List[str]) -> List[str]:
    """Extract significant word-level tokens from a brand name and its aliases.

    ``"HDFC Bank"`` → ``["hdfc", "bank"]``
    ``"SBI"`` → ``["sbi"]``
    ``"Amazon India"`` → ``["amazon", "india"]``
    """
    tokens = set()
    for name in [brand_name] + list(aliases or []):
        for part in name.lower().split():
            part = part.strip(".,!?()[]{}")
            if part:
                tokens.add(part)
    return list(tokens)


def _is_relevant_to_brand(
    ad_text: str,
    advertiser_name: str,
    landing_domain: str,
    brand_name: str,
    aliases: List[str],
    official_domains: List[str],
    suspicious_keywords: List[str],
) -> bool:
    """Brand relevance gate — require at least one signal that this ad is plausibly related to the brand.

    Returns ``True`` if any of the following holds:

    * brand name or alias appears in ``ad_text``
    * advertiser name is similar to brand name/alias
    * landing domain resembles an official domain (lookalike)
    * landing domain contains a brand token
    * a suspicious keyword hits **and** a brand alias appears somewhere in
      ``ad_text``, ``advertiser_name``, or ``landing_domain``
    """
    text_lower = ad_text.lower().strip()
    adv_lower = advertiser_name.lower().strip()
    domain_lower = normalize_domain(landing_domain)
    all_brand_names = [brand_name.lower().strip()] + [a.lower().strip() for a in (aliases or [])]

    # 1. Brand name/alias in ad text
    for term in all_brand_names:
        if term and term in text_lower:
            return True

    # 2. Advertiser name similar to brand
    if advertiser_similar_to_brand(advertiser_name, brand_name, aliases or []):
        return True

    # 3. Landing domain resembles official domain
    if domain_lower and official_domains and is_lookalike_domain(domain_lower, official_domains):
        return True

    # 4. Landing domain contains a brand token at a word boundary
    #    (e.g. "hdfc" in "hdfc-kyc-help.com" or "hdfc.bank.com", but not
    #    "bank" inside "hdfcbank" which has no word boundary)
    tokens = _extract_brand_tokens(brand_name, aliases or [])
    if tokens and domain_lower:
        for token in tokens:
            if len(token) >= 3 and re.search(r'\b' + re.escape(token) + r'\b', domain_lower):
                return True

    # 5. Suspicious keyword hits AND brand alias in ad_text/advertiser/domain
    keywords_lower = [k.lower().strip() for k in (suspicious_keywords or [])]
    has_suspicious = any(kw and kw in text_lower for kw in keywords_lower)
    if has_suspicious:
        combined = text_lower + " " + adv_lower + " " + domain_lower
        for term in all_brand_names:
            if term and term in combined:
                return True

    return False


def score_ad_against_brand(
    ad_text: str,
    advertiser_name: str,
    landing_domain: str,
    approved_advertisers: List[str],
    official_domains: List[str],
    brand_name: str,
    aliases: List[str],
    suspicious_keywords: List[str],
) -> tuple:
    """Evaluate one ad against one brand and return ``(risk_score, signals, reasons)``.

    Parameters
    ----------
    ad_text, advertiser_name, landing_domain : str
        Fields from the normalised ad.
    approved_advertisers, official_domains, aliases, suspicious_keywords : list of str
        Brand configuration loaded from the YAML.
    brand_name : str
        Primary brand name.

    Returns
    -------
    tuple of (int, list[dict], list[str])
        ``(risk_score, signals, reasons)``.

    **signals** — machine-readable list of dicts, each with ``name``, ``weight``
    and ``matched_value`` keys.  Used for downstream analysis and explainability.

    **reasons** — human-readable list of sentences describing why the ad was flagged.
    """
    score = 0
    signals: list = []
    reasons: list = []

    ad_text_lower = ad_text.lower().strip()
    adv_lower = advertiser_name.lower().strip()
    domain_lower = normalize_domain(landing_domain)
    all_brand_names = [brand_name.lower().strip()] + [a.lower().strip() for a in (aliases or [])]

    approved_lower = [a.lower().strip() for a in (approved_advertisers or [])]
    official_lower = [normalize_domain(d) for d in (official_domains or [])]
    keywords_lower = [k.lower().strip() for k in (suspicious_keywords or [])]

    # ── Brand relevance gate ──────────────────────────────────────────────
    # Do not score ads that have no plausible relationship to this brand.
    # This prevents false positives where a genuine HDFC ad is flagged
    # against SBI or Amazon India purely because the advertiser or domain
    # is not in those brands' approved lists.
    if not _is_relevant_to_brand(
        ad_text=ad_text,
        advertiser_name=advertiser_name,
        landing_domain=landing_domain,
        brand_name=brand_name,
        aliases=aliases or [],
        official_domains=official_domains or [],
        suspicious_keywords=suspicious_keywords or [],
    ):
        return 0, [], []

    # ── 1. Brand name or alias appears in ad text ───────────────────────
    matched_brand_term: Optional[str] = None
    for term in all_brand_names:
        if term and term in ad_text_lower:
            matched_brand_term = term
            score += 20
            signals.append({"name": "brand_in_ad_text", "weight": 20, "matched_value": term})
            reasons.append(f"Brand alias '{term}' found in ad text")
            break

    # ── 2. Advertiser not in approved list ──────────────────────────────
    advertiser_unapproved = False
    if approved_lower and adv_lower not in approved_lower:
        advertiser_unapproved = True
        score += 25
        signals.append({"name": "unapproved_advertiser", "weight": 25, "matched_value": advertiser_name})
        reasons.append(f"Advertiser '{advertiser_name}' is not in approved list")

    # ── 3. Landing domain not official ──────────────────────────────────
    domain_unofficial = False
    if domain_lower and official_lower and not is_official_domain(domain_lower, official_lower):
        domain_unofficial = True
        score += 30
        signals.append({"name": "unofficial_domain", "weight": 30, "matched_value": landing_domain})
        reasons.append(f"Landing domain '{landing_domain}' is not official")

    # ── 4. Lookalike / typosquatted domain (only if not already official) ──
    if domain_lower and official_lower and domain_unofficial and is_lookalike_domain(domain_lower, official_lower):
        score += 35
        signals.append({"name": "lookalike_domain", "weight": 35, "matched_value": landing_domain})
        reasons.append(f"Landing domain '{landing_domain}' resembles official domain")

    # ── 5. Suspicious keyword hits ─────────────────────────────────────
    for kw in keywords_lower:
        if kw and kw in ad_text_lower:
            score += 10
            signals.append({"name": "suspicious_keyword", "weight": 10, "matched_value": kw})
            reasons.append(f"Suspicious keyword '{kw}' found in ad text")

    # ── 6. Advertiser name similar to brand but not exact ──────────────
    if advertiser_similar_to_brand(advertiser_name, brand_name, aliases or []):
        score += 20
        signals.append({"name": "advertiser_similar_to_brand", "weight": 20, "matched_value": advertiser_name})
        reasons.append(f"Advertiser name '{advertiser_name}' is similar to brand '{brand_name}'")

    return score, signals, reasons


def severity_from_score(risk_score: int) -> str:
    if risk_score >= 70:
        return "HIGH"
    if risk_score >= 40:
        return "MEDIUM"
    return "LOW"
