"""
Build trade setups triggered by the geopolitical signal.

When Trump + Iran + Israel appear in the same article:
  - BUY XLE  (oil/energy ETF — spikes on Middle East tension)
  - BUY GLD  (gold ETF — safe-haven demand rises)

Both use a fixed stop loss of RISK_PER_TRADE_USD / current_price
and a 1:1 take-profit above entry.
"""

import math
from dataclasses import dataclass
import config


@dataclass
class TradeSetup:
    symbol: str
    side: str          # "BUY"
    shares: int
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_usd: float


def build_trade(symbol: str, current_price: float) -> TradeSetup | None:
    if current_price <= 0:
        return None

    # Use a fixed 1% stop below entry for ETFs (liquid, low-volatility)
    stop_distance = round(current_price * 0.01, 4)
    if stop_distance == 0:
        return None

    shares = min(
        math.floor(config.RISK_PER_TRADE_USD / stop_distance),
        config.MAX_SHARES,
    )
    if shares == 0:
        return None

    stop_loss = round(current_price - stop_distance, 4)
    take_profit = round(current_price + stop_distance, 4)   # 1:1

    return TradeSetup(
        symbol=symbol,
        side="BUY",
        shares=shares,
        entry_price=current_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_usd=round(shares * stop_distance, 2),
    )


def summarise(setup: TradeSetup) -> str:
    return (
        f"  BUY {setup.shares} x {setup.symbol} @ ~${setup.entry_price:.2f}\n"
        f"    Stop loss  : ${setup.stop_loss:.4f}\n"
        f"    Take profit: ${setup.take_profit:.4f}  (1:1)\n"
        f"    Risk       : ${setup.risk_usd:.2f}\n"
    )
