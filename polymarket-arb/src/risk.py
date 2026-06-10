"""
Risk manager: position limits, daily loss, failure cooldowns, single-leg tracking.
All state lives in memory — resets on restart (as designed: don't persist live positions).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .config import Config
from .models import Opportunity, Trade

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, config: Config):
        self._cfg = config

        # Capital tracking
        self._total_deployed: float = 0.0
        self._daily_pnl: float = 0.0
        self._total_pnl: float = 0.0

        # Position tracking
        self._open_positions: dict[str, Trade] = {}   # condition_id → Trade
        self._single_leg_warnings: list[Trade] = []

        # Failure tracking
        self._failure_streak: int = 0
        self._cooldown_until: float = 0.0

        # Stats
        self._total_trades: int = 0
        self._filled_trades: int = 0
        self._dry_run_trades: int = 0

    # ── Trade gate ────────────────────────────────────────────────────────────

    def can_trade(self, opportunity: Opportunity) -> tuple[bool, str]:
        now = time.monotonic()

        if now < self._cooldown_until:
            remaining = int(self._cooldown_until - now)
            return False, f"Cooldown active — {remaining}s remaining after failure streak"

        new_total = self._total_deployed + self._cfg.max_position_usdc
        if new_total > self._cfg.max_total_deployed_usdc:
            return False, (
                f"Capital limit: deployed=${self._total_deployed:.2f} + "
                f"new=${self._cfg.max_position_usdc:.2f} > "
                f"max=${self._cfg.max_total_deployed_usdc:.2f}"
            )

        if self._daily_pnl < -self._cfg.daily_loss_limit_usdc:
            return False, (
                f"Daily loss limit reached: ${self._daily_pnl:.2f} < "
                f"-${self._cfg.daily_loss_limit_usdc:.2f}"
            )

        cid = opportunity.market.condition_id
        if cid in self._open_positions:
            return False, f"Already have an open position on {cid[:16]}..."

        return True, "OK"

    # ── Trade recording ───────────────────────────────────────────────────────

    def record_trade(self, trade: Trade) -> None:
        self._total_trades += 1

        if trade.status == "dry_run":
            self._dry_run_trades += 1
            return

        if trade.status == "filled":
            self._filled_trades += 1
            self._total_deployed += trade.size_usdc
            self._open_positions[trade.opportunity.market.condition_id] = trade
            self._failure_streak = 0

        elif trade.status == "partial":
            # YES filled, NO failed — single-leg exposure
            self._single_leg_warnings.append(trade)
            self._total_deployed += trade.size_usdc
            self._failure_streak += 1
            logger.critical(
                "SINGLE-LEG EXPOSURE DETECTED!\n"
                f"  Market  : {trade.opportunity.market.question}\n"
                f"  YES ID  : {trade.yes_order_id}\n"
                f"  YES fill: ${trade.yes_fill_price:.4f}\n"
                "  NO order FAILED — this is now a directional position, not arb.\n"
                "  Review and hedge manually via the Polymarket UI."
            )
            self._maybe_cooldown()

        elif trade.status == "failed":
            self._failure_streak += 1
            self._maybe_cooldown()

    def close_position(self, condition_id: str, resolved_pnl: float) -> None:
        """Call when a market resolves and our position is closed."""
        trade = self._open_positions.pop(condition_id, None)
        if trade is None:
            return
        self._total_deployed = max(0.0, self._total_deployed - trade.size_usdc)
        self._daily_pnl += resolved_pnl
        self._total_pnl += resolved_pnl
        logger.info(
            f"Position closed: {trade.opportunity.market.question[:50]} | "
            f"P&L: ${resolved_pnl:+.2f}"
        )

    def record_failure(self) -> None:
        self._failure_streak += 1
        self._maybe_cooldown()

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_total_deployed(self) -> float:
        return self._total_deployed

    def get_daily_pnl(self) -> float:
        return self._daily_pnl

    def get_total_pnl(self) -> float:
        return self._total_pnl

    def get_open_positions(self) -> dict[str, Trade]:
        return dict(self._open_positions)

    def get_single_leg_warnings(self) -> list[Trade]:
        return list(self._single_leg_warnings)

    def get_fill_rate(self) -> float:
        live = self._total_trades - self._dry_run_trades
        if live == 0:
            return 1.0
        return self._filled_trades / live

    def get_stats(self) -> dict:
        return {
            "total_deployed": self._total_deployed,
            "daily_pnl": self._daily_pnl,
            "total_pnl": self._total_pnl,
            "open_positions": len(self._open_positions),
            "single_leg_warnings": len(self._single_leg_warnings),
            "fill_rate": self.get_fill_rate(),
            "total_trades": self._total_trades,
            "filled_trades": self._filled_trades,
        }

    # ── Async background tasks ────────────────────────────────────────────────

    async def daily_reset_loop(self) -> None:
        """Sleep until UTC midnight, then reset daily counters. Repeat."""
        while True:
            now = datetime.now(timezone.utc)
            seconds_to_midnight = (
                (23 - now.hour) * 3600
                + (59 - now.minute) * 60
                + (60 - now.second)
            )
            await asyncio.sleep(seconds_to_midnight)
            self.reset_daily()

    def reset_daily(self) -> None:
        logger.info(f"Daily reset — yesterday P&L: ${self._daily_pnl:+.2f}")
        self._daily_pnl = 0.0

    # ── Private ───────────────────────────────────────────────────────────────

    def _maybe_cooldown(self) -> None:
        if self._failure_streak >= 3:
            self._cooldown_until = time.monotonic() + self._cfg.cooldown_after_failures
            logger.warning(
                f"3 consecutive failures — pausing {self._cfg.cooldown_after_failures}s"
            )
            self._failure_streak = 0
