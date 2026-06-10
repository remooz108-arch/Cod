#!/usr/bin/env python3
"""
Polymarket Batumi Weather Bot
------------------------------
Reads weather forecast for Batumi, Georgia, finds rain-related Polymarket
prediction markets, and places bets when the weather-implied probability
differs from the market price by more than MIN_EDGE.

Usage:
    python bot.py [--live]    # --live overrides LIVE_TRADING env var
"""

import argparse
import sys
import config

from weather import fetch_weather, summarise as weather_summary
from market_finder import find_rain_markets, summarise_markets
from strategy import decide, summarise_decision


def run(live_override: bool = False):
    if live_override:
        config.LIVE_TRADING = True

    mode = "LIVE" if config.LIVE_TRADING else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Polymarket Batumi Weather Bot  [{mode}]")
    print(f"{'='*60}\n")

    # ── 1. Weather ──────────────────────────────────────────────────
    print("[ Step 1 ] Fetching weather for Batumi, Georgia...")
    if not config.WEATHER_API_KEY:
        print("  ERROR: WEATHER_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    try:
        ws = fetch_weather()
    except Exception as exc:
        print(f"  ERROR fetching weather: {exc}")
        sys.exit(1)

    print(weather_summary(ws))
    print()

    # ── 2. Markets ──────────────────────────────────────────────────
    print("[ Step 2 ] Searching Polymarket for Batumi rain markets...")
    try:
        markets = find_rain_markets()
    except Exception as exc:
        print(f"  ERROR searching markets: {exc}")
        sys.exit(1)

    print(summarise_markets(markets))

    if not markets:
        print("\nNothing to bet on. Check back later or try different search terms.")
        sys.exit(0)

    # ── 3. Strategy ─────────────────────────────────────────────────
    print("[ Step 3 ] Evaluating betting opportunities...\n")
    decisions = []
    for market in markets:
        d = decide(ws, market)
        print(f"  Market: {market.question[:80]}")
        print(f"  {summarise_decision(d)}")
        if d is not None:
            decisions.append(d)

    if not decisions:
        print("\nNo trades meet the minimum edge threshold.")
        sys.exit(0)

    # ── 4. Execute ──────────────────────────────────────────────────
    print(f"[ Step 4 ] Placing {len(decisions)} order(s)...\n")

    if config.LIVE_TRADING and not config.PRIVATE_KEY:
        print("  ERROR: PRIVATE_KEY is not set. Cannot place live orders.")
        sys.exit(1)

    if config.LIVE_TRADING:
        try:
            from polymarket_client import PolymarketTrader
            trader = PolymarketTrader()
            balance = trader.get_balance()
            print(f"  Wallet USDC balance: ${balance:.2f}\n")
        except ImportError as exc:
            print(f"  ERROR: {exc}")
            sys.exit(1)
    else:
        trader = None

    for d in decisions:
        print(f"  -> {d.side} on '{d.market.question[:60]}'")
        print(f"     Stake ${d.stake_usdc:.2f} @ {d.limit_price}")

        if config.LIVE_TRADING and trader:
            result = trader.place_order(
                token_id=d.token_id,
                side="BUY",
                size_usdc=d.stake_usdc,
                price=d.limit_price,
            )
            if result:
                print(f"     Order placed: {result}")
            else:
                print("     Order failed — see errors above.")
        else:
            print(f"     [dry-run] Skipped (set LIVE_TRADING=true to execute)")

    print(f"\n{'='*60}")
    print("  Bot run complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket Batumi weather betting bot")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live order placement (overrides LIVE_TRADING env var)",
    )
    args = parser.parse_args()
    run(live_override=args.live)
