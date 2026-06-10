from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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


@dataclass
class Position:
    id: str              # "{exchange}:{base}"
    exchange: str
    base: str            # e.g. "BTC"
    spot_symbol: str     # e.g. "BTC/USDT"
    perp_symbol: str     # e.g. "BTC/USDT:USDT"

    spot_qty: float      # units of base asset held long
    perp_qty: float      # units of base asset shorted (positive number)
    entry_spot_price: float
    entry_perp_price: float
    size_usdc: float     # total USDC deployed

    opened_at: datetime
    funding_collected: float = 0.0    # USDC received so far
    funding_periods: int = 0          # number of 8h periods elapsed
    last_rate_8h: float = 0.0

    spot_order_id: Optional[str] = None
    perp_order_id: Optional[str] = None

    @property
    def unrealised_pnl(self) -> float:
        """Approximation based on last known rate × periods."""
        return self.funding_collected

    @property
    def apy_realised(self) -> float:
        if self.funding_periods == 0 or self.size_usdc == 0:
            return 0.0
        total_return = self.funding_collected / self.size_usdc
        # annualise: one period = 8h, 1095 periods/year
        return (total_return / self.funding_periods) * 1095 * 100


@dataclass
class ExchangeSnapshot:
    exchange: str
    rates: list[FundingRate] = field(default_factory=list)
    error: Optional[str] = None
    fetched_at: datetime = field(default_factory=datetime.utcnow)
