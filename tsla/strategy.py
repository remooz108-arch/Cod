"""
2-minute opening momentum strategy for TSLA.

Logic:
  - Record TSLA price at market open (9:30 AM ET) → open_price
  - Wait 2 minutes → signal_price
  - move = signal_price - open_price
  - If move > +MIN_MOVE  → go LONG
  - If move < -MIN_MOVE  → go SHORT
  - Stop loss  = entry - |move|   (long) / entry + |move|  (short)
  - Take profit = entry + |move|  (long) / entry - |move|  (short)
  - Shares = floor(RISK_PER_TRADE_USD / |move|), capped at MAX_SHARES
"""

import math
from dataclasses import dataclass
from typing import Literal
import config


@dataclass
class TradeSetup:
    direction: Literal["LONG", "SHORT"]
    open_price: float
    signal_price: float
    move: float          # signed
    entry_price: float   # = signal_price (market order)
    stop_loss: float
    take_profit: float
    shares: int
    risk_usd: float
    reward_usd: float


def build_setup(open_price: float, signal_price: float) -> TradeSetup | None:
    move = round(signal_price - open_price, 4)
    abs_move = abs(move)

    if abs_move < config.MIN_MOVE_USD:
        return None

    direction: Literal["LONG", "SHORT"] = "LONG" if move > 0 else "SHORT"
    entry = signal_price

    if direction == "LONG":
        stop_loss = round(entry - abs_move, 4)
        take_profit = round(entry + abs_move, 4)
    else:
        stop_loss = round(entry + abs_move, 4)
        take_profit = round(entry - abs_move, 4)

    shares = min(
        math.floor(config.RISK_PER_TRADE_USD / abs_move),
        config.MAX_SHARES,
    )
    if shares == 0:
        return None

    return TradeSetup(
        direction=direction,
        open_price=open_price,
        signal_price=signal_price,
        move=move,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        shares=shares,
        risk_usd=round(shares * abs_move, 2),
        reward_usd=round(shares * abs_move, 2),
    )


def summarise(setup: TradeSetup | None) -> str:
    if setup is None:
        return (
            f"No trade — 2-min move is below the ${config.MIN_MOVE_USD:.2f} threshold."
        )
    arrow = "▲ LONG " if setup.direction == "LONG" else "▼ SHORT"
    sign = "+" if setup.move > 0 else ""
    return (
        f"{arrow}  TSLA  x {setup.shares} shares\n"
        f"  Open price  : ${setup.open_price:.4f}\n"
        f"  Signal price: ${setup.signal_price:.4f}  ({sign}{setup.move:.4f})\n"
        f"  Entry       : ${setup.entry_price:.4f}  (market)\n"
        f"  Stop loss   : ${setup.stop_loss:.4f}\n"
        f"  Take profit : ${setup.take_profit:.4f}\n"
        f"  Risk / Reward: ${setup.risk_usd:.2f} / ${setup.reward_usd:.2f}  (1:1)\n"
    )
