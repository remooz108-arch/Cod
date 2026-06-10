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
import csv
import os
import time
from datetime import datetime, timezone
from typing import Optional

import config
from exchanges import (
    build_exchanges,
    fetch_all_funding_rates,
    fetch_available_balance,
    fetch_current_funding_rate,
    fetch_margin_ratio,
    has_spot_market,
    place_spot_buy,
    place_spot_buy_maker,
    place_perp_short,
    place_perp_short_maker,
    set_leverage,
    close_spot_position,
    close_spot_position_maker,
    close_perp_position,
    close_perp_position_maker,
    get_spot_symbol,
    PERP_ONLY_EXCHANGES,
)
from models import Position
from risk import RiskManager
from dashboard import Dashboard
import notify


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}")


# ── Trade journal ────────────────────────────────────────────────────────────

def _log_trade(pos: "Position", reason: str) -> None:
    """Append one closed trade to the CSV journal for performance tracking."""
    path = config.TRADE_JOURNAL_FILE
    write_header = not os.path.exists(path)
    try:
        with open(path, "a", newline="") as fh:
            w = csv.writer(fh)
            if write_header:
                w.writerow([
                    "closed_at", "exchange", "base", "size_usdc",
                    "periods", "funding_collected", "apy_realised_pct",
                    "opened_at", "duration_hours", "reason", "entry_thesis",
                ])
            now   = datetime.now(timezone.utc)
            hours = (
                (now - pos.opened_at).total_seconds() / 3600
                if pos.opened_at else ""
            )
            w.writerow([
                now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                pos.exchange, pos.base, f"{pos.size_usdc:.2f}",
                pos.funding_periods,
                f"{pos.funding_collected:.6f}",
                f"{pos.apy_realised:.2f}" if pos.funding_periods > 0 else "n/a",
                pos.opened_at.strftime("%Y-%m-%d %H:%M:%S UTC") if pos.opened_at else "",
                f"{hours:.1f}" if hours != "" else "",
                reason,
                pos.entry_note,
            ])
    except Exception as exc:
        log(f"  [warn] trade journal write failed: {exc}")


# ── Equity curve snapshot ─────────────────────────────────────────────────────

def _snapshot_equity(risk: "RiskManager") -> None:
    """Append a timestamped equity row to the curve CSV (for plotting growth)."""
    path = config.EQUITY_CURVE_FILE
    write_header = not os.path.exists(path)
    try:
        stats = risk.get_stats()
        with open(path, "a", newline="") as fh:
            w = csv.writer(fh)
            if write_header:
                w.writerow([
                    "timestamp", "total_earned", "daily_earned",
                    "total_deployed", "open_positions", "avg_apy_pct",
                    "compound_step",
                ])
            w.writerow([
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                f"{stats['total_funding_earned']:.6f}",
                f"{stats['daily_earned']:.6f}",
                f"{stats['total_deployed']:.2f}",
                stats["open_positions"],
                f"{stats['avg_apy']:.2f}",
                stats["compound_step"],
            ])
    except Exception as exc:
        log(f"  [warn] equity snapshot write failed: {exc}")


# ── Hedge drift check ─────────────────────────────────────────────────────────

def check_hedge_drift(
    positions: list, exchanges: dict, risk: "RiskManager", live: bool
) -> None:
    """Alert or exit when spot price has drifted too far from the entry price."""
    for pos in positions:
        ex = exchanges.get(pos.exchange)
        if not ex or not pos.entry_perp_price:
            continue
        try:
            ticker  = ex.fetch_ticker(pos.perp_symbol)
            current = ticker.get("last") or ticker.get("markPrice") or ticker.get("mark")
            if not current:
                continue
            drift = abs(float(current) - pos.entry_perp_price) / pos.entry_perp_price
            if drift >= config.HEDGE_DRIFT_EXIT_PCT:
                reason = (
                    f"Hedge drift {drift:.1%} "
                    f"(entry ${pos.entry_perp_price:.4f} → ${float(current):.4f})"
                )
                log(f"  EXIT {pos.id} — {reason}")
                close_position(pos, exchanges, risk, live=live, reason=reason)
                risk.save_state()
            elif drift >= config.HEDGE_DRIFT_ALERT_PCT:
                log(f"  ⚠️  HEDGE DRIFT {pos.id}: {drift:.1%} from entry")
                notify.hedge_drift_alert(pos.exchange, pos.base, drift)
        except Exception:
            pass


