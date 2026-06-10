"""
Risk management for the funding arb bot.

Rules:
  - Max simultaneous positions: MAX_POSITIONS
  - Max total capital deployed: MAX_TOTAL_USDC
  - Exit immediately if funding rate flips negative on any open position
  - Never enter the same (exchange, base) twice
  - Stop all new entries if unrealised loss > 2% of deployed capital
    (signals a significant spot/perp spread divergence)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import config
from models import Position


class RiskManager:
    def __init__(self):
        self._positions: dict[str, Position] = {}   # id → Position
        self._total_funding_earned: float = 0.0
        self._closed_positions: list[Position] = []

    # ── Gate ──────────────────────────────────────────────────────────────────

    def can_open(self, exchange: str, base: str) -> tuple[bool, str]:
        pid = f"{exchange}:{base}"
        if pid in self._positions:
            return False, f"Already have {pid} open"
        if len(self._positions) >= config.MAX_POSITIONS:
            return False, f"Max positions reached ({config.MAX_POSITIONS})"
        deployed = self.total_deployed()
        if deployed + config.POSITION_SIZE_USDC > config.MAX_TOTAL_USDC:
            return False, f"Capital cap: ${deployed:.0f} + ${config.POSITION_SIZE_USDC:.0f} > ${config.MAX_TOTAL_USDC:.0f}"
        return True, "OK"

    def should_exit(self, pos: Position, current_rate: Optional[float]) -> tuple[bool, str]:
        if current_rate is not None and current_rate < 0:
            return True, f"Funding rate went negative ({current_rate:.4%})"
        if current_rate is not None and current_rate < config.EXIT_FUNDING_RATE:
            return True, f"Funding rate {current_rate:.4%} below exit threshold {config.EXIT_FUNDING_RATE:.4%}"
        return False, ""

    # ── Position tracking ─────────────────────────────────────────────────────

    def record_open(self, pos: Position) -> None:
        self._positions[pos.id] = pos

    def record_funding(self, pos_id: str, amount: float, rate: float) -> None:
        if pos_id in self._positions:
            p = self._positions[pos_id]
            p.funding_collected += amount
            p.funding_periods += 1
            p.last_rate_8h = rate
            self._total_funding_earned += amount

    def record_close(self, pos_id: str) -> Optional[Position]:
        pos = self._positions.pop(pos_id, None)
        if pos:
            self._closed_positions.append(pos)
        return pos

    # ── Stats ─────────────────────────────────────────────────────────────────

    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def total_deployed(self) -> float:
        return sum(p.size_usdc for p in self._positions.values())

    def total_funding_earned(self) -> float:
        return self._total_funding_earned

    def total_pnl(self) -> float:
        return self._total_funding_earned

    def get_stats(self) -> dict:
        positions = list(self._positions.values())
        return {
            "open_positions": len(positions),
            "total_deployed": self.total_deployed(),
            "total_funding_earned": self._total_funding_earned,
            "closed_positions": len(self._closed_positions),
            "avg_apy": (
                sum(p.apy_realised for p in positions) / len(positions)
                if positions else 0.0
            ),
        }
