"""
Scan RSS feeds for headlines (titles only) that contain
ALL of the configured trigger words in a single headline.
"""

import hashlib
import re
from dataclasses import dataclass

import feedparser
import config


@dataclass
class Headline:
    id: str
    title: str
    url: str
    source: str
    published: str


def _make_id(url: str, title: str) -> str:
    raw = (url or title).encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def fetch_headlines() -> list[Headline]:
    headlines: list[Headline] = []
    seen_ids: set[str] = set()

    for source_name, feed_url in config.RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as exc:
            print(f"  [warn] RSS fetch failed ({source_name}): {exc}")
            continue

        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            url = entry.get("link", "")
            hid = _make_id(url, title)
            if hid in seen_ids:
                continue
            seen_ids.add(hid)
            headlines.append(Headline(
                id=hid,
                title=title,
                url=url,
                source=source_name,
                published=entry.get("published") or entry.get("updated", ""),
            ))

    return headlines


def matches_trigger(headline: Headline) -> bool:
    """Return True if ALL trigger words appear in the headline title."""
    text = headline.title.lower()
    return all(
        bool(re.search(r'\b' + re.escape(w) + r'\b', text))
        for w in config.TRIGGER_WORDS
    )


def find_triggered(headlines: list[Headline]) -> list[Headline]:
    return [h for h in headlines if matches_trigger(h)]