# ── Margin health guard ───────────────────────────────────────────────────────

def check_margin_health(
    positions: list, exchanges: dict, risk: "RiskManager", live: bool
) -> None:
    """Alert or exit positions whose perp short margin is approaching liquidation."""
    for pos in positions:
        ex = exchanges.get(pos.exchange)
        if not ex:
            continue
        ratio = fetch_margin_ratio(ex, pos.perp_symbol)
        if ratio is None:
            continue
        if ratio >= config.MARGIN_EXIT_RATIO:
            reason = f"Margin critical: ratio {ratio:.2f} >= exit threshold {config.MARGIN_EXIT_RATIO}"
            log(f"  EXIT {pos.id} — {reason}")
            close_position(pos, exchanges, risk, live=live, reason=reason)
            risk.save_state()
            notify.margin_alert(pos.exchange, pos.base, ratio, "exited")
        elif ratio >= config.MARGIN_ALERT_RATIO:
            log(f"  ⚠️  MARGIN WARNING {pos.id}: ratio={ratio:.2f}")
            notify.margin_alert(pos.exchange, pos.base, ratio, "warning")


# ── Performance report ────────────────────────────────────────────────────────

def print_performance_report() -> None:
    """Print a full P&L breakdown from the trade journal CSV and exit."""
    from collections import defaultdict
    from datetime import timedelta

    path = config.TRADE_JOURNAL_FILE
    if not os.path.exists(path):
        print(f"No trade journal at {path}. Run the bot first.")
        return

    rows = []
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))

    if not rows:
        print("Trade journal is empty.")
        return

    def _dt(s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _earned(r: dict) -> float:
        try:
            return float(r.get("funding_collected") or 0)
        except ValueError:
            return 0.0

    now    = datetime.now(timezone.utc)
    week   = now - timedelta(days=7)
    month  = now - timedelta(days=30)

    total   = sum(_earned(r) for r in rows)
    last_7d = sum(_earned(r) for r in rows if (_dt(r.get("closed_at", "")) or now) >= week)
    last_30 = sum(_earned(r) for r in rows if (_dt(r.get("closed_at", "")) or now) >= month)

    by_exchange: dict[str, float] = defaultdict(float)
    by_asset:    dict[str, float] = defaultdict(float)
    apys: list[float] = []

    for r in rows:
        by_exchange[r.get("exchange", "?")] += _earned(r)
        by_asset[r.get("base", "?")]        += _earned(r)
        a = r.get("apy_realised_pct", "n/a")
        if a != "n/a":
            try:
                apys.append(float(a))
            except ValueError:
                pass

    avg_apy = sum(apys) / len(apys) if apys else 0.0
    n       = len(rows)

    print(f"\n{'='*70}")
    print(f"  FUNDING ARB PERFORMANCE REPORT")
    print(f"  Generated {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}")
    print(f"  Completed trades   : {n}")
    print(f"  All-time earned    : ${total:+.4f}")
    print(f"  Last 7 days        : ${last_7d:+.4f}")
    print(f"  Last 30 days       : ${last_30:+.4f}")
    print(f"  Avg realised APY   : {avg_apy:.1f}%")

    print(f"\n  ── By Exchange {'─'*40}")
    for ex, amt in sorted(by_exchange.items(), key=lambda x: -x[1]):
        bar = "█" * int(amt / max(total, 0.01) * 20) if total > 0 else ""
        print(f"  {ex:14s}  ${amt:+8.4f}  {bar}")

    print(f"\n  ── Top Assets {'─'*42}")
    for base, amt in sorted(by_asset.items(), key=lambda x: -x[1])[:12]:
        bar = "█" * int(amt / max(total, 0.01) * 20) if total > 0 else ""
        print(f"  {base:10s}  ${amt:+8.4f}  {bar}")

    print(f"\n  ── Exit Reasons {'─'*40}")
    reasons: dict[str, int] = defaultdict(int)
    for r in rows:
        reasons[r.get("reason", "unknown")] += 1
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:30s}  {count}×")

    print(f"{'='*70}\n")


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

    # Balance-aware sizing (live only): size from real free balance so the bot
    # self-calibrates as capital grows. Never exceed the compounded size cap.
    if config.BALANCE_AWARE_SIZING and live:
        free = fetch_available_balance(exchanges[ex_name])
        if free is not None and free > 0:
            balance_size = free * config.BALANCE_FRACTION
            pos_size = min(pos_size, balance_size) if balance_size > 0 else pos_size

    ok, reason = risk.can_open(ex_name, rate.base, size_override=pos_size)
    if not ok:
        log(f"  Skip {ex_name}:{rate.base} — {reason}")
        return

    # Verify spot market exists before committing
    ex = exchanges[ex_name]
    if not has_spot_market(ex, rate.base):
        log(f"  Skip {ex_name}:{rate.base} — no spot market")
        return

    # Entry quality gate: skip if round-trip fees can't be recovered in time.
    round_trip_cost = config.TAKER_FEE_PCT * 4
    if rate.rate_8h > 0 and (round_trip_cost / rate.rate_8h) > config.MAX_BREAKEVEN_PERIODS:
        log(f"  Skip {ex_name}:{rate.base} — breakeven "
            f"{round_trip_cost/rate.rate_8h:.1f} periods > {config.MAX_BREAKEVEN_PERIODS} max")
        return

    # Funding timing gate: if payment is imminent, bypass the stability scan.
    # Entering just before a funding settlement collects it with minimal exposure time.
    timing_bypass = False
    if config.TIMING_GATE_ENABLED and rate.next_funding:
        mins_to_funding = (
            rate.next_funding - datetime.now(timezone.utc)
        ).total_seconds() / 60
        if 0 < mins_to_funding <= config.TIMING_GATE_MINUTES:
            timing_bypass = True
            log(
                f"  ⏰ {ex_name}:{rate.base} — funding in {mins_to_funding:.0f}m, "
                f"timing gate active"
            )

    # Rate stability filter (bypassed when funding is imminent).
    if not timing_bypass and not risk.is_rate_stable(ex_name, rate.base):
        log(f"  Skip {ex_name}:{rate.base} — awaiting {config.RATE_STABILITY_SCANS} stable scans")
        return

    # Rate consistency filter: average must clear the floor and be steady, not flickering.
    consistent, why = risk.is_rate_consistent(ex_name, rate.base)
    if not consistent:
        log(f"  Skip {ex_name}:{rate.base} — {why}")
        return

    # Momentum filter: skip if the rate has been declining too rapidly.
    if config.MOMENTUM_FILTER_ENABLED:
        momentum = risk.rate_momentum(ex_name, rate.base)
        if momentum < config.MIN_RATE_MOMENTUM:
            log(
                f"  Skip {ex_name}:{rate.base} — momentum {momentum:+.0%} "
                f"(declining, threshold {config.MIN_RATE_MOMENTUM:+.0%})"
            )
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
        # Enforce low leverage before opening the short to maximise distance
        # from liquidation.  Silent no-op if the exchange doesn't support it.
        set_leverage(ex, rate.symbol, config.PERP_LEVERAGE)

        maker = config.MAKER_ORDER_ENABLED
        try:
            sr = (
                place_spot_buy_maker(ex, rate.base, half, config.MAKER_FILL_TIMEOUT)
                if maker else place_spot_buy(ex, rate.base, half)
            )
            spot_order_id = sr.get("id")
            spot_qty    = float(sr.get("filled") or sr.get("amount") or spot_qty)
            log(f"    Spot BUY  {spot_qty:.6f} {rate.base} "
                f"(order {spot_order_id}){' [maker]' if maker else ''}")
        except Exception as exc:
            log(f"    ERROR spot buy: {exc}")
            return

        try:
            pr = (
                place_perp_short_maker(ex, rate.symbol, half, config.MAKER_FILL_TIMEOUT)
                if maker else place_perp_short(ex, rate.symbol, half)
            )
            perp_order_id = pr.get("id")
            log(f"    Perp SHORT filled: {perp_order_id}"
                f"{' [maker]' if maker else ''}")
        except Exception as exc:
            log(f"    ERROR perp short (spot leg already open!): {exc}")
            log(f"    CRITICAL: Unhedged {rate.base} spot on {ex_name} — close manually.")
            return
    else:
        log(
            f"    [dry-run] Would buy ${half:.2f} {rate.base} spot "
            f"+ short ${half:.2f} {rate.symbol}"
        )

    # Capture the full entry thesis for the trade journal (why we entered).
    mean, std, n  = risk.rate_stats(ex_name, rate.base)
    momentum      = risk.rate_momentum(ex_name, rate.base)
    breakeven_p   = (round_trip_cost / rate.rate_8h) if rate.rate_8h > 0 else 0
    entry_note = (
        f"rate {rate.rate_8h:.4%}/8h ({rate.apy:.0f}% APY); "
        f"avg {mean:.4%} over {n} scans; "
        f"momentum {momentum:+.0%}; "
        f"breakeven {breakeven_p:.1f}p; size ${pos_size:.2f}"
        + ("; timing-gate" if timing_bypass else "")
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
        peak_rate_8h=rate.rate_8h,
        entry_note=entry_note,
        spot_order_id=spot_order_id,
        perp_order_id=perp_order_id,
    )
    risk.record_open(pos)
    log(f"  Position opened: {pos.id}  (${pos_size:.0f} USDC deployed)")
    notify.position_opened(ex_name, rate.base, pos_size, rate.rate_8h, rate.apy)


