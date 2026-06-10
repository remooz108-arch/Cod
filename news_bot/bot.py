#!/usr/bin/env python3
"""
Trump + Iran + Israel Headline Prediction Bot
----------------------------------------------
Polls major news RSS feeds every POLL_INTERVAL seconds.
If a single headline contains "Trump", "Iran", AND "Israel",
the bot searches Polymarket for related prediction markets and
places YES bets on them.

Usage:
    python bot.py              # dry-run loop
    python bot.py --once       # single scan, then exit
    python bot.py --live       # place real bets
    python bot.py --scan-only  # print headlines + markets, never bet
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from headlines import fetch_headlines, find_triggered, Headline
from market_finder import find_markets, display as display_markets
from bettor import init_client, place_yes_bet


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_seen() -> set[str]:
    p = Path(config.SEEN_FILE)
    return set(json.loads(p.read_text())) if p.exists() else set()


def save_seen(seen: set[str]) -> None:
    Path(config.SEEN_FILE).write_text(json.dumps(list(seen)))


def log_signal(headline: Headline, markets_found: int, bets_placed: int) -> None:
    with open(config.SIGNALS_LOG, "a") as f:
        f.write(
            f"\n[{ts()}] SIGNAL\n"
            f"  Headline : {headline.title}\n"
            f"  Source   : {headline.source}\n"
            f"  URL      : {headline.url}\n"
            f"  Markets  : {markets_found} found\n"
            f"  Bets     : {bets_placed} placed\n"
        )


def handle_signal(headline: Headline, client, live: bool, scan_only: bool) -> None:
    print(f"\n{'!'*60}")
    print(f"  SIGNAL FIRED")
    print(f"  Source   : {headline.source}")
    print(f"  Headline : {headline.title}")
    print(f"  URL      : {headline.url}")
    print(f"{'!'*60}\n")

    print("  Searching Polymarket for related prediction markets...")
    markets = find_markets()
    print(f"  Found {len(markets)} market(s):\n")
    print(display_markets(markets))
    print()

    if not markets:
        log_signal(headline, 0, 0)
        return

    if scan_only:
        print("  [scan-only] Skipping bets.")
        log_signal(headline, len(markets), 0)
        return

    bets_placed = 0
    for market in markets:
        if market.yes_price is None:
            print(f"  [{market.question[:50]}] — no price data, skipping")
            continue

        # Only bet YES if market isn't already near certainty
        if market.yes_price > 0.90:
            print(f"  [{market.question[:50]}] — YES already at {market.yes_price:.3f}, skipping")
            continue

        print(f"  Bet YES on: {market.question[:60]}")
        print(f"    Token  : {market.yes_token_id[:20]}...")
        print(f"    Price  : {market.yes_price:.3f}  |  Amount: ${config.BET_AMOUNT_USDC:.2f} USDC")

        if not live or client is None:
            print(f"    [dry-run] Would place FOK YES order.")
        else:
            try:
                resp = place_yes_bet(client, market.yes_token_id, config.BET_AMOUNT_USDC)
                status = resp.get("status", "unknown")
                order_id = resp.get("orderID") or resp.get("id", "n/a")
                print(f"    Order placed: status={status}  id={order_id}")
                bets_placed += 1
            except Exception as exc:
                print(f"    ERROR placing bet: {exc}")

    log_signal(headline, len(markets), bets_placed)
    print()


def run(live: bool = False, once: bool = False, scan_only: bool = False) -> None:
    mode = "LIVE" if live else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Trump + Iran + Israel Headline Prediction Bot  [{mode}]")
    print(f"{'='*60}")
    print(f"  Trigger words : {' + '.join(config.TRIGGER_WORDS)}")
    print(f"  Matching on   : headline titles only")
    print(f"  RSS sources   : {len(config.RSS_FEEDS)}")
    print(f"  Bet amount    : ${config.BET_AMOUNT_USDC:.2f} USDC per market")
    print(f"  Poll interval : {config.POLL_INTERVAL}s")
    print(f"  Signals log   : {config.SIGNALS_LOG}")
    print(f"{'='*60}\n")

    client = None
    if live and not scan_only:
        if not config.POLY_PRIVATE_KEY or config.POLY_PRIVATE_KEY.startswith("0x_your"):
            print("  ERROR: POLY_PRIVATE_KEY not set. Cannot place live bets.")
            sys.exit(1)
        print("  Authenticating with Polymarket...")
        client = init_client()
        if client is None:
            print("  ERROR: Authentication failed.")
            sys.exit(1)
        print("  Authenticated.\n")

    seen = load_seen()
    print(f"  Loaded {len(seen)} previously seen headline IDs.\n")

    def scan() -> None:
        print(f"[{ts()}] Scanning {len(config.RSS_FEEDS)} RSS feeds for headlines...")
        all_headlines = fetch_headlines()
        new_headlines = [h for h in all_headlines if h.id not in seen]
        print(f"  {len(all_headlines)} total, {len(new_headlines)} new")

        triggered = find_triggered(new_headlines)

        for h in new_headlines:
            seen.add(h.id)
        save_seen(seen)

        if not triggered:
            print(f"  No matching headlines this scan.")
            return

        for headline in triggered:
            handle_signal(headline, client, live=live, scan_only=scan_only)

    if once:
        scan()
        return

    print(f"  Running continuously. Press Ctrl+C to stop.\n")
    while True:
        try:
            scan()
            print(f"  Next scan in {config.POLL_INTERVAL}s...\n")
            time.sleep(config.POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n\n  Stopped.")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trump+Iran+Israel headline prediction bot")
    parser.add_argument("--live",      action="store_true", help="Place real bets on Polymarket")
    parser.add_argument("--once",      action="store_true", help="Single scan then exit")
    parser.add_argument("--scan-only", action="store_true", dest="scan_only", help="Find markets but never bet")
    args = parser.parse_args()
    run(live=args.live, once=args.once, scan_only=args.scan_only)
