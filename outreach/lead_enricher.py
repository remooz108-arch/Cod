"""
Lead enrichment: fetch the business website and detect pain signals.

Scoring is intentionally lightweight — one HTTP request per lead, no paid APIs.
"""

import re
import requests
from urllib.parse import urlparse

BOOKING_KEYWORDS = [
    "book now", "book an appointment", "schedule online", "schedule now",
    "request an appointment", "online scheduling", "calendly", "acuityscheduling",
    "housecall pro", "servicetitan", "jobber", "book a service", "online booking",
    "schedule service", "schedule a visit", "request service", "request a quote online",
    "get a quote online",
]

REVIEW_KEYWORDS = [
    "leave a review", "review us", "rate us", "google review", "yelp",
    "write a review", "share your experience",
]

APPOINTMENT_REMINDER_KEYWORDS = [
    "appointment reminder", "we'll remind you", "text reminder", "sms reminder",
    "email reminder", "automated reminder",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; OutreachBot/1.0; +https://example.com)"
    )
}


def _fetch_page_text(url: str, timeout: int = 8) -> str:
    """Return lowercased visible text from URL, empty string on any error."""
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        # Strip tags — crude but fast; avoids BeautifulSoup dependency
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        return text.lower()
    except Exception:
        return ""


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text for kw in keywords)


def enrich_lead(lead: dict) -> dict:
    """
    Add pain-signal fields to lead dict in-place (also returns it).

    Added keys:
      has_online_booking   bool
      has_review_cta       bool
      has_reminder_system  bool  (dental-specific)
      pain_signals         list[str]  — human-readable list
      website_live         bool
    """
    text = _fetch_page_text(lead.get("website", ""))

    has_booking = _has_keyword(text, BOOKING_KEYWORDS)
    has_reviews = _has_keyword(text, REVIEW_KEYWORDS)
    has_reminders = _has_keyword(text, APPOINTMENT_REMINDER_KEYWORDS)
    website_live = bool(text)

    lead["has_online_booking"] = has_booking
    lead["has_review_cta"] = has_reviews
    lead["has_reminder_system"] = has_reminders
    lead["website_live"] = website_live

    signals = []
    if not website_live:
        signals.append("no working website found")
    elif not has_booking:
        signals.append("no online booking or self-serve scheduling on website")
    if not has_reviews:
        signals.append("no visible review-collection prompt on site")
    if not has_reminders:
        signals.append("no automated reminder system detected")

    lead["pain_signals"] = signals
    return lead


def score_lead(lead: dict) -> int:
    """
    Simple 0-100 score: higher = more pain = better outreach candidate.
    """
    score = 0
    if not lead.get("has_online_booking"):
        score += 40
    if not lead.get("has_review_cta"):
        score += 20
    if not lead.get("has_reminder_system"):
        score += 20
    if not lead.get("website_live"):
        score += 10   # no website is pain, but also harder to personalize
    if lead.get("email"):
        score += 10
    return score
