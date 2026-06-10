"""
Binary prediction market state.

Question : Will at least 1 news headline contain <trigger words>?
Resolves : YES as soon as a matching headline is found
           NO  if the end date passes with no match
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import config


@dataclass
class Hit:
    headline: str
    source: str
    url: str
    found_at: str  # ISO timestamp


@dataclass
class Market:
    question: str
    trigger_words: list[str]
    created_at: str
    ends_at: str
    resolution: Optional[str]       # None | "YES" | "NO"
    resolved_at: Optional[str]
    resolving_hit: Optional[Hit]    # the headline that triggered YES
    all_hits: list[Hit]             # every matching headline seen
    scans_completed: int
    headlines_checked: int
    seen_ids: list[str]             # dedup set persisted as list

    @property
    def is_open(self) -> bool:
        return self.resolution is None

    @property
    def time_remaining(self) -> str:
        if not self.is_open:
            return "closed"
        end = datetime.fromisoformat(self.ends_at)
        now = datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = end - now
        if delta.total_seconds() <= 0:
            return "expired"
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        mins = rem // 60
        return f"{days}d {hours:02d}h {mins:02d}m"

    def save(self) -> None:
        Path(config.MARKET_FILE).write_text(
            json.dumps(asdict(self), indent=2, default=str)
        )

    @classmethod
    def load(cls) -> "Market":
        data = json.loads(Path(config.MARKET_FILE).read_text())
        hits = [Hit(**h) for h in data.pop("all_hits", [])]
        rh   = Hit(**data.pop("resolving_hit")) if data.get("resolving_hit") else None
        data.pop("resolving_hit", None)
        return cls(**data, resolving_hit=rh, all_hits=hits)

    @classmethod
    def exists(cls) -> bool:
        return Path(config.MARKET_FILE).exists()


def create_market() -> Market:
    now     = datetime.now(timezone.utc)
    ends_at = now + timedelta(days=config.MARKET_DURATION_DAYS)
    words   = config.TRIGGER_WORDS
    word_str = " + ".join(w.title() for w in words)

    m = Market(
        question=(
            f'Will at least 1 news headline contain all of: '
            f'{word_str}?'
        ),
        trigger_words=words,
        created_at=now.isoformat(),
        ends_at=ends_at.isoformat(),
        resolution=None,
        resolved_at=None,
        resolving_hit=None,
        all_hits=[],
        scans_completed=0,
        headlines_checked=0,
        seen_ids=[],
    )
    m.save()
    return m


def status_block(m: Market) -> str:
    res = m.resolution or "OPEN"
    res_color = {"YES": "✅ YES", "NO": "❌ NO", "OPEN": "⏳ OPEN"}.get(res, res)

    lines = [
        "╔══════════════════════════════════════════════════════╗",
        f"  {m.question}",
        "╠══════════════════════════════════════════════════════╣",
        f"  Resolution    : {res_color}",
        f"  Time remaining: {m.time_remaining}",
        f"  Created       : {m.created_at[:19]}",
        f"  Ends          : {m.ends_at[:19]}",
        f"  Scans done    : {m.scans_completed}",
        f"  Headlines seen: {m.headlines_checked}",
        f"  Matches found : {len(m.all_hits)}",
    ]

    if m.resolving_hit:
        lines += [
            "╠══════════════════════════════════════════════════╣",
            f"  RESOLVED BY:",
            f"  [{m.resolving_hit.source}] {m.resolving_hit.headline}",
            f"  {m.resolving_hit.url}",
            f"  at {m.resolving_hit.found_at[:19]}",
        ]
    elif m.all_hits:
        lines += [
            "╠══════════════════════════════════════════════════╣",
            f"  MATCHES SO FAR ({len(m.all_hits)}):",
        ]
        for h in m.all_hits[-5:]:
            lines.append(f"  [{h.source}] {h.headline[:65]}")

    lines.append("╚══════════════════════════════════════════════════════╝")
    return "\n".join(lines)
