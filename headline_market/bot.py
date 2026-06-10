#!/usr/bin/env python3
"""
Headline Prediction Market Bot
--------------------------------
Creates and runs a binary prediction market with one question:

  "Will at least 1 news headline contain Trump + Iran + Israel?"

The bot monitors 6 RSS feeds. The market resolves:
  YES  — the moment a matching headline appears
  NO   — if the market end date passes with no match

When a headline triggers the signal, the bot also searches Polymarket
for related prediction markets and places YES bets on them (optional).

Usage:
    python bot.py            # create market, monitor, bet in dry-run
    python bot.py --live     # same but place real Polymarket orders
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
import polymarket as pm


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


def run_scan(market: Market, poly_client) -> bool:
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
            if not any(x.headline == h.title for x in market.all_hits):
                market.all_hits.append(hit)
                log(f"MATCH — [{h.source}] {h.title}")

        # Resolve YES on the first match, then fire bets
        if market.resolution is None:
            resolve_yes(market, market.all_hits[-1])
            _fire_bets(poly_client)
            return True

    market.save()
    return False


def _fire_bets(poly_client) -> None:
    """Search Polymarket for related markets and place YES bets."""
    mode = "LIVE" if config.LIVE_BETTING else "DRY-RUN"
    log(f"Searching Polymarket for escalation markets [{mode}]...")

    targets = pm.find_targets()
    log(f"  Found {len(targets)} eligible market(s)")

    results = pm.place_bets(poly_client, targets)
    output = pm.display_results(targets, results)
    print(output)

    placed = sum(1 for r in results if r.status == "placed")
    dry    = sum(1 for r in results if r.status == "dry_run")
    failed = sum(1 for r in results if r.status == "failed")
    log(f"  Bets: {placed} placed, {dry} dry-run, {failed} failed")

    with open(config.LOG_FILE, "a") as f:
        f.write(output + "\n")


def run(reset: bool = False, live: bool = False) -> None:
    if live:
        config.LIVE_BETTING = True

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

    # ── Polymarket client ──────────────────────────────────────────────
    poly_client = None
    if config.LIVE_BETTING:
        log("Authenticating with Polymarket...")
        poly_client = pm.init_client()
        if poly_client is None:
            print("  ERROR: Could not authenticate. Check POLY_PRIVATE_KEY in .env.")
            sys.exit(1)
        log("Polymarket authenticated.")
    else:
        log("Polymarket betting: DRY-RUN (set LIVE_BETTING=true or use --live)")

    bet_mode = "LIVE" if config.LIVE_BETTING else "DRY-RUN"
    words = " + ".join(w.title() for w in config.TRIGGER_WORDS)
    print(f"Monitoring  : {len(config.RSS_FEEDS)} RSS feeds every {config.POLL_INTERVAL}s")
    print(f"Trigger     : headline title must contain ALL of: {words}")
    print(f"On signal   : search Polymarket, bet YES [{bet_mode}] ${config.BET_AMOUNT_USDC:.2f}/market")
    print(f"Resolves    : YES on first match | NO at {market.ends_at[:19]}")
    print("Press Ctrl+C to stop (market state is saved).\n")

    # ── Main loop ──────────────────────────────────────────────────────
    while market.is_open:
        print(f"[{ts()}] Scanning...")

        if check_expiry(market):
            break

        resolved = run_scan(market, poly_client)

        print(f"  Headlines: {market.headlines_checked} checked | "
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
    parser.add_argument("--live",   action="store_true", help="Place real Polymarket bets on signal")
    args = parser.parse_args()

    if args.status:
        print_status()
    else:
        try:
            run(reset=args.reset, live=args.live)
        except KeyboardInterrupt:
            print("\nStopped.")
