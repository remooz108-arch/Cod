"""Price parsing, tick rounding, USDC formatting."""

from __future__ import annotations

import json
import math
from typing import Union


def parse_price_list(raw: Union[str, list]) -> list[float]:
    """Parse Gamma API outcomePrices (JSON string or list) → list[float]."""
    if isinstance(raw, list):
        return [float(p) for p in raw]
    try:
        return [float(p) for p in json.loads(raw)]
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def parse_token_ids(raw: Union[str, list]) -> list[str]:
    """Parse Gamma API clobTokenIds (JSON string or list) → list[str]."""
    if isinstance(raw, list):
        return [str(t) for t in raw]
    try:
        return [str(t) for t in json.loads(raw)]
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def round_to_tick(value: float, tick_size: float) -> float:
    """Round value DOWN to the nearest tick increment."""
    if tick_size <= 0:
        return value
    return math.floor(value / tick_size) * tick_size


def format_usdc(amount: float) -> str:
    return f"${amount:,.2f}"


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def profit_after_fee(pair_cost: float, fee_rate: float = 0.02) -> float:
    """
    Gross profit on a binary arb = 1.0 - pair_cost.
    Fee applies to net winnings only (~2% of gross profit).
    Returns net profit per USDC of position size.
    """
    gross = 1.0 - pair_cost
    if gross <= 0:
        return 0.0
    return gross * (1.0 - fee_rate)


def is_opportunity(pair_cost: float, min_spread: float, fee_rate: float = 0.02) -> bool:
    """Return True if the net profit per dollar exceeds min_spread."""
    return profit_after_fee(pair_cost, fee_rate) >= min_spread
