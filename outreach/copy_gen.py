"""
Generate personalized cold email openers using the Claude API.

Each opener is 1-2 sentences, hyper-specific to the business and its pain signal.
We use claude-haiku-4-5 for speed and cost efficiency at scale.
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
    """
    Return a 1-2 sentence personalised opening line for a cold email.

    The opener should:
    - Reference something specific about their business (pain signal)
    - Sound like it came from a human who actually looked at their site
    - NOT mention AI, software, or the offer (that comes later in the email)
    """
    location_str = f" in {city}" if city else ""
    pain_str = (
        ", ".join(pain_signals)
        if pain_signals
        else "likely handling all customer contact manually"
    )
    website_str = f" (website: {website})" if website else ""

    prompt = (
        f"Write a 1-2 sentence cold email opening line for a small business owner.\n\n"
        f"Business: {company_name}{location_str} — a {vertical_label}{website_str}\n"
        f"Pain signals observed: {pain_str}\n"
        f"Recipient first name: {first_name}\n\n"
        f"Rules:\n"
        f"- Sound like a human who spent 2 minutes on their website or Google listing\n"
        f"- Reference the specific pain signal naturally (don't say 'I noticed you have no booking system')\n"
        f"- Do NOT mention AI, software, automation, or any offer\n"
        f"- Do NOT use hollow phrases like 'I came across your business' or 'I hope this finds you well'\n"
        f"- Keep it under 40 words\n"
        f"- Output only the opener text, no quotes, no extra commentary"
    )

    resp = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def generate_openers_batch(leads: list[dict], vertical_label: str) -> list[dict]:
    """
    Add an 'opener' field to each lead dict. Processes sequentially to avoid
    rate-limit bursts; fast enough for batches up to ~200 leads.
    """
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
