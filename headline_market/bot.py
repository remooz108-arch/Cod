#!/usr/bin/env python3
"""
Headline Prediction Market Bot
--------------------------------
Creates and runs a binary prediction market with one question:

  "Will at least 1 news headline contain Trump + Iran + Israel?"

The bot monitors 6 RSS feeds. The market resolves:
  YES  — the moment a matching headline appears
  NO   — if the market end date passes with no match

Usage:
    python bot.py            # create market and start monitoring
    python bot.py --reset    # delete existing market and start fresh
    python bot.py --status   # print current market state and exit
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from market import Market, Hit, create_market, status_block
from scanner import fetch_new_headlines


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line)
    with open(config.LOG_FILE, "a") as f:
        f.write(line + "\n")


def resolve_yes(market: Market, hit: Hit) -> None:
    now = datetime.now(timezone.utc).isoformat()
    market.resolution   = "YES"
    market.resolved_at  = now
    market.resolving_hit = hit
    market.save()
    log(f"RESOLVED YES — headline: {hit.headline}")
    log(f"  Source : {hit.source}")
    log(f"  URL    : {hit.url}")


def resolve_no(market: Market) -> None:
    now = datetime.now(timezone.utc).isoformat()
    market.resolution  = "NO"
    market.resolved_at = now
    market.save()
    log("RESOLVED NO — end date passed with no matching headline.")


def check_expiry(market: Market) -> bool:
    """Return True and resolve NO if the market has expired."""
    end = datetime.fromisoformat(market.ends_at)
    now = datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if now >= end:
        resolve_no(market)
        return True
    return False


def run_scan(market: Market) -> bool:
    """
    Perform one scan.
    Returns True if the market just resolved YES (caller should stop loop).
    """
    seen = set(market.seen_ids)
    new_headlines, triggered = fetch_new_headlines(seen)

    # Update seen IDs
    market.seen_ids = list(seen | {h.id for h in new_headlines})
    market.headlines_checked += len(new_headlines)
    market.scans_completed   += 1

    if triggered:
        for h in triggered:
            hit = Hit(
                headline=h.title,
                source=h.source,
                url=h.url,
                found_at=datetime.now(timezone.utc).isoformat(),
            )
            # Record every match regardless
            if not any(x.headline == h.title for x in market.all_hits):
                market.all_hits.append(hit)
                log(f"MATCH — [{h.source}] {h.title}")

        # Resolve YES on the first match
        if market.resolution is None:
            resolve_yes(market, market.all_hits[-1])
            return True

    market.save()
    return False


def run(reset: bool = False) -> None:
    # ── Setup ─────────────────────────────────────────────────────────
    if reset and Path(config.MARKET_FILE).exists():
        Path(config.MARKET_FILE).unlink()
        log("Existing market deleted.")

    if Market.exists():
        market = Market.load()
        log("Loaded existing market.")
    else:
        market = create_market()
        log(f"Market created. Ends: {market.ends_at[:19]}")

    print()
    print(status_block(market))
    print()

    if not market.is_open:
        print("Market is already resolved. Use --reset to start a new one.")
        return

    words = " + ".join(w.title() for w in config.TRIGGER_WORDS)
    print(f"Monitoring {len(config.RSS_FEEDS)} RSS feeds every {config.POLL_INTERVAL}s")
    print(f"Trigger   : headline title must contain ALL of: {words}")
    print(f"Resolves  : YES on first match | NO at {market.ends_at[:19]}")
    print("Press Ctrl+C to stop (market state is saved).\n")

    # ── Main loop ──────────────────────────────────────────────────────
    while market.is_open:
        print(f"[{ts()}] Scanning...")

        if check_expiry(market):
            break

        resolved = run_scan(market)

        print(f"  Headlines scanned this run: {market.headlines_checked} total | "
              f"Matches: {len(market.all_hits)} | "
              f"Time left: {market.time_remaining}")

        if resolved:
            break

        try:
            time.sleep(config.POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopped. Market state saved.")
            break

    print()
    print(status_block(market))


def print_status() -> None:
    if not Market.exists():
        print("No market file found. Run `python bot.py` to create one.")
        return
    print(status_block(Market.load()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Headline prediction market")
    parser.add_argument("--reset",  action="store_true", help="Delete existing market and start fresh")
    parser.add_argument("--status", action="store_true", help="Print current market state and exit")
    args = parser.parse_args()

    if args.status:
        print_status()
    else:
        try:
            run(reset=args.reset)
        except KeyboardInterrupt:
            print("\nStopped.")
