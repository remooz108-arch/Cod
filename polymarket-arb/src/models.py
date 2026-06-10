from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Market:
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    tick_size: float
    min_order_size: float
    outcome_prices: tuple[float, float]  # (yes_price, no_price)
    active: bool
    accepting_orders: bool


@dataclass
class OrderLevel:
    price: float
    size: float  # shares


@dataclass
class OrderBook:
    token_id: str
    bids: list[OrderLevel]
    asks: list[OrderLevel]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def best_ask(self) -> Optional[OrderLevel]:
        return min(self.asks, key=lambda x: x.price) if self.asks else None

    @property
    def best_bid(self) -> Optional[OrderLevel]:
        return max(self.bids, key=lambda x: x.price) if self.bids else None

    def ask_depth_usdc(self, max_price: float) -> float:
        """Total USDC fillable at or below max_price."""
        return sum(lv.price * lv.size for lv in self.asks if lv.price <= max_price)


@dataclass
class Opportunity:
    market: Market
    best_ask_yes: float
    best_ask_no: float
    pair_cost: float
    estimated_profit_pct: float
    estimated_profit_usdc: float
    depth_yes_usdc: float
    depth_no_usdc: float
    detected_at: datetime


@dataclass
class Trade:
    opportunity: Opportunity
    yes_order_id: Optional[str]
    no_order_id: Optional[str]
    yes_fill_price: float
    no_fill_price: float
    size_usdc: float
    status: str  # "filled" | "partial" | "failed" | "dry_run"
    executed_at: datetime
    pnl_usdc: float

    def to_dict(self) -> dict:
        m = self.opportunity.market
        return {
            "_type": "trade",
            "condition_id": m.condition_id,
            "question": m.question,
            "yes_order_id": self.yes_order_id,
            "no_order_id": self.no_order_id,
            "yes_fill_price": self.yes_fill_price,
            "no_fill_price": self.no_fill_price,
            "pair_cost": round(self.yes_fill_price + self.no_fill_price, 6),
            "size_usdc": self.size_usdc,
            "status": self.status,
            "executed_at": self.executed_at.isoformat(),
            "pnl_usdc": self.pnl_usdc,
        }
