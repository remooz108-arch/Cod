"""
Generate personalised cold email openers using Claude.

1-2 sentences, specific to the business's visible website situation.
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
    city: str = "",
    website: str = "",
) -> str:
    """1-2 sentence opener referencing their specific website situation."""
    location = f" in {city}" if city else ""
    pain = ", ".join(pain_signals) if pain_signals else "likely has an outdated or hard-to-find website"
    site_note = f"their current site is {website}" if website else "no website found"

    prompt = (
        f"Write a 1-2 sentence cold email opening line for a small business owner.\n\n"
        f"Business: {company_name}{location} — {vertical_label} ({site_note})\n"
        f"Website issues observed: {pain}\n\n"
        f"Rules:\n"
        f"- Sound like a human who spent 2 minutes Googling their business\n"
        f"- Reference their specific situation naturally — don't quote the issues word for word\n"
        f"- Do NOT mention your company, product, or price\n"
        f"- No hollow openers like 'I came across your business' or 'I hope this finds you well'\n"
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
    for lead in leads:
        lead["opener"] = generate_opener(
            first_name=lead.get("first_name", "there"),
            company_name=lead.get("company_name", "your business"),
            vertical_label=vertical_label,
            pain_signals=lead.get("pain_signals", []),
            city=lead.get("city", ""),
            website=lead.get("website", ""),
        )
    return leads
