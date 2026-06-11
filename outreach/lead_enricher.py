"""
Lead enrichment: fetch the business website and detect web + workflow pain signals.

Two pain buckets:
  WEB   — bad/missing site, no HTTPS, not mobile-ready, old copyright
  WORKFLOW — no lead capture, no booking, no chat/contact automation

The stronger bucket determines which offer leads the email.
"""

import re
import requests

# ── Web quality signals ────────────────────────────────────────────────────────

BOOKING_KEYWORDS = [
    "book now", "book an appointment", "schedule online", "schedule now",
    "request an appointment", "online scheduling", "calendly", "acuityscheduling",
    "housecall pro", "servicetitan", "jobber", "book a service", "online booking",
    "schedule service", "schedule a visit", "request service",
    "request a quote online", "get a quote online",
]

CONTACT_FORM_KEYWORDS = [
    "contact us", "send us a message", "get in touch", "contact form",
    "fill out the form", "submit your inquiry",
]

CHAT_KEYWORDS = [
    "live chat", "chat with us", "chat now", "intercom", "drift",
    "tidio", "crisp", "zendesk chat",
]

CRM_KEYWORDS = [
    "hubspot", "salesforce", "pipedrive", "zoho crm", "keap", "infusionsoft",
    "monday.com", "crm",
]

EMAIL_MARKETING_KEYWORDS = [
    "mailchimp", "klaviyo", "constant contact", "subscribe to our newsletter",
    "sign up for updates", "email list",
]

MOBILE_META = "viewport"
HTTPS_PREFIX = "https://"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SiteChecker/1.0)"
}


def _fetch_raw(url: str, timeout: int = 8) -> tuple[str, str]:
    """Return (raw_html_lower, final_url). Empty strings on failure."""
    if not url:
        return "", ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text.lower(), resp.url
    except Exception:
        return "", ""


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text)


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text for kw in keywords)


def _extract_copyright_year(html: str) -> int | None:
    m = re.search(r"©\s*(20\d{2})", html)
    return int(m.group(1)) if m else None


def enrich_lead(lead: dict) -> dict:
    """
    Detect web and workflow pain signals. Adds fields:

      website_live         bool
      has_https            bool
      has_mobile_meta      bool
      copyright_year       int | None
      has_booking          bool
      has_contact_form     bool
      has_chat             bool
      has_crm_hints        bool
      has_email_marketing  bool
      web_pain_score       int  (0-100)
      workflow_pain_score  int  (0-100)
      primary_pain         str  ("web" | "workflow" | "both")
      pain_signals         list[str]
    """
    html, final_url = _fetch_raw(lead.get("website", ""))
    text = _strip_tags(html)
    website_live = bool(html)

    # Web quality
    has_https = final_url.startswith(HTTPS_PREFIX) if final_url else False
    has_mobile_meta = MOBILE_META in html
    copyright_year = _extract_copyright_year(html)
    site_is_old = bool(copyright_year and copyright_year < 2021)

    # Workflow / automation
    has_booking = _has_keyword(text, BOOKING_KEYWORDS)
    has_contact_form = _has_keyword(text, CONTACT_FORM_KEYWORDS)
    has_chat = _has_keyword(text, CHAT_KEYWORDS)
    has_crm = _has_keyword(text, CRM_KEYWORDS)
    has_email_mkt = _has_keyword(text, EMAIL_MARKETING_KEYWORDS)

    lead.update({
        "website_live": website_live,
        "has_https": has_https,
        "has_mobile_meta": has_mobile_meta,
        "copyright_year": copyright_year,
        "site_is_old": site_is_old,
        "has_booking": has_booking,
        "has_contact_form": has_contact_form,
        "has_chat": has_chat,
        "has_crm_hints": has_crm,
        "has_email_marketing": has_email_mkt,
    })

    # ── Score each bucket ──────────────────────────────────────────────────────
    web_score = 0
    if not website_live:
        web_score += 60
    else:
        if not has_https:
            web_score += 25
        if not has_mobile_meta:
            web_score += 25
        if site_is_old:
            web_score += 15
        if not has_contact_form:
            web_score += 10  # site exists but no way to reach them online
    web_score = min(web_score, 100)

    workflow_score = 0
    if not has_booking:
        workflow_score += 35
    if not has_contact_form and not has_chat:
        workflow_score += 25
    if not has_crm:
        workflow_score += 20
    if not has_email_mkt:
        workflow_score += 20
    workflow_score = min(workflow_score, 100)

    lead["web_pain_score"] = web_score
    lead["workflow_pain_score"] = workflow_score

    # Decide primary pitch angle
    if web_score >= 40 and workflow_score >= 40:
        primary = "both"
    elif web_score >= workflow_score:
        primary = "web"
    else:
        primary = "workflow"
    lead["primary_pain"] = primary

    # Human-readable signals list
    signals = []
    if not website_live:
        signals.append("no working website found")
    else:
        if not has_https:
            signals.append("website not on HTTPS — shows 'Not Secure' in browser")
        if not has_mobile_meta:
            signals.append("website doesn't appear to be mobile-optimised")
        if site_is_old:
            signals.append(f"website copyright last updated {copyright_year}")
    if not has_booking:
        signals.append("no online booking or self-serve scheduling")
    if not has_contact_form and not has_chat:
        signals.append("no lead capture form or chat on site")
    if not has_crm:
        signals.append("no CRM or follow-up automation detected")

    lead["pain_signals"] = signals
    return lead


def score_lead(lead: dict) -> int:
    """Overall quality score — leads below 30 are skipped."""
    return max(lead.get("web_pain_score", 0), lead.get("workflow_pain_score", 0))
