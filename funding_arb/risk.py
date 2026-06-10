"""
Risk management for the funding arb bot.

Rules:
  - Max simultaneous positions: MAX_POSITIONS
  - Max total capital deployed: MAX_TOTAL_USDC
  - Exit immediately if funding rate flips negative
  - Never enter the same (exchange, base) twice
  - Auto-compound: position size grows 10% for every COMPOUND_THRESHOLD earned
  - Spike detection: alert when any rate exceeds SPIKE_ALERT_RATE
  - Daily stats reset at UTC midnight
  - State persisted to JSON so the bot recovers gracefully after a restart
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, date, timezone
from typing import Optional

import config
from models import Position, DailyStats, RateSpike, _utcnow


def _pos_to_dict(pos: Position) -> dict:
    return {
        "id":                pos.id,
        "exchange":          pos.exchange,
        "base":              pos.base,
        "spot_symbol":       pos.spot_symbol,
        "perp_symbol":       pos.perp_symbol,
        "spot_exchange":     pos.spot_exchange,
        "spot_qty":          pos.spot_qty,
        "perp_qty":          pos.perp_qty,
        "entry_spot_price":  pos.entry_spot_price,
        "entry_perp_price":  pos.entry_perp_price,
        "size_usdc":         pos.size_usdc,
        "opened_at":         pos.opened_at.isoformat(),
        "funding_collected": pos.funding_collected,
        "funding_periods":   pos.funding_periods,
        "last_rate_8h":      pos.last_rate_8h,
        "spot_order_id":     pos.spot_order_id,
        "perp_order_id":     pos.perp_order_id,
        "last_period_at":    pos.last_period_at.isoformat() if pos.last_period_at else None,
    }


def _pos_from_dict(d: dict) -> Position:
    def _parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    return Position(
        id               = d["id"],
        exchange         = d["exchange"],
        base             = d["base"],
        spot_symbol      = d["spot_symbol"],
        perp_symbol      = d["perp_symbol"],
        spot_exchange    = d.get("spot_exchange", d["exchange"]),
        spot_qty         = float(d["spot_qty"]),
        perp_qty         = float(d["perp_qty"]),
        entry_spot_price = float(d["entry_spot_price"]),
        entry_perp_price = float(d["entry_perp_price"]),
        size_usdc        = float(d["size_usdc"]),
        opened_at        = _parse_dt(d["opened_at"]),
        funding_collected= float(d.get("funding_collected", 0)),
        funding_periods  = int(d.get("funding_periods", 0)),
        last_rate_8h     = float(d.get("last_rate_8h", 0)),
        spot_order_id    = d.get("spot_order_id"),
        perp_order_id    = d.get("perp_order_id"),
        last_period_at   = _parse_dt(d.get("last_period_at")),
    )


class RiskManager:
    def __init__(self):
        self._lock = threading.RLock()  # reentrant: get_stats() calls helper methods
        self._positions: dict[str, Position] = {}
        self._closed_positions: list[Position] = []
        self._total_funding_earned: float = 0.0

        # Daily tracking
        self._today: date = datetime.now(timezone.utc).date()
        self._daily_earned: float = 0.0
        self._daily_history: list[DailyStats] = []
        self._daily_opened: int = 0
        self._daily_closed: int = 0

        # Spike tracking
        self._recent_spikes: list[RateSpike] = []
        self._spike_seen: set[str] = set()

    # ── Daily reset ───────────────────────────────────────────────────────────

    def _maybe_reset_daily(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._today:
            self._daily_history.append(DailyStats(
                date             = self._today,
                funding_earned   = self._daily_earned,
                positions_opened = self._daily_opened,
                positions_closed = self._daily_closed,
            ))
            self._daily_earned  = 0.0
            self._daily_opened  = 0
            self._daily_closed  = 0
            self._spike_seen    = set()
            self._today         = today

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compound_steps(self) -> int:
        if config.COMPOUND_THRESHOLD <= 0:
            return 0
        return int(self._total_funding_earned / config.COMPOUND_THRESHOLD)

    # ── Compound sizing ───────────────────────────────────────────────────────

    def effective_position_size(self) -> float:
        """Position size grows 10% for each COMPOUND_THRESHOLD earned.

        Capped at MAX_TOTAL_USDC / 3 so at minimum 3 positions can always
        coexist even at maximum compound. can_open() enforces the total
        capital hard cap independently.
        """
        if not config.COMPOUND_ENABLED or config.COMPOUND_THRESHOLD <= 0:
            return config.POSITION_SIZE_USDC
        raw = config.POSITION_SIZE_USDC * (1.10 ** self._compound_steps())
        return min(raw, config.MAX_TOTAL_USDC / 3)

    def compound_progress(self) -> tuple[float, float]:
        """(earned_in_current_cycle, threshold) for progress display."""
        if config.COMPOUND_THRESHOLD <= 0:
            return 0.0, 0.0
        cycle = self._total_funding_earned % config.COMPOUND_THRESHOLD
        return cycle, config.COMPOUND_THRESHOLD

    def compound_step(self) -> int:
        return self._compound_steps()

    # ── Spike detection ───────────────────────────────────────────────────────

    def check_spikes(self, rates: list) -> list[RateSpike]:
        """Return newly detected spikes (not seen since last daily reset)."""
        new: list[RateSpike] = []
        with self._lock:
            self._maybe_reset_daily()
            for r in rates:
                if r.rate_8h >= config.SPIKE_ALERT_RATE:
                    key = f"{r.exchange}:{r.base}"
                    if key not in self._spike_seen:
                        self._spike_seen.add(key)
                        spike = RateSpike(
                            exchange = r.exchange,
                            base     = r.base,
                            rate_8h  = r.rate_8h,
                            apy      = r.apy,
                        )
                        self._recent_spikes.append(spike)
                        self._recent_spikes = self._recent_spikes[-10:]
                        new.append(spike)
        return new

    # ── Gate ──────────────────────────────────────────────────────────────────

    def can_open(
        self, exchange: str, base: str, size_override: Optional[float] = None
    ) -> tuple[bool, str]:
        with self._lock:
            pid = f"{exchange}:{base}"
            if pid in self._positions:
                return False, f"Already have {pid} open"
            if len(self._positions) >= config.MAX_POSITIONS:
                return False, f"Max positions ({config.MAX_POSITIONS}) reached"
            size     = size_override if size_override is not None else self.effective_position_size()
            deployed = sum(p.size_usdc for p in self._positions.values())
            if deployed + size > config.MAX_TOTAL_USDC:
                return False, (
                    f"Capital cap: ${deployed:.0f} + ${size:.0f} "
                    f"> ${config.MAX_TOTAL_USDC:.0f}"
                )
            max_per_ex = config.MAX_TOTAL_USDC * config.MAX_EXCHANGE_FRACTION
            ex_deployed = sum(
                p.size_usdc for p in self._positions.values()
                if p.exchange == exchange
            )
            if ex_deployed + size > max_per_ex:
                return False, (
                    f"Exchange cap: ${ex_deployed:.0f} on {exchange} "
                    f"+ ${size:.0f} > ${max_per_ex:.0f} (50% limit)"
                )
            return True, "OK"

    def should_exit(
        self, pos: Position, current_rate: Optional[float]
    ) -> tuple[bool, str]:
        if current_rate is not None and current_rate < 0:
            return True, f"Rate went negative ({current_rate:.4%})"
        if current_rate is not None and current_rate < config.EXIT_FUNDING_RATE:
            return True, (
                f"Rate {current_rate:.4%} below exit "
                f"threshold {config.EXIT_FUNDING_RATE:.4%}"
            )
        return False, ""

    # ── Position lifecycle ────────────────────────────────────────────────────

    def record_open(self, pos: Position) -> None:
        with self._lock:
            self._maybe_reset_daily()
            self._positions[pos.id] = pos
            self._daily_opened += 1

    def update_rate(self, pos_id: str, rate: float) -> None:
        """Update last_rate_8h for display; does NOT count a funding period."""
        with self._lock:
            if pos_id in self._positions:
                self._positions[pos_id].last_rate_8h = rate

    def record_funding(
        self, pos_id: str, amount: float, rate: float, period_at: Optional[datetime] = None
    ) -> None:
        """Record one completed 8-hour funding period."""
        with self._lock:
            self._maybe_reset_daily()
            if pos_id in self._positions:
                p = self._positions[pos_id]
                p.funding_collected      += amount
                p.funding_periods        += 1
                p.last_rate_8h            = rate
                if period_at is not None:
                    p.last_period_at      = period_at
                self._total_funding_earned += amount
                self._daily_earned         += amount

    def record_close(self, pos_id: str) -> Optional[Position]:
        with self._lock:
            self._maybe_reset_daily()
            pos = self._positions.pop(pos_id, None)
            if pos:
                self._closed_positions.append(pos)
                self._daily_closed += 1
        return pos

    # ── Stats ─────────────────────────────────────────────────────────────────

    def open_positions(self) -> list[Position]:
        with self._lock:
            return list(self._positions.values())

    def total_deployed(self) -> float:
        with self._lock:
            return sum(p.size_usdc for p in self._positions.values())

    def total_funding_earned(self) -> float:
        with self._lock:
            return self._total_funding_earned

    def daily_earned(self) -> float:
        with self._lock:
            self._maybe_reset_daily()
            return self._daily_earned

    def recent_spikes(self) -> list[RateSpike]:
        with self._lock:
            return list(self._recent_spikes)

    def total_pnl(self) -> float:
        with self._lock:
            return self._total_funding_earned

    def get_stats(self) -> dict:
        with self._lock:
            self._maybe_reset_daily()
            positions  = list(self._positions.values())
            cycle, threshold = self.compound_progress()
            return {
                "open_positions":          len(positions),
                "total_deployed":          sum(p.size_usdc for p in positions),
                "total_funding_earned":    self._total_funding_earned,
                "daily_earned":            self._daily_earned,
                "closed_positions":        len(self._closed_positions),
                "avg_apy": (
                    sum(p.apy_realised for p in positions) / len(positions)
                    if positions else 0.0
                ),
                "effective_position_size": self.effective_position_size(),
                "compound_step":           self.compound_step(),
                "compound_progress":       cycle,
                "compound_threshold":      threshold,
                "recent_spikes":           list(self._recent_spikes[-3:]),
            }

    def worst_position(self) -> Optional[Position]:
        """Return the open position with the lowest current funding rate."""
        with self._lock:
            if not self._positions:
                return None
            return min(self._positions.values(), key=lambda p: p.last_rate_8h)

    def exchange_deployed(self, exchange: str) -> float:
        """Total USDC deployed on a specific exchange."""
        with self._lock:
            return sum(
                p.size_usdc for p in self._positions.values()
                if p.exchange == exchange
            )

    # ── State persistence ─────────────────────────────────────────────────────

    def save_state(self, path: str = "") -> None:
        """Atomically write open positions to disk (rename from temp file)."""
        path = path or config.STATE_FILE
        with self._lock:
            state = {
                "total_funding_earned": self._total_funding_earned,
                "positions": [_pos_to_dict(p) for p in self._positions.values()],
            }
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(state, fh, indent=2)
            os.replace(tmp, path)
        except Exception as exc:
            print(f"  [warn] state save failed: {exc}")

    def load_state(self, path: str = "") -> int:
        """Load persisted positions. Returns number of positions restored."""
        path = path or config.STATE_FILE
        if not os.path.exists(path):
            return 0
        try:
            with open(path) as fh:
                state = json.load(fh)
            with self._lock:
                self._total_funding_earned = float(state.get("total_funding_earned", 0))
                for d in state.get("positions", []):
                    pos = _pos_from_dict(d)
                    self._positions[pos.id] = pos
            return len(state.get("positions", []))
        except Exception as exc:
            print(f"  [warn] state load failed: {exc}")
            return 0
