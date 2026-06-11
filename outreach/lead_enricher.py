"""
Lead enrichment: detect website quality pain signals.

Checks (single HTTP request per lead, no paid APIs):
  - Site exists and loads
  - HTTPS
  - Mobile-ready (viewport meta)
  - Copyright year (staleness)
  - Contact form / any way to reach them online
"""

import re
import requests

CONTACT_KEYWORDS = [
    "contact us", "get in touch", "send us a message", "contact form",
    "request a quote", "get a quote", "free estimate", "book now",
    "schedule", "call us", "email us",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SiteChecker/1.0)"}


def _fetch(url: str, timeout: int = 8) -> tuple[str, str]:
    """Return (raw_html_lower, final_url). Empty strings on any error."""
    if not url:
        return "", ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.text.lower(), r.url
    except Exception:
        return "", ""


def enrich_lead(lead: dict) -> dict:
    """
    Add website quality fields to lead dict in-place.

    Added keys:
      website_live    bool
      has_https       bool
      has_mobile_meta bool
      copyright_year  int | None
      has_contact     bool
      pain_signals    list[str]
      web_score       int (0-100, higher = more pain = better prospect)
    """
    html, final_url = _fetch(lead.get("website", ""))
    live = bool(html)

    has_https = final_url.startswith("https://") if final_url else False
    has_mobile = "viewport" in html
    has_contact = any(kw in html for kw in CONTACT_KEYWORDS)

    year_match = re.search(r"©\s*(20\d{2})", html)
    copyright_year = int(year_match.group(1)) if year_match else None
    site_is_old = bool(copyright_year and copyright_year < 2021)

    lead.update({
        "website_live": live,
        "has_https": has_https,
        "has_mobile_meta": has_mobile,
        "copyright_year": copyright_year,
        "has_contact": has_contact,
    })

    signals = []
    if not live:
        signals.append("no working website found")
    else:
        if not has_https:
            signals.append("site not on HTTPS — shows 'Not Secure' in Chrome")
        if not has_mobile:
            signals.append("site doesn't appear mobile-optimised")
        if site_is_old:
            signals.append(f"site copyright still showing {copyright_year}")
        if not has_contact:
            signals.append("no visible way for customers to get in touch online")

    lead["pain_signals"] = signals

    # Score
    score = 0
    if not live:
        score = 80
    else:
        if not has_https:
            score += 30
        if not has_mobile:
            score += 30
        if site_is_old:
            score += 20
        if not has_contact:
            score += 20
    lead["web_score"] = min(score, 100)

    return lead


def score_lead(lead: dict) -> int:
    return lead.get("web_score", 0)
