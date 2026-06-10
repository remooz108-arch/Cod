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
from collections import deque
from datetime import datetime, date, timedelta, timezone
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
        "peak_rate_8h":      pos.peak_rate_8h,
        "entry_note":        pos.entry_note,
        "spot_order_id":     pos.spot_order_id,
        "perp_order_id":     pos.perp_order_id,
        "last_period_at":    pos.last_period_at.isoformat() if pos.last_period_at else None,
        "direction":         pos.direction,
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
        peak_rate_8h     = float(d.get("peak_rate_8h", d.get("last_rate_8h", 0))),
        entry_note       = d.get("entry_note", ""),
        spot_order_id    = d.get("spot_order_id"),
        perp_order_id    = d.get("perp_order_id"),
        last_period_at   = _parse_dt(d.get("last_period_at")),
        direction        = d.get("direction", "long"),
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

        # Rate stability tracking: rolling window of recent rate observations
        self._rate_history: dict[str, deque] = {}

        # Circuit breaker: timestamps of exits caused by rate flips
        self._flip_exit_times: list[datetime] = []

        # Cooldown guard: {exchange:base -> datetime re-entry is allowed again}
        self._cooldowns: dict[str, datetime] = {}

        # Sector map for concentration checks (built once from config at init)
        self._sector_map: dict[str, str] = {
            base: sector
            for sector, bases in config.SECTOR_CLUSTERS.items()
            for base in bases
        }

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

    # ── Rate stability ────────────────────────────────────────────────────────

    def record_rate_observation(self, exchange: str, base: str, rate: float) -> None:
        """Store the latest rate reading for the stability and consistency filters."""
        with self._lock:
            key = f"{exchange}:{base}"
            if key not in self._rate_history:
                window = max(config.RATE_HISTORY_SAMPLES, config.RATE_STABILITY_SCANS + 1, 2)
                self._rate_history[key] = deque(maxlen=window)
            self._rate_history[key].append(rate)

    def is_rate_stable(self, exchange: str, base: str, direction: str = "long") -> bool:
        """True if the last RATE_STABILITY_SCANS observations all clear the entry threshold."""
        if not config.RATE_STABILITY_ENABLED:
            return True
        with self._lock:
            hist = self._rate_history.get(f"{exchange}:{base}")
            if not hist or len(hist) < config.RATE_STABILITY_SCANS:
                return False
            recent = list(hist)[-config.RATE_STABILITY_SCANS:]
            if direction == "short":
                return all(r <= -config.MIN_NEGATIVE_FUNDING_RATE for r in recent)
            return all(r >= config.MIN_FUNDING_RATE for r in recent)

    def rate_stats(self, exchange: str, base: str) -> tuple[float, float, int]:
        """Return (mean, std, count) of the rolling rate history for an asset."""
        with self._lock:
            hist = self._rate_history.get(f"{exchange}:{base}")
            if not hist:
                return 0.0, 0.0, 0
            data = list(hist)
            n    = len(data)
            mean = sum(data) / n
            var  = sum((r - mean) ** 2 for r in data) / n if n > 1 else 0.0
            return mean, var ** 0.5, n

    def is_rate_consistent(self, exchange: str, base: str) -> tuple[bool, str]:
        """
        True if the AVERAGE rate clears MIN_FUNDING_RATE and the rate is steady
        (coefficient of variation below MAX_RATE_CV). Filters out flickering
        rates that look good on a single reading but average out poorly.
        """
        if not config.RATE_CV_FILTER_ENABLED:
            return True, "OK"
        mean, std, n = self.rate_stats(exchange, base)
        # Need a meaningful sample before judging consistency.
        if n < config.RATE_STABILITY_SCANS:
            return False, f"only {n} samples (need {config.RATE_STABILITY_SCANS})"
        if mean < config.MIN_FUNDING_RATE:
            return False, f"avg {mean:.4%} < {config.MIN_FUNDING_RATE:.4%} floor"
        cv = (std / mean) if mean > 0 else float("inf")
        if cv > config.MAX_RATE_CV:
            return False, f"volatile (CV {cv:.2f} > {config.MAX_RATE_CV:.2f})"
        return True, "OK"

    def rate_momentum(self, exchange: str, base: str) -> float:
        """
        Normalised rate change across the observation window.
        Returns (last − first) / first, clamped to [-1, +∞).
        0.0 when insufficient data. Positive = rising, negative = falling.
        """
        with self._lock:
            hist = self._rate_history.get(f"{exchange}:{base}")
            if not hist or len(hist) < 3:
                return 0.0
            data  = list(hist)
            first = data[0]
            if first <= 0:
                return 0.0
            return (data[-1] - first) / first

    # ── Cooldown guard ────────────────────────────────────────────────────────

    def start_cooldown(self, exchange: str, base: str, direction: str = "long") -> None:
        """Block re-entry on the same side for COOLDOWN_HOURS after an exit."""
        if not config.COOLDOWN_ENABLED or config.COOLDOWN_HOURS <= 0:
            return
        with self._lock:
            self._cooldowns[f"{exchange}:{base}:{direction}"] = (
                _utcnow() + timedelta(hours=config.COOLDOWN_HOURS)
            )

    def in_cooldown(self, exchange: str, base: str, direction: str = "long") -> tuple[bool, float]:
        """Return (is_cooling_down, minutes_remaining). Direction-aware."""
        if not config.COOLDOWN_ENABLED:
            return False, 0.0
        with self._lock:
            key   = f"{exchange}:{base}:{direction}"
            until = self._cooldowns.get(key)
            # Support old-format keys (no direction suffix) written by pre-upgrade state.
            # Only apply the bare key to "long" queries — inverse arb must never be blocked
            # by a cooldown that was recorded for a long position.
            if until is None and direction == "long":
                until = self._cooldowns.get(f"{exchange}:{base}")
            if until is None:
                return False, 0.0
            now = _utcnow()
            if now >= until:
                self._cooldowns.pop(key, None)
                return False, 0.0
            return True, (until - now).total_seconds() / 60.0

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def record_flip_exit(self) -> None:
        """Call when a position exits because its rate went negative or below threshold."""
        with self._lock:
            now = _utcnow()
            self._flip_exit_times.append(now)
            cutoff = now - timedelta(hours=1)
            self._flip_exit_times = [t for t in self._flip_exit_times if t > cutoff]

    def circuit_breaker_open(self) -> bool:
        """True if too many rate-flip exits happened in the last hour."""
        if not config.CIRCUIT_BREAKER_ENABLED:
            return False
        with self._lock:
            cutoff = _utcnow() - timedelta(hours=1)
            recent = sum(1 for t in self._flip_exit_times if t > cutoff)
            return recent >= config.CIRCUIT_BREAKER_EXITS

    # ── Gate ──────────────────────────────────────────────────────────────────

    def can_open(
        self, exchange: str, base: str,
        size_override: Optional[float] = None,
        direction: str = "long",
    ) -> tuple[bool, str]:
        with self._lock:
            pid = f"{exchange}:{base}"
            if pid in self._positions:
                return False, f"Already have {pid} open"
            cooling, mins = self.in_cooldown(exchange, base, direction)
            if cooling:
                return False, f"Cooldown: {base} re-entry blocked {mins:.0f}m more"
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
            # Per-asset cap: diversify across coins, not just exchanges.
            max_per_asset  = config.MAX_TOTAL_USDC * config.MAX_ASSET_FRACTION
            asset_deployed = sum(
                p.size_usdc for p in self._positions.values() if p.base == base
            )
            if asset_deployed + size > max_per_asset:
                return False, (
                    f"Asset cap: ${asset_deployed:.0f} in {base} "
                    f"+ ${size:.0f} > ${max_per_asset:.0f} "
                    f"({config.MAX_ASSET_FRACTION:.0%} limit)"
                )
            # Sector cap: cap exposure to any one narrative cluster.
            if config.MAX_SECTOR_POSITIONS > 0:
                sector = self._sector_map.get(base)
                if sector:
                    sc = sum(
                        1 for p in self._positions.values()
                        if self._sector_map.get(p.base) == sector
                    )
                    if sc >= config.MAX_SECTOR_POSITIONS:
                        return False, (
                            f"Sector cap: {sc}/{config.MAX_SECTOR_POSITIONS} "
                            f"positions already in '{sector}' cluster"
                        )
            return True, "OK"

    def should_exit(
        self, pos: Position, current_rate: Optional[float]
    ) -> tuple[bool, str]:
        if pos.direction == "short":
            # Inverse position: collecting negative funding. Exit when rate normalises.
            if current_rate is not None and current_rate >= 0:
                return True, f"Rate went positive ({current_rate:.4%}) — inverse exits"
            if current_rate is not None and current_rate > -config.EXIT_FUNDING_RATE:
                return True, (
                    f"Rate {current_rate:.4%} no longer sufficiently negative "
                    f"(exit threshold {-config.EXIT_FUNDING_RATE:.4%})"
                )
            if (
                config.TRAILING_RATE_STOP > 0
                and pos.peak_rate_8h < 0
                and current_rate is not None
            ):
                # Recovery = how far rate has moved from most-negative toward zero
                recovery = (current_rate - pos.peak_rate_8h) / abs(pos.peak_rate_8h)
                if recovery >= config.TRAILING_RATE_STOP:
                    return True, (
                        f"Trailing stop: rate recovered {recovery:.0%} from peak "
                        f"({pos.peak_rate_8h:.4%} → {current_rate:.4%}/8h)"
                    )
            return False, ""

        # Normal (positive funding) position
        if current_rate is not None and current_rate < 0:
            return True, f"Rate went negative ({current_rate:.4%})"
        if current_rate is not None and current_rate < config.EXIT_FUNDING_RATE:
            return True, (
                f"Rate {current_rate:.4%} below exit "
                f"threshold {config.EXIT_FUNDING_RATE:.4%}"
            )
        if (
            config.TRAILING_RATE_STOP > 0
            and pos.peak_rate_8h > 0
            and current_rate is not None
        ):
            drop = (pos.peak_rate_8h - current_rate) / pos.peak_rate_8h
            if drop >= config.TRAILING_RATE_STOP:
                return True, (
                    f"Trailing stop: rate dropped {drop:.0%} from peak "
                    f"({pos.peak_rate_8h:.4%} → {current_rate:.4%}/8h)"
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
                p = self._positions[pos_id]
                p.last_rate_8h = rate
                if p.direction == "short":
                    # Inverse position: track the most-negative rate (most favourable)
                    if rate < p.peak_rate_8h:
                        p.peak_rate_8h = rate
                else:
                    if rate > p.peak_rate_8h:
                        p.peak_rate_8h = rate

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
                if p.direction == "short":
                    if rate < p.peak_rate_8h:
                        p.peak_rate_8h    = rate
                else:
                    if rate > p.peak_rate_8h:
                        p.peak_rate_8h    = rate
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
                "cooldowns": {
                    k: v.isoformat() for k, v in self._cooldowns.items()
                },
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
                now = _utcnow()
                for k, iso in state.get("cooldowns", {}).items():
                    try:
                        dt = datetime.fromisoformat(iso)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt > now:  # drop already-expired cooldowns
                            self._cooldowns[k] = dt
                    except (ValueError, TypeError):
                        continue
            return len(state.get("positions", []))
        except Exception as exc:
            print(f"  [warn] state load failed: {exc}")
            return 0
