"""
Generate personalised cold email openers using the Claude API.

One opener per lead — 1-2 sentences, specific to their visible pain signal.
Uses claude-haiku-4-5 for speed and cost at scale.
"""

import os
from typing import Optional
import anthropic

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def generate_opener(
    first_name: str,
    company_name: str,
    vertical_label: str,
    pain_signals: list[str],
    primary_pain: str,
    city: str = "",
    website: str = "",
) -> str:
    """
    Return a 1-2 sentence personalised opening line for a cold email.

    primary_pain: "web" | "workflow" | "both"
    """
    location_str = f" in {city}" if city else ""
    pain_str = ", ".join(pain_signals) if pain_signals else "likely handling most admin manually"
    website_str = f" — site: {website}" if website else " — no website found"

    if primary_pain == "web":
        angle = (
            "Focus on their website issues. Sound like someone who briefly looked at "
            "their site (or noticed they don't have one). Don't mention the word 'website' "
            "directly — reference the customer experience instead."
        )
    elif primary_pain == "workflow":
        angle = (
            "Focus on the operational/admin side — they're probably handling lead follow-up, "
            "scheduling, or customer communication manually. Sound like someone who's seen "
            "this pattern with similar businesses."
        )
    else:
        angle = (
            "They have both a weak web presence and manual workflows. Lead with whichever "
            "would be most immediately painful for a business owner."
        )

    prompt = (
        f"Write a 1-2 sentence cold email opening line.\n\n"
        f"Business: {company_name}{location_str} — {vertical_label}{website_str}\n"
        f"Observed pain signals: {pain_str}\n"
        f"Angle: {angle}\n\n"
        f"Rules:\n"
        f"- Sound like a human who spent 2 minutes on their Google listing or website\n"
        f"- Reference the specific pain naturally — don't quote the signals verbatim\n"
        f"- Do NOT mention your company, product, price, or any offer\n"
        f"- Do NOT use filler phrases like 'I came across your business' or 'I hope this finds you well'\n"
        f"- Under 35 words\n"
        f"- Output only the opener, no quotes, no extra text"
    )

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def generate_openers_batch(leads: list[dict], vertical_label: str) -> list[dict]:
    """Add an 'opener' field to each lead dict."""
    for lead in leads:
        lead["opener"] = generate_opener(
            first_name=lead.get("first_name", "there"),
            company_name=lead.get("company_name", "your business"),
            vertical_label=vertical_label,
            pain_signals=lead.get("pain_signals", []),
            primary_pain=lead.get("primary_pain", "web"),
            city=lead.get("city", ""),
            website=lead.get("website", ""),
        )
    return leads
