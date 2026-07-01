"""
Paper-trading ledger — an HONEST simulation of the funding-arb bot.

The bot's built-in dry-run already accrues *gross* funding income using real
live funding rates, but it never subtracts the costs that eat that income in
the real world. This ledger fixes that: it tracks entry/exit fees, slippage,
and margin-borrow cost, then reports NET P&L so you can see what the strategy
would actually have made — not a fantasy top-line.

It persists to a JSON file so a month of running accumulates real data across
restarts. Nothing here ever touches an exchange or a private key.

Enable with PAPER_TRADING=true in your .env (implies dry-run — no real orders).
View the running ledger any time:  python paper.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

import config


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperLedger:
    """Tracks simulated net P&L with realistic costs, persisted to disk."""

    def __init__(self, path: str, starting_capital: float):
        self.path = path
        self.state: dict = {
            "starting_capital": starting_capital,
            "created_at": _utcnow_iso(),
            "gross_funding": 0.0,
            "entry_fees": 0.0,
            "exit_fees": 0.0,
            "slippage": 0.0,
            "margin_cost": 0.0,
            "trades_opened": 0,
            "trades_closed": 0,
            "would_be_liquidations": 0,
            "closed_trades": [],
            "open_positions": {},
        }
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    saved = json.load(f)
                # Preserve starting capital from first run; merge the rest.
                saved.setdefault("would_be_liquidations", 0)
                self.state.update(saved)
            except Exception as exc:
                print(f"[paper] Could not read ledger ({exc}); starting fresh.")

    def save(self) -> None:
        try:
            with open(self.path, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as exc:
            print(f"[paper] Could not write ledger: {exc}")

    # ── Cost model ────────────────────────────────────────────────────────────

    def _leg_cost(self, notional: float) -> tuple[float, float]:
        """
        Return (fee, slippage) for a single market leg on `notional` USDC.

        Two legs per side (spot + perp), so open and close are 2 legs each.
        """
        fee   = config.TAKER_FEE_PCT * notional
        slip  = getattr(config, "SIM_SLIPPAGE_PCT", 0.0003) * notional
        return fee, slip

    # ── Events ────────────────────────────────────────────────────────────────

    def record_open(self, pos) -> None:
        """Charge entry fees + slippage for both legs (spot + perp)."""
        half = pos.size_usdc / 2  # each leg is half the position notional
        entry_fee = entry_slip = 0.0
        for _ in range(2):  # spot leg + perp leg
            fee, slip = self._leg_cost(half)
            entry_fee  += fee
            entry_slip += slip

        self.state["entry_fees"] += entry_fee
        self.state["slippage"]   += entry_slip
        self.state["trades_opened"] += 1
        self.state["open_positions"][pos.id] = {
            "base": pos.base,
            "exchange": pos.exchange,
            "size_usdc": pos.size_usdc,
            "direction": pos.direction,
            "opened_at": _utcnow_iso(),
            "entry_cost": round(entry_fee + entry_slip, 6),
            "funding": 0.0,
        }
        self.save()

    def record_funding(self, pos_id: str, amount: float, direction: str = "long") -> None:
        """Credit a funding payment; for inverse shorts, net out margin borrow cost."""
        self.state["gross_funding"] += amount
        rec = self.state["open_positions"].get(pos_id)
        if rec:
            rec["funding"] = round(rec.get("funding", 0.0) + amount, 6)

        # Inverse (short-spot) positions pay margin interest each period.
        if direction == "short" and rec:
            # 8h period ≈ 1/3 of a day of borrow on the spot half.
            day_cost = config.MARGIN_INTEREST_RATE * (rec["size_usdc"] / 2)
            self.state["margin_cost"] += day_cost / 3
        self.save()

    def record_liquidation_risk(self, pos_id: str, margin_ratio: float) -> None:
        """Flag when a position drifted close enough to liquidation to matter."""
        self.state["would_be_liquidations"] += 1

    def record_close(self, pos, reason: str = "") -> None:
        """Charge exit fees + slippage and realise the trade."""
        half = pos.size_usdc / 2
        exit_fee = exit_slip = 0.0
        for _ in range(2):
            fee, slip = self._leg_cost(half)
            exit_fee  += fee
            exit_slip += slip

        self.state["exit_fees"] += exit_fee
        self.state["slippage"]  += exit_slip
        self.state["trades_closed"] += 1

        rec = self.state["open_positions"].pop(pos.id, {})
        funding = pos.funding_collected if pos.funding_collected else rec.get("funding", 0.0)
        entry_cost = rec.get("entry_cost", 0.0)
        net = funding - entry_cost - (exit_fee + exit_slip)

        self.state["closed_trades"].append({
            "id": pos.id,
            "base": pos.base,
            "direction": pos.direction,
            "size_usdc": pos.size_usdc,
            "funding_collected": round(funding, 6),
            "total_cost": round(entry_cost + exit_fee + exit_slip, 6),
            "net_pnl": round(net, 6),
            "reason": reason,
            "closed_at": _utcnow_iso(),
        })
        self.save()

    # ── Reporting ─────────────────────────────────────────────────────────────

    def net_pnl(self) -> float:
        s = self.state
        return (
            s["gross_funding"]
            - s["entry_fees"]
            - s["exit_fees"]
            - s["slippage"]
            - s["margin_cost"]
        )

    def snapshot(self) -> dict:
        s = self.state
        total_costs = s["entry_fees"] + s["exit_fees"] + s["slippage"] + s["margin_cost"]
        net = self.net_pnl()
        cap = s["starting_capital"] or 1.0

        # Annualise from elapsed wall-clock since the ledger began.
        try:
            started = datetime.fromisoformat(s["created_at"])
            days = max((datetime.now(timezone.utc) - started).total_seconds() / 86400, 0.01)
        except Exception:
            days = 0.01
        roi = net / cap
        apy = (roi / days) * 365 * 100

        closed = s["closed_trades"]
        wins = sum(1 for t in closed if t["net_pnl"] > 0)
        return {
            "starting_capital": cap,
            "elapsed_days": round(days, 2),
            "gross_funding": s["gross_funding"],
            "total_costs": total_costs,
            "entry_fees": s["entry_fees"],
            "exit_fees": s["exit_fees"],
            "slippage": s["slippage"],
            "margin_cost": s["margin_cost"],
            "net_pnl": net,
            "roi_pct": roi * 100,
            "annualised_pct": apy,
            "trades_opened": s["trades_opened"],
            "trades_closed": s["trades_closed"],
            "open_now": len(s["open_positions"]),
            "wins": wins,
            "win_rate_pct": (wins / len(closed) * 100) if closed else 0.0,
            "would_be_liquidations": s["would_be_liquidations"],
        }

    def summary(self) -> str:
        s = self.snapshot()
        cap = s["starting_capital"]
        # Project the 6-month figure the user keeps asking about, honestly.
        six_month = cap * (s["annualised_pct"] / 100) / 2

        lines = [
            "",
            "═" * 66,
            "  PAPER TRADING LEDGER  (simulation — no real money moved)",
            "═" * 66,
            f"  Starting capital     : ${cap:,.2f}",
            f"  Running for          : {s['elapsed_days']} days",
            "",
            f"  Gross funding income : ${s['gross_funding']:+,.4f}",
            f"  – entry fees         : ${s['entry_fees']:,.4f}",
            f"  – exit fees          : ${s['exit_fees']:,.4f}",
            f"  – slippage           : ${s['slippage']:,.4f}",
            f"  – margin borrow cost : ${s['margin_cost']:,.4f}",
            "  " + "-" * 40,
            f"  NET P&L              : ${s['net_pnl']:+,.4f}",
            f"  Return on capital    : {s['roi_pct']:+.3f}%",
            f"  Annualised (est.)    : {s['annualised_pct']:+.1f}%",
            "",
            f"  Trades opened/closed : {s['trades_opened']} / {s['trades_closed']}",
            f"  Win rate             : {s['win_rate_pct']:.0f}%  ({s['wins']} wins)",
            f"  Open right now       : {s['open_now']}",
        ]
        if s["would_be_liquidations"]:
            lines.append(
                f"  ⚠ LIQUIDATION FLAGS  : {s['would_be_liquidations']} "
                f"(positions that drifted dangerously close to liquidation)"
            )
        lines += [
            "",
            f"  → Projected 6-month at this rate: ${six_month:+,.2f} on ${cap:,.0f}",
            "",
            "  NOTE: This models fees, slippage and margin cost, but assumes both",
            "  legs always fill and stay hedged. Real runs also face failed fills,",
            "  transfer lag, and liquidation cascades — none of which appear here.",
            "  Treat this as a best-case ceiling, not a guarantee.",
            "═" * 66,
            "",
        ]
        return "\n".join(lines)


# ── Module-level singleton ─────────────────────────────────────────────────────

_ledger: Optional[PaperLedger] = None


def get_ledger() -> PaperLedger:
    global _ledger
    if _ledger is None:
        path = getattr(config, "PAPER_LEDGER_PATH", "paper_ledger.json")
        cap  = getattr(config, "PAPER_STARTING_CAPITAL", config.MAX_TOTAL_USDC)
        _ledger = PaperLedger(path, cap)
    return _ledger


if __name__ == "__main__":
    print(get_ledger().summary())
