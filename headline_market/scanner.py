"""Scan RSS feeds and check headline titles for trigger words."""

from __future__ import annotations

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


def _make_id(title: str, url: str) -> str:
    return hashlib.sha1((url or title).encode()).hexdigest()[:16]


def fetch_new_headlines(seen_ids: set[str]) -> tuple[list[Headline], list[Headline]]:
    """
    Returns (all_new, triggered).
    all_new  = headlines not in seen_ids
    triggered = subset where ALL trigger words appear in the title
    """
    all_new: list[Headline] = []
    new_ids_seen: set[str] = set()

    for source, url in config.RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            print(f"  [warn] {source}: {exc}")
            continue
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            hid = _make_id(title, entry.get("link", ""))
            if hid in seen_ids or hid in new_ids_seen:
                continue
            new_ids_seen.add(hid)
            all_new.append(Headline(
                id=hid,
                title=title,
                url=entry.get("link", ""),
                source=source,
                published=entry.get("published") or entry.get("updated", ""),
            ))

    triggered = [h for h in all_new if _matches(h.title)]
    return all_new, triggered


def _matches(title: str) -> bool:
    text = title.lower()
    return all(
        bool(re.search(r'\b' + re.escape(w) + r'\b', text))
        for w in config.TRIGGER_WORDS
    )
