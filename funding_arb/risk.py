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
"""

from __future__ import annotations

import threading
from datetime import datetime, date, timezone
from typing import Optional

import config
from models import Position, DailyStats, RateSpike


class RiskManager:
    def __init__(self):
        self._lock = threading.RLock()  # reentrant: get_stats() calls several sub-methods
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
        self._spike_seen: set[str] = set()   # reset daily

    # ── Daily reset ───────────────────────────────────────────────────────────

    def _maybe_reset_daily(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._today:
            self._daily_history.append(DailyStats(
                date=self._today,
                funding_earned=self._daily_earned,
                positions_opened=self._daily_opened,
                positions_closed=self._daily_closed,
            ))
            self._daily_earned   = 0.0
            self._daily_opened   = 0
            self._daily_closed   = 0
            self._spike_seen     = set()
            self._today          = today

    # ── Internal helper ───────────────────────────────────────────────────────

    def _compound_steps(self) -> int:
        if config.COMPOUND_THRESHOLD <= 0:
            return 0
        return int(self._total_funding_earned / config.COMPOUND_THRESHOLD)

    # ── Compound sizing ───────────────────────────────────────────────────────

    def effective_position_size(self) -> float:
        """Position size grows 10% for each COMPOUND_THRESHOLD earned.
        Cap at MAX_TOTAL_USDC so a single position never exceeds total capital.
        can_open() enforces the hard capital check; this just controls sizing."""
        if not config.COMPOUND_ENABLED or config.COMPOUND_THRESHOLD <= 0:
            return config.POSITION_SIZE_USDC
        raw = config.POSITION_SIZE_USDC * (1.10 ** self._compound_steps())
        return min(raw, config.MAX_TOTAL_USDC)

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
                            exchange=r.exchange,
                            base=r.base,
                            rate_8h=r.rate_8h,
                            apy=r.apy,
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
            size = size_override if size_override is not None else self.effective_position_size()
            deployed = self.total_deployed()
            if deployed + size > config.MAX_TOTAL_USDC:
                return False, (
                    f"Capital cap: ${deployed:.0f} + ${size:.0f} "
                    f"> ${config.MAX_TOTAL_USDC:.0f}"
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

    def record_funding(self, pos_id: str, amount: float, rate: float) -> None:
        with self._lock:
            self._maybe_reset_daily()
            if pos_id in self._positions:
                p = self._positions[pos_id]
                p.funding_collected += amount
                p.funding_periods   += 1
                p.last_rate_8h       = rate
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
            positions = list(self._positions.values())
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