# ── Exit ──────────────────────────────────────────────────────────────────────

def close_position(
    pos: Position, exchanges: dict, risk: RiskManager, live: bool, reason: str,
    use_maker: bool = False,
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

        maker = use_maker and config.MAKER_ORDER_ENABLED
        try:
            if maker:
                close_spot_position_maker(spot_ex, pos.base, pos.spot_qty,
                                          config.MAKER_FILL_TIMEOUT)
            else:
                close_spot_position(spot_ex, pos.base, pos.spot_qty)
            log(f"    Spot SELL {pos.spot_qty:.6f} {pos.base} done"
                f"{' (maker)' if maker else ''}")
        except Exception as exc:
            log(f"    ERROR closing spot: {exc}")

        try:
            if maker:
                close_perp_position_maker(perp_ex, pos.perp_symbol, pos.perp_qty,
                                          config.MAKER_FILL_TIMEOUT)
            else:
                close_perp_position(perp_ex, pos.perp_symbol, pos.perp_qty)
            log(f"    Perp BUY-BACK {pos.perp_qty:.6f} done"
                f"{' (maker)' if maker else ''}")
        except Exception as exc:
            log(f"    ERROR closing perp: {exc}")
    else:
        log(f"    [dry-run] Would close spot + perp for {pos.id}")

    risk.record_close(pos.id)
    log(f"  Position closed. Funding collected: ${pos.funding_collected:.4f}")
    notify.position_closed(pos.exchange, pos.base, reason, pos.funding_collected)
    _log_trade(pos, reason)

    # Block re-entry of this asset for a cooldown window to prevent whipsawing.
    risk.start_cooldown(pos.exchange, pos.base)

    # Circuit breaker: count rate-flip exits (not rotations or drift exits).
    if "rate" in reason.lower() or "negative" in reason.lower() or "below" in reason.lower():
        risk.record_flip_exit()


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
    print(f"  Capital    : ${config.MAX_TOTAL_USDC:,.2f} USDC")
    print(f"  Strategy   : Long spot + Short perp → collect funding every 8h")
    print(f"  Entry      : rate > {config.MIN_FUNDING_RATE:.4%}/8h  "
          f"({config.rate_to_apy(config.MIN_FUNDING_RATE):.1f}% APY)")
    print(f"  Exit       : rate < {config.EXIT_FUNDING_RATE:.4%}/8h or negative")
    print(f"  Position   : ${config.POSITION_SIZE_USDC:.2f} USDC  "
          f"({config.MAX_POSITIONS} slots × ${config.POSITION_SIZE_USDC:.2f})")
    print(f"  Exchanges  : Binance · Bybit · OKX · Gate.io · Hyperliquid")
    print(f"  Compound   : {'ON' if config.COMPOUND_ENABLED else 'OFF'}  "
          f"(+10% per ${config.COMPOUND_THRESHOLD:.2f} earned)")
    print(f"  Spike alert: rate > {config.SPIKE_ALERT_RATE:.4%}/8h  "
          f"({config.rate_to_apy(config.SPIKE_ALERT_RATE):.0f}% APY)")
    print(f"  Daily goal : ${config.TARGET_DAILY_USDC:.2f}")
    est_daily = config.daily_income_est(config.MIN_FUNDING_RATE, config.MAX_TOTAL_USDC)
    print(f"  Est. daily : ${est_daily:.2f}  "
          f"(full cap at entry-threshold rate, ~{est_daily/config.MAX_TOTAL_USDC*100:.2f}%/day)")
    print(f"{'='*70}")

    # Print any configuration warnings before starting.
    for w in config.validate():
        print(f"  ⚠️  WARNING: {w}")
    print()

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

    scan_count    = 0
    _summary_date = datetime.now(timezone.utc).date()
    top_rates: list = []
    _cb_notified  = False  # latch: only send circuit-breaker Telegram once per trip
    _last_equity_snapshot = datetime.now(timezone.utc)
    _snapshot_equity(risk)  # baseline row at startup

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

            # Feed rate observations into the stability filter.
            for r in top_rates[:60]:
                risk.record_rate_observation(r.exchange, r.base, r.rate_8h)

            if no_ui and top_rates:
                log(
                    f"Top rate: {top_rates[0].exchange} {top_rates[0].base} "
                    f"{top_rates[0].rate_8h:.4%}/8h = {top_rates[0].apy:.1f}% APY"
                )

            # ── Spike alerts ──────────────────────────────────────────────────
            new_spikes = risk.check_spikes(top_rates)
            for spike in new_spikes:
                log(f"  ⚡ SPIKE ALERT: {spike}")
            for spike in new_spikes:
                notify.spike_alert(spike.exchange, spike.base, spike.rate_8h, spike.apy)

            # Snapshot once per scan to avoid redundant lock+copy calls.
            positions = risk.open_positions()
            open_ids  = {p.id for p in positions}

            # ── Position rotation ─────────────────────────────────────────────
            # If at capacity, swap out the weakest position for a meaningfully
            # better rate. MIN_HOLD_PERIODS prevents churning before breakeven.
            if config.ROTATION_ENABLED and len(positions) >= config.MAX_POSITIONS:
                worst = risk.worst_position()
                if worst and worst.funding_periods >= config.MIN_HOLD_PERIODS:
                    for cand in top_rates:
                        cand_id = f"{cand.exchange}:{cand.base}"
                        if (
                            not cand.perp_only
                            and cand_id not in open_ids
                            and cand.rate_8h >= worst.last_rate_8h * config.ROTATION_THRESHOLD
                        ):
                            log(
                                f"  ROTATION: {worst.id} ({worst.last_rate_8h:.4%}/8h) → "
                                f"{cand_id} ({cand.rate_8h:.4%}/8h)"
                            )
                            notify.rotation(
                                worst.base, worst.last_rate_8h,
                                cand.base, cand.rate_8h,
                            )
                            close_position(
                                worst, exchanges, risk,
                                live=config.LIVE_TRADING, reason="rotation",
                                use_maker=True,
                            )
                            risk.save_state()
                            positions = risk.open_positions()
                            open_ids  = {p.id for p in positions}
                            break  # one rotation per scan

            # ── Check exits on open positions ─────────────────────────────────
            for pos in positions:
                ex           = exchanges.get(pos.exchange)
                current_rate = fetch_current_funding_rate(ex, pos.perp_symbol) if ex else None
                should, reason = risk.should_exit(pos, current_rate)
                if should:
                    # Soft exits (rate decay) can use maker; hard exits (negative) market.
                    soft = "below exit" in reason or "Trailing" in reason
                    close_position(
                        pos, exchanges, risk,
                        live=config.LIVE_TRADING, reason=reason,
                        use_maker=soft,
                    )
                    risk.save_state()

            # ── Accrue funding ────────────────────────────────────────────────
            accrue_funding(positions, exchanges, risk)

            # ── Hedge drift check ─────────────────────────────────────────────
            check_hedge_drift(positions, exchanges, risk, live=config.LIVE_TRADING)

            # ── Margin health guard ───────────────────────────────────────────
            check_margin_health(positions, exchanges, risk, live=config.LIVE_TRADING)

            # Refresh snapshot after potential drift/margin-triggered closes.
            positions = risk.open_positions()
            open_ids  = {p.id for p in positions}

            # ── Open new positions ────────────────────────────────────────────
            if risk.circuit_breaker_open():
                log("  ⚡ CIRCUIT BREAKER: too many rate-flip exits — new entries paused")
                if not _cb_notified:
                    notify.circuit_breaker_alert(config.CIRCUIT_BREAKER_EXITS)
                    _cb_notified = True
            else:
                _cb_notified = False
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

            # ── Daily summary (midnight UTC) ──────────────────────────────────
            today = datetime.now(timezone.utc).date()
            if today != _summary_date:
                stats = risk.get_stats()
                notify.daily_summary(
                    earned_today   = risk.daily_earned(),
                    total_earned   = stats["total_funding_earned"],
                    open_positions = stats["open_positions"],
                    target         = config.TARGET_DAILY_USDC,
                )
                _summary_date = today

            # ── Equity curve snapshot (hourly) ────────────────────────────────
            now_utc = datetime.now(timezone.utc)
            if (now_utc - _last_equity_snapshot).total_seconds() >= config.EQUITY_SNAPSHOT_HOURS * 3600:
                _snapshot_equity(risk)
                _last_equity_snapshot = now_utc

            # Scan faster when below half capacity to catch new opportunities sooner.
            utilisation = len(positions) / max(config.MAX_POSITIONS, 1)
            sleep_secs  = (
                config.SCAN_INTERVAL_FAST
                if utilisation < config.FAST_SCAN_THRESHOLD
                else config.SCAN_INTERVAL
            )
            time.sleep(sleep_secs)

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
    parser.add_argument("--live",   action="store_true", help="Place real orders")
    parser.add_argument("--no-ui",  action="store_true", dest="no_ui",
                        help="Log mode, no dashboard")
    parser.add_argument("--report", action="store_true",
                        help="Print P&L report from trade journal and exit")
    args = parser.parse_args()
    if args.report:
        print_performance_report()
    else:
        run(live=args.live, no_ui=args.no_ui)
