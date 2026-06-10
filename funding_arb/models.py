from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional


@dataclass
class FundingRate:
    exchange: str
    symbol: str          # e.g. "BTC/USDT:USDT"
    base: str            # e.g. "BTC"
    rate_8h: float       # funding rate per 8-hour period
    apy: float           # annualised %
    next_funding: Optional[datetime]
    mark_price: float
    perp_only: bool = False  # True for Hyperliquid — no built-in spot execution


@dataclass
class Position:
    id: str              # "{exchange}:{base}"
    exchange: str
    base: str
    spot_symbol: str     # e.g. "BTC/USDT"
    perp_symbol: str     # e.g. "BTC/USDT:USDT"
    spot_exchange: str   # exchange holding the long spot (may differ from perp_exchange)

    spot_qty: float
    perp_qty: float
    entry_spot_price: float
    entry_perp_price: float
    size_usdc: float

    opened_at: datetime
    funding_collected: float = 0.0
    funding_periods: int = 0
    last_rate_8h: float = 0.0

    spot_order_id: Optional[str] = None
    perp_order_id: Optional[str] = None
    last_period_at: Optional[datetime] = None  # tracks 8h funding window

    @property
    def apy_realised(self) -> float:
        if self.funding_periods == 0 or self.size_usdc == 0:
            return 0.0
        total_return = self.funding_collected / self.size_usdc
        return (total_return / self.funding_periods) * 1095 * 100


@dataclass
class DailyStats:
    date: date
    funding_earned: float = 0.0
    positions_opened: int = 0
    positions_closed: int = 0


@dataclass
class RateSpike:
    exchange: str
    base: str
    rate_8h: float
    apy: float
    detected_at: datetime = field(default_factory=datetime.utcnow)

    def __str__(self) -> str:
        return (
            f"SPIKE {self.exchange} {self.base} "
            f"{self.rate_8h:.4%}/8h = {self.apy:.0f}% APY"
        )


@dataclass
class ExchangeSnapshot:
    exchange: str
    rates: list[FundingRate] = field(default_factory=list)
    error: Optional[str] = None
    fetched_at: datetime = field(default_factory=datetime.utcnow)
