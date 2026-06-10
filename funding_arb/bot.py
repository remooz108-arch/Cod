#!/usr/bin/env python3
"""
Funding Rate Arbitrage Bot
---------------------------
The Strategy
  When perpetual futures funding rates are positive, longs PAY shorts.
  By holding long spot + short perp simultaneously (delta-neutral), you
  COLLECT that payment every 8 hours with zero directional risk.

  Entry: funding rate > MIN_FUNDING_RATE (default 0.03% per 8h = 32% APY)
  Exit:  funding rate falls below EXIT_FUNDING_RATE or goes negative

  Real example:
    BTC funding rate = 0.1% per 8h
    Deploy $500: buy $250 BTC spot, short $250 BTC perp
    Collect $0.25 every 8 hours = $0.75/day = $273/year on $500
    That's 54.6% APY with ZERO directional risk.

Usage:
    python bot.py              # scan only, no orders, show dashboard
    python bot.py --live       # place real orders
    python bot.py --no-ui      # headless / log mode
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime

import config
from exchanges import (
    build_exchanges,
    fetch_all_funding_rates,
    fetch_current_funding_rate,
    place_spot_buy,
    place_perp_short,
    close_spot_position,
    close_perp_position,
    get_spot_symbol,
)
from models import Position
from risk import RiskManager
from dashboard import Dashboard


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}")


# ── Entry ─────────────────────────────────────────────────────────────────────

def open_position(ex_name: str, exchanges: dict, rate, risk: RiskManager, live: bool) -> None:
    ok, reason = risk.can_open(ex_name, rate.base)
    if not ok:
        log(f"  Skip {ex_name}:{rate.base} — {reason}")
        return

    half = config.POSITION_SIZE_USDC / 2
    spot_symbol = get_spot_symbol(ex_name, rate.base)
    ex = exchanges[ex_name]

    log(f"  ENTERING {rate.base} on {ex_name} | rate={rate.rate_8h:.4%}/8h ({rate.apy:.1f}% APY)")

    spot_order_id = None
    perp_order_id = None
    spot_qty      = half / rate.mark_price if rate.mark_price else 0

    if live:
        try:
            spot_resp = place_spot_buy(ex, rate.base, half)
            spot_order_id = spot_resp.get("id")
            spot_qty = float(spot_resp.get("filled") or spot_resp.get("amount") or spot_qty)
            log(f"    Spot BUY  filled: {spot_qty:.6f} {rate.base} (order {spot_order_id})")
        except Exception as exc:
            log(f"    ERROR spot buy: {exc}")
            return

        try:
            perp_resp = place_perp_short(ex, rate.symbol, half)
            perp_order_id = perp_resp.get("id")
            log(f"    Perp SHORT filled: {perp_order_id}")
        except Exception as exc:
            log(f"    ERROR perp short (spot leg already open!): {exc}")
            log(f"    WARNING: You now have an unhedged {rate.base} spot position. Close manually.")
            return
    else:
        log(f"    [dry-run] Would buy ${half:.2f} {rate.base} spot + short ${half:.2f} {rate.symbol}")

    pos = Position(
        id=f"{ex_name}:{rate.base}",
        exchange=ex_name,
        base=rate.base,
        spot_symbol=spot_symbol,
        perp_symbol=rate.symbol,
        spot_qty=spot_qty,
        perp_qty=spot_qty,
        entry_spot_price=rate.mark_price,
        entry_perp_price=rate.mark_price,
        size_usdc=config.POSITION_SIZE_USDC,
        opened_at=datetime.utcnow(),
        last_rate_8h=rate.rate_8h,
        spot_order_id=spot_order_id,
        perp_order_id=perp_order_id,
    )
    risk.record_open(pos)
    log(f"  Position opened: {pos.id}")


# ── Exit ──────────────────────────────────────────────────────────────────────

def close_position(pos: Position, exchanges: dict, risk: RiskManager, live: bool, reason: str) -> None:
    log(f"  EXITING {pos.id} — {reason}")
    ex = exchanges.get(pos.exchange)

    if live and ex:
        try:
            close_spot_position(ex, pos.base, pos.spot_qty)
            log(f"    Spot SELL {pos.spot_qty:.6f} {pos.base} done")
        except Exception as exc:
            log(f"    ERROR closing spot: {exc}")

        try:
            close_perp_position(ex, pos.perp_symbol, pos.perp_qty)
            log(f"    Perp BUY-BACK {pos.perp_qty:.6f} done")
        except Exception as exc:
            log(f"    ERROR closing perp: {exc}")
    else:
        log(f"    [dry-run] Would close spot + perp for {pos.id}")

    risk.record_close(pos.id)
    log(f"  Position closed. Funding collected: ${pos.funding_collected:.4f}")


# ── Funding accrual ───────────────────────────────────────────────────────────

def accrue_funding(positions: list[Position], exchanges: dict, risk: RiskManager) -> None:
    """
    Called every scan. Estimates funding received since last period.
    In production, the exchange credits funding automatically every 8h.
    We track it here for P&L accounting.
    """
    for pos in positions:
        ex = exchanges.get(pos.exchange)
        if not ex:
            continue
        rate = fetch_current_funding_rate(ex, pos.perp_symbol)
        if rate is None:
            continue
        # Funding accrues every 8 hours. We approximate on each scan.
        # On live, the exchange pays directly to your margin balance.
        # Here we record the theoretical amount for display purposes.
        # Real tracking: compare margin balance before/after funding timestamps.
        risk.record_funding(pos.id, 0.0, rate)  # amount=0 until real fills
        pos.last_rate_8h = rate


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(live: bool = False, no_ui: bool = False) -> None:
    if live:
        config.LIVE_TRADING = True

    mode = "LIVE" if config.LIVE_TRADING else "DRY-RUN"
    print(f"\n{'='*66}")
    print(f"  FUNDING RATE ARBITRAGE BOT  [{mode}]")
    print(f"{'='*66}")
    print(f"  Strategy : Long spot + Short perp → collect funding every 8h")
    print(f"  Entry    : rate > {config.MIN_FUNDING_RATE:.4%}/8h  ({config.rate_to_apy(config.MIN_FUNDING_RATE):.1f}% APY)")
    print(f"  Exit     : rate < {config.EXIT_FUNDING_RATE:.4%}/8h or negative")
    print(f"  Size     : ${config.POSITION_SIZE_USDC:.0f} USDC per position")
    print(f"  Max pos  : {config.MAX_POSITIONS}  |  Cap: ${config.MAX_TOTAL_USDC:,.0f} USDC")
    print(f"{'='*66}\n")

    log("Building exchange connections...")
    exchanges = build_exchanges()
    log(f"Connected to: {', '.join(exchanges.keys())}\n")

    risk = RiskManager()
    dashboard = None if no_ui else Dashboard(risk, live_mode=config.LIVE_TRADING)
    if dashboard:
        dashboard.start()

    scan_count = 0
    top_rates: list = []

    try:
        while True:
            scan_count += 1
            if not no_ui:
                pass  # dashboard shows scanning state
            else:
                log(f"Scan #{scan_count} — fetching funding rates...")

            # ── Fetch rates ───────────────────────────────────────────────────
            try:
                all_rates = fetch_all_funding_rates(exchanges)
                top_rates = [r for r in all_rates if r.rate_8h > 0]
            except Exception as exc:
                log(f"Rate fetch error: {exc}")
                time.sleep(config.SCAN_INTERVAL)
                continue

            if dashboard:
                dashboard.update(top_rates[:10], scan_count)

            if no_ui and top_rates:
                log(f"Top rate: {top_rates[0].exchange} {top_rates[0].base} "
                    f"{top_rates[0].rate_8h:.4%}/8h = {top_rates[0].apy:.1f}% APY")

            # ── Check exits on open positions ─────────────────────────────────
            for pos in risk.open_positions():
                ex = exchanges.get(pos.exchange)
                current_rate = fetch_current_funding_rate(ex, pos.perp_symbol) if ex else None
                should_exit, reason = risk.should_exit(pos, current_rate)
                if should_exit:
                    close_position(pos, exchanges, risk, live=config.LIVE_TRADING, reason=reason)

            # ── Accrue funding on open positions ──────────────────────────────
            accrue_funding(risk.open_positions(), exchanges, risk)

            # ── Open new positions ────────────────────────────────────────────
            for rate in top_rates:
                if rate.rate_8h < config.MIN_FUNDING_RATE:
                    break  # list is sorted descending
                pos_id = f"{rate.exchange}:{rate.base}"
                if any(p.id == pos_id for p in risk.open_positions()):
                    continue
                open_position(rate.exchange, exchanges, rate, risk, live=config.LIVE_TRADING)

            time.sleep(config.SCAN_INTERVAL)

    except KeyboardInterrupt:
        log("\nStopping...")
        if dashboard:
            dashboard.stop()

        stats = risk.get_stats()
        print(f"\n{'='*66}")
        print(f"  Session summary")
        print(f"  Open positions   : {stats['open_positions']}")
        print(f"  Total deployed   : ${stats['total_deployed']:,.2f}")
        print(f"  Funding earned   : ${stats['total_funding_earned']:+.4f}")
        print(f"{'='*66}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Funding rate arbitrage bot")
    parser.add_argument("--live",  action="store_true", help="Place real orders")
    parser.add_argument("--no-ui", action="store_true", dest="no_ui", help="Log mode, no dashboard")
    args = parser.parse_args()
    run(live=args.live, no_ui=args.no_ui)
