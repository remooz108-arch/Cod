#!/usr/bin/env python3
"""
Geopolitical News Signal Bot
------------------------------
Continuously scans news RSS feeds (+ optional NewsAPI) for articles
containing "Trump", "Iran", AND "Israel". When all three appear in the
same article, it buys XLE (oil ETF) and GLD (gold ETF) with 1:1
bracket orders on Alpaca.

Usage:
    python bot.py           # dry-run, polls every POLL_INTERVAL seconds
    python bot.py --live    # submits real (paper or live) orders
    python bot.py --once    # single scan, then exit (good for testing)
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from news_scanner import fetch_all_articles, Article
from signal import find_signals, highlight
from trades import build_trade, summarise as trade_summary
from broker import (
    make_trading_client,
    make_data_client,
    get_price,
    market_is_open,
    has_open_position,
    place_bracket_order,
    account_equity,
)


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_seen() -> set[str]:
    p = Path(config.SEEN_ARTICLES_FILE)
    if p.exists():
        return set(json.loads(p.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    Path(config.SEEN_ARTICLES_FILE).write_text(json.dumps(list(seen)))


def load_cooldowns() -> dict[str, float]:
    p = Path("cooldowns.json")
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_cooldowns(cd: dict[str, float]) -> None:
    Path("cooldowns.json").write_text(json.dumps(cd))


def log_signal(article: Article) -> None:
    with open(config.LOG_FILE, "a") as f:
        f.write(f"\n[{ts()}] SIGNAL FIRED\n")
        f.write(f"  {article.source}: {article.title}\n")
        f.write(f"  {article.url}\n")


def run_scan(
    trading_client,
    data_client,
    seen: set[str],
    cooldowns: dict[str, float],
) -> None:
    print(f"\n[{ts()}] Scanning {len(config.RSS_FEEDS)} RSS feeds"
          + (" + NewsAPI" if config.NEWS_API_KEY else "") + "...")

    articles = fetch_all_articles()
    print(f"  Fetched {len(articles)} articles total.")

    new_articles = [a for a in articles if a.id not in seen]
    print(f"  {len(new_articles)} new (unseen) articles.")

    signals = find_signals(new_articles)

    # Mark all new articles as seen regardless of signal
    for a in new_articles:
        seen.add(a.id)
    save_seen(seen)

    if not signals:
        print("  No matching articles found this scan.")
        return

    print(f"\n  *** {len(signals)} SIGNAL(S) DETECTED ***")
    for article in signals:
        print(f"\n{highlight(article)}")
        log_signal(article)

    # Only trade if market is open
    if not market_is_open(trading_client):
        print("  Market is closed — signal logged but no orders placed.")
        return

    now = time.time()

    for symbol in config.SIGNAL_TICKERS:
        # Check cooldown
        last_trade = cooldowns.get(symbol, 0)
        if now - last_trade < config.TRADE_COOLDOWN:
            remaining = int(config.TRADE_COOLDOWN - (now - last_trade))
            print(f"  [{symbol}] Cooldown active — {remaining}s remaining, skipping.")
            continue

        # Check for existing position
        if has_open_position(trading_client, symbol):
            print(f"  [{symbol}] Already have an open position, skipping.")
            continue

        # Fetch current price
        price = get_price(data_client, symbol)
        if price == 0:
            print(f"  [{symbol}] Could not fetch price, skipping.")
            continue

        setup = build_trade(symbol, price)
        if setup is None:
            print(f"  [{symbol}] Could not build trade setup, skipping.")
            continue

        print(f"\n  Trade setup for {symbol}:")
        print(trade_summary(setup))

        if not config.LIVE_ORDERS:
            print(f"  [dry-run] Would submit bracket BUY order for {symbol}.")
            print(f"            Set LIVE_ORDERS=true (or --live) to execute.\n")
            continue

        try:
            order = place_bracket_order(trading_client, setup)
            cooldowns[symbol] = now
            save_cooldowns(cooldowns)
            print(f"  ORDER SUBMITTED: {order.id}  status={order.status}")
        except Exception as exc:
            print(f"  ERROR placing order for {symbol}: {exc}")


def run(live_override: bool = False, once: bool = False):
    if live_override:
        config.LIVE_ORDERS = True

    mode = "LIVE" if config.LIVE_ORDERS else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Geopolitical News Signal Bot  [{mode}]")
    print(f"{'='*60}")
    print(f"  Keywords  : {' + '.join(config.REQUIRED_KEYWORDS)}")
    print(f"  Tickers   : {', '.join(config.SIGNAL_TICKERS)}")
    print(f"  Interval  : every {config.POLL_INTERVAL}s")
    print(f"  Mode      : {'paper' if config.PAPER else 'LIVE'} Alpaca")
    print(f"{'='*60}")

    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        print("\n  ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY not set in .env")
        sys.exit(1)

    trading_client = make_trading_client()
    data_client = make_data_client()

    equity = account_equity(trading_client)
    print(f"\n  Account equity : ${equity:,.2f}")
    print(f"  Risk/trade     : ${config.RISK_PER_TRADE_USD:.2f}")
    print(f"  Cooldown       : {config.TRADE_COOLDOWN}s between trades per ticker\n")

    seen = load_seen()
    cooldowns = load_cooldowns()

    print(f"  Loaded {len(seen)} previously seen article IDs.")
    print(f"  Signals will be logged to: {config.LOG_FILE}\n")

    if once:
        run_scan(trading_client, data_client, seen, cooldowns)
        return

    print(f"  Running continuously. Press Ctrl+C to stop.\n")
    while True:
        try:
            run_scan(trading_client, data_client, seen, cooldowns)
            print(f"\n  Next scan in {config.POLL_INTERVAL}s...")
            time.sleep(config.POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n\n  Stopped by user. Exiting.")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Geopolitical news signal trading bot")
    parser.add_argument("--live", action="store_true", help="Submit real orders")
    parser.add_argument("--once", action="store_true", help="Single scan then exit")
    args = parser.parse_args()
    run(live_override=args.live, once=args.once)
