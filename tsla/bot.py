#!/usr/bin/env python3
"""
TSLA Opening Momentum Bot
--------------------------
Waits for 9:30 AM New York time, records the open price, waits 2 minutes,
then goes LONG or SHORT based on direction with a 1:1 bracket order.

Usage:
    python bot.py [--live]     # --live overrides LIVE_ORDERS env var
    python bot.py --now        # skip the clock wait, trade immediately (testing)
"""

import argparse
import sys
import time
from datetime import datetime, timedelta

import pytz

import config
from market_data import make_data_client, get_latest_price
from strategy import build_setup, summarise as strategy_summary
from broker import (
    make_trading_client,
    market_is_open,
    account_equity,
    place_bracket_order,
)

NY = pytz.timezone(config.NY_TZ)


def now_ny() -> datetime:
    return datetime.now(NY)


def wait_until(target: datetime, label: str) -> None:
    while True:
        remaining = (target - now_ny()).total_seconds()
        if remaining <= 0:
            break
        mins, secs = divmod(int(remaining), 60)
        print(f"\r  Waiting for {label}... {mins:02d}:{secs:02d} remaining", end="", flush=True)
        time.sleep(1)
    print()


def next_open_time() -> datetime:
    """Return the next 9:30 AM ET (today if it hasn't passed yet, else tomorrow)."""
    now = now_ny()
    candidate = now.replace(
        hour=config.MARKET_OPEN_HOUR,
        minute=config.MARKET_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )
    if now >= candidate:
        candidate += timedelta(days=1)
    return candidate


def run(live_override: bool = False, skip_wait: bool = False):
    if live_override:
        config.LIVE_ORDERS = True

    mode = "LIVE" if config.LIVE_ORDERS else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  TSLA Opening Momentum Bot  [{mode}]")
    print(f"{'='*60}")

    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        print("\n  ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY not set in .env")
        sys.exit(1)

    data_client = make_data_client()
    trading_client = make_trading_client()

    # Show account info
    equity = account_equity(trading_client)
    acct_label = "paper" if config.PAPER else "LIVE"
    print(f"\n  Account [{acct_label}] equity: ${equity:,.2f}")
    print(f"  Risk per trade: ${config.RISK_PER_TRADE_USD:.2f}  |  "
          f"Max shares: {config.MAX_SHARES}  |  "
          f"Min move: ${config.MIN_MOVE_USD:.2f}\n")

    # ── Step 1: Wait for 9:30 AM ET ──────────────────────────────────
    if not skip_wait:
        open_time = next_open_time()
        print(f"[ Step 1 ] Waiting for market open: {open_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        wait_until(open_time, "9:30 AM ET open")
    else:
        print("[ Step 1 ] --now flag set, skipping clock wait.\n")

    # Confirm market is actually open
    if not market_is_open(trading_client):
        print("  Market is not open right now (weekend or holiday). Exiting.")
        sys.exit(0)

    # ── Step 2: Capture open price ───────────────────────────────────
    print("[ Step 2 ] Capturing TSLA open price...")
    open_price = get_latest_price(data_client)
    open_time_actual = now_ny()
    print(f"  Open price : ${open_price:.4f}  at {open_time_actual.strftime('%H:%M:%S %Z')}")

    # ── Step 3: Wait 2 minutes ───────────────────────────────────────
    signal_time = open_time_actual + timedelta(seconds=config.SIGNAL_WAIT_SECONDS)
    print(f"\n[ Step 3 ] Waiting 2 minutes for signal...")
    if not skip_wait:
        wait_until(signal_time, "signal at 9:32 AM")
    else:
        print("  --now flag: skipping 2-minute wait.\n")

    # ── Step 4: Read signal price ────────────────────────────────────
    print("[ Step 4 ] Reading signal price...")
    signal_price = get_latest_price(data_client)
    print(f"  Signal price: ${signal_price:.4f}  at {now_ny().strftime('%H:%M:%S %Z')}")

    # ── Step 5: Build trade setup ────────────────────────────────────
    print("\n[ Step 5 ] Evaluating trade setup...")
    setup = build_setup(open_price, signal_price)
    print(f"\n  {strategy_summary(setup)}")

    if setup is None:
        print("  No trade taken. Exiting.")
        sys.exit(0)

    # ── Step 6: Place order ──────────────────────────────────────────
    print("[ Step 6 ] Placing bracket order...")

    if not config.LIVE_ORDERS:
        print(f"\n  [dry-run] Would submit:")
        print(f"    {setup.direction} {setup.shares} shares of {config.SYMBOL}")
        print(f"    Stop loss  : ${setup.stop_loss:.4f}")
        print(f"    Take profit: ${setup.take_profit:.4f}")
        print(f"\n  Set LIVE_ORDERS=true in .env (or use --live) to execute.\n")
        sys.exit(0)

    try:
        order = place_bracket_order(trading_client, setup)
        print(f"\n  Order submitted:")
        print(f"    Order ID   : {order.id}")
        print(f"    Status     : {order.status}")
        print(f"    Symbol     : {order.symbol}")
        print(f"    Qty        : {order.qty}")
        print(f"    Side       : {order.side}")
        print(f"    Order class: {order.order_class}")
    except Exception as exc:
        print(f"\n  ERROR placing order: {exc}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  Bot run complete. Monitor your Alpaca dashboard for fills.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TSLA opening momentum bot")
    parser.add_argument("--live", action="store_true", help="Enable live order submission")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Skip the clock wait and trade immediately (for testing)",
    )
    args = parser.parse_args()
    run(live_override=args.live, skip_wait=args.now)
