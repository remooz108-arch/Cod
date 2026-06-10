#!/usr/bin/env python3
"""
Funding Rate Arbitrage Bot — v2 (altcoin + multi-exchange + auto-compound)
--------------------------------------------------------------------------
Strategy
  Long spot + Short perp = delta-neutral position that COLLECTS the
  funding payment every 8 hours.  No directional risk.

  Entry: funding rate > MIN_FUNDING_RATE (default 0.03 %/8h = ~32 % APY)
  Exit:  rate falls below EXIT_FUNDING_RATE or flips negative

Exchanges scanned
  Binance, Bybit, OKX, Gate.io, Hyperliquid
  Gate.io excels at altcoin memecoins (PEPE, SHIB, WIF, BONK).
  Hyperliquid is scanned for rate intelligence; its positions are flagged
  as "manual cross-exchange" — buy spot on a CEX, short perp on HL.

Auto-compound
  Each time total funding earned crosses a multiple of COMPOUND_THRESHOLD
  the effective position size increases 10 %, snowballing returns over time.

Rate spike alerts
  Any rate above SPIKE_ALERT_RATE (default 0.2 %/8h ≈ 220 % APY) triggers
  a visible alert and log line.

Usage
  python bot.py              # scan only, no orders, Rich dashboard
  python bot.py --live       # place real orders
  python bot.py --no-ui      # log mode (headless server)
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import config
from exchanges import (
    build_exchanges,
    fetch_all_funding_rates,
    fetch_current_funding_rate,
    has_spot_market,
    place_spot_buy,
    place_perp_short,
    close_spot_position,
    close_perp_position,
    get_spot_symbol,
    PERP_ONLY_EXCHANGES,
)
from models import Position
from risk import RiskManager
from dashboard import Dashboard


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}")


# ── Entry ─────────────────────────────────────────────────────────────────────

def open_position(
    ex_name: str, exchanges: dict, rate, risk: RiskManager, live: bool
) -> None:
    # Hyperliquid (and any other perp-only exchange) needs cross-exchange hedging.
    # We surface the signal but don't auto-execute.
    if rate.perp_only:
        log(
            f"  ⚡ SIGNAL {ex_name}:{rate.base}  {rate.rate_8h:.4%}/8h "
            f"= {rate.apy:.0f}% APY  [perp-only — manual cross-exchange arb]"
        )
        return

    pos_size = risk.effective_position_size()
    ok, reason = risk.can_open(ex_name, rate.base, size_override=pos_size)
    if not ok:
        log(f"  Skip {ex_name}:{rate.base} — {reason}")
        return

    # Verify spot market exists before committing
    ex = exchanges[ex_name]
    if not has_spot_market(ex, rate.base):
        log(f"  Skip {ex_name}:{rate.base} — no spot market")
        return

    half         = pos_size / 2
    spot_symbol  = get_spot_symbol(ex_name, rate.base)
    spot_qty     = half / rate.mark_price if rate.mark_price else 0

    compound_tag = (
        f" [compound ×{risk.compound_step() + 1}  ${pos_size:.0f}]"
        if risk.compound_step() > 0 else ""
    )
    log(
        f"  ENTERING {rate.base} on {ex_name} | "
        f"rate={rate.rate_8h:.4%}/8h ({rate.apy:.1f}% APY){compound_tag}"
    )

    spot_order_id = perp_order_id = None

    if live:
        try:
            sr          = place_spot_buy(ex, rate.base, half)
            spot_order_id = sr.get("id")
            spot_qty    = float(sr.get("filled") or sr.get("amount") or spot_qty)
            log(f"    Spot BUY  {spot_qty:.6f} {rate.base} (order {spot_order_id})")
        except Exception as exc:
            log(f"    ERROR spot buy: {exc}")
            return

        try:
            pr            = place_perp_short(ex, rate.symbol, half)
            perp_order_id = pr.get("id")
            log(f"    Perp SHORT filled: {perp_order_id}")
        except Exception as exc:
            log(f"    ERROR perp short (spot leg already open!): {exc}")
            log(f"    CRITICAL: Unhedged {rate.base} spot on {ex_name} — close manually.")
            return
    else:
        log(
            f"    [dry-run] Would buy ${half:.2f} {rate.base} spot "
            f"+ short ${half:.2f} {rate.symbol}"
        )

    pos = Position(
        id=f"{ex_name}:{rate.base}",
        exchange=ex_name,
        base=rate.base,
        spot_symbol=spot_symbol,
        perp_symbol=rate.symbol,
        spot_exchange=ex_name,
        spot_qty=spot_qty,
        perp_qty=spot_qty,
        entry_spot_price=rate.mark_price,
        entry_perp_price=rate.mark_price,
        size_usdc=pos_size,
        opened_at=datetime.now(timezone.utc),
        last_rate_8h=rate.rate_8h,
        spot_order_id=spot_order_id,
        perp_order_id=perp_order_id,
    )
    risk.record_open(pos)
    log(f"  Position opened: {pos.id}  (${pos_size:.0f} USDC deployed)")


# ── Exit ──────────────────────────────────────────────────────────────────────

def close_position(
    pos: Position, exchanges: dict, risk: RiskManager, live: bool, reason: str
) -> None:
    log(f"  EXITING {pos.id} — {reason}")
    spot_ex = exchanges.get(pos.spot_exchange)
    perp_ex = exchanges.get(pos.exchange)

    if live:
        if not spot_ex or not perp_ex:
            # Cannot close without both exchange objects — leave position open
            # and do NOT remove it from RiskManager so the next scan retries.
            missing = pos.spot_exchange if not spot_ex else pos.exchange
            log(f"    ABORT close: exchange '{missing}' not in exchanges dict. "
                f"Position remains open. Check your API keys.")
            return

        try:
            close_spot_position(spot_ex, pos.base, pos.spot_qty)
            log(f"    Spot SELL {pos.spot_qty:.6f} {pos.base} done")
        except Exception as exc:
            log(f"    ERROR closing spot: {exc}")

        try:
            close_perp_position(perp_ex, pos.perp_symbol, pos.perp_qty)
            log(f"    Perp BUY-BACK {pos.perp_qty:.6f} done")
        except Exception as exc:
            log(f"    ERROR closing perp: {exc}")
    else:
        log(f"    [dry-run] Would close spot + perp for {pos.id}")

    risk.record_close(pos.id)
    log(f"  Position closed. Funding collected: ${pos.funding_collected:.4f}")


# ── Funding accrual ───────────────────────────────────────────────────────────

_EIGHT_HOURS_S = 8 * 3600


def accrue_funding(
    positions: list[Position], exchanges: dict, risk: RiskManager
) -> None:
    now = datetime.now(timezone.utc)
    for pos in positions:
        ex = exchanges.get(pos.exchange)
        if not ex:
            continue
        rate = fetch_current_funding_rate(ex, pos.perp_symbol)
        if rate is None:
            continue

        # Always update the displayed rate — done under lock via update_rate().
        risk.update_rate(pos.id, rate)

        # Count a funding period only when 8 hours have elapsed.
        # Exchange credits the payment to the margin balance automatically.
        baseline = pos.last_period_at if pos.last_period_at is not None else pos.opened_at
        if (now - baseline).total_seconds() >= _EIGHT_HOURS_S:
            risk.record_funding(pos.id, 0.0, rate, period_at=now)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(live: bool = False, no_ui: bool = False) -> None:
    if live:
        config.LIVE_TRADING = True

    mode = "LIVE" if config.LIVE_TRADING else "DRY-RUN"
    print(f"\n{'='*70}")
    print(f"  FUNDING RATE ARBITRAGE BOT  v2  [{mode}]")
    print(f"{'='*70}")
    print(f"  Strategy   : Long spot + Short perp → collect funding every 8h")
    print(f"  Entry      : rate > {config.MIN_FUNDING_RATE:.4%}/8h  "
          f"({config.rate_to_apy(config.MIN_FUNDING_RATE):.1f}% APY)")
    print(f"  Exit       : rate < {config.EXIT_FUNDING_RATE:.4%}/8h or negative")
    print(f"  Position   : ${config.POSITION_SIZE_USDC:.0f} USDC base size")
    print(f"  Max pos    : {config.MAX_POSITIONS}  |  Cap: ${config.MAX_TOTAL_USDC:,.0f} USDC")
    print(f"  Exchanges  : Binance · Bybit · OKX · Gate.io · Hyperliquid")
    print(f"  Compound   : {'ON' if config.COMPOUND_ENABLED else 'OFF'}  "
          f"(+10 % per ${config.COMPOUND_THRESHOLD:.0f} earned)")
    print(f"  Spike alert: rate > {config.SPIKE_ALERT_RATE:.4%}/8h  "
          f"({config.rate_to_apy(config.SPIKE_ALERT_RATE):.0f}% APY)")
    print(f"  Daily goal : ${config.TARGET_DAILY_USDC:.0f}")
    est_daily = config.daily_income_est(config.MIN_FUNDING_RATE, config.MAX_TOTAL_USDC)
    print(f"  Est. daily : ${est_daily:.2f} (full cap at entry threshold)")
    print(f"{'='*70}\n")

    log("Building exchange connections…")
    exchanges = build_exchanges()
    log(f"Connected: {', '.join(exchanges.keys())}\n")

    risk = RiskManager()

    # Restore any positions that were open before the last restart.
    restored = risk.load_state()
    if restored:
        log(f"Restored {restored} position(s) from {config.STATE_FILE}")
    else:
        log(f"No saved state found — starting fresh")

    dashboard = None if no_ui else Dashboard(risk, live_mode=config.LIVE_TRADING)
    if dashboard:
        dashboard.start()

    scan_count = 0
    top_rates: list = []

    try:
        while True:
            scan_count += 1
            if no_ui:
                log(f"Scan #{scan_count} — fetching rates across all exchanges…")

            # ── Fetch rates (parallel) ────────────────────────────────────────
            try:
                all_rates = fetch_all_funding_rates(exchanges)
                top_rates = [r for r in all_rates if r.rate_8h > 0]
            except Exception as exc:
                log(f"Rate fetch error: {exc}")
                time.sleep(config.SCAN_INTERVAL)
                continue

            if dashboard:
                dashboard.update(top_rates[:12], scan_count)

            if no_ui and top_rates:
                log(
                    f"Top rate: {top_rates[0].exchange} {top_rates[0].base} "
                    f"{top_rates[0].rate_8h:.4%}/8h = {top_rates[0].apy:.1f}% APY"
                )

            # ── Spike alerts ──────────────────────────────────────────────────
            new_spikes = risk.check_spikes(top_rates)
            for spike in new_spikes:
                log(f"  ⚡ SPIKE ALERT: {spike}")

            # Snapshot once per scan to avoid redundant lock+copy calls.
            positions = risk.open_positions()

            # ── Check exits on open positions ─────────────────────────────────
            for pos in positions:
                ex           = exchanges.get(pos.exchange)
                current_rate = fetch_current_funding_rate(ex, pos.perp_symbol) if ex else None
                should, reason = risk.should_exit(pos, current_rate)
                if should:
                    close_position(
                        pos, exchanges, risk,
                        live=config.LIVE_TRADING, reason=reason,
                    )
                    risk.save_state()

            # ── Accrue funding ────────────────────────────────────────────────
            accrue_funding(positions, exchanges, risk)

            # ── Open new positions ────────────────────────────────────────────
            open_ids = {p.id for p in positions}
            for rate in top_rates:
                if rate.rate_8h < config.MIN_FUNDING_RATE:
                    break  # sorted descending
                if f"{rate.exchange}:{rate.base}" in open_ids:
                    continue
                open_position(
                    rate.exchange, exchanges, rate, risk,
                    live=config.LIVE_TRADING,
                )
                risk.save_state()

            # ── Compound progress log ─────────────────────────────────────────
            if no_ui:
                daily = risk.daily_earned()
                total = risk.total_funding_earned()
                eff   = risk.effective_position_size()
                log(
                    f"  Earned today: ${daily:.4f} / ${config.TARGET_DAILY_USDC:.0f} target  "
                    f"| All-time: ${total:.4f}  | Position size: ${eff:.0f}"
                )

            time.sleep(config.SCAN_INTERVAL)

    except KeyboardInterrupt:
        log("\nStopping…")
        if dashboard:
            dashboard.stop()

        stats = risk.get_stats()
        print(f"\n{'='*70}")
        print(f"  Session summary")
        print(f"  Open positions   : {stats['open_positions']}")
        print(f"  Total deployed   : ${stats['total_deployed']:,.2f}")
        print(f"  Funding earned   : ${stats['total_funding_earned']:+.4f}")
        print(f"  Today's earnings : ${stats['daily_earned']:+.4f} "
              f"/ ${config.TARGET_DAILY_USDC:.0f} target")
        print(f"  Compound step    : ×{stats['compound_step'] + 1}  "
              f"(pos size ${stats['effective_position_size']:.0f})")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Funding rate arbitrage bot v2")
    parser.add_argument("--live",  action="store_true", help="Place real orders")
    parser.add_argument("--no-ui", action="store_true", dest="no_ui",
                        help="Log mode, no dashboard")
    args = parser.parse_args()
    run(live=args.live, no_ui=args.no_ui)
