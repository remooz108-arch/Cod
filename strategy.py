"""Betting strategy: compare weather-implied probability vs market price."""

from dataclasses import dataclass
from typing import Optional
from weather import WeatherSnapshot
from market_finder import PolymarketMarket
import config


@dataclass
class BetDecision:
    market: PolymarketMarket
    # "YES" or "NO"
    side: str
    token_id: str
    # Our probability estimate (0-1)
    our_prob: float
    # Market's implied probability (0-1)
    market_prob: float
    # Edge = our_prob - market_prob
    edge: float
    # Recommended stake in USDC
    stake_usdc: float
    # Limit price to submit
    limit_price: float
    reason: str


def weather_rain_prob(ws: WeatherSnapshot) -> float:
    """Convert WeatherSnapshot to a single 0-1 rain probability."""
    # Base: max hourly PoP
    base = ws.rain_probability / 100.0

    # Boost slightly if actual rain accumulation is forecast
    if ws.rain_mm_24h > 0:
        base = min(base + 0.05, 1.0)

    # Humidity nudge: high humidity increases likelihood
    if ws.humidity >= 85:
        base = min(base + 0.03, 1.0)
    elif ws.humidity <= 40:
        base = max(base - 0.03, 0.0)

    return base


def kelly_stake(our_prob: float, market_price: float, bankroll: float, fraction: float) -> float:
    """Full Kelly fraction of bankroll; capped at MAX_BET_USDC."""
    if market_price <= 0 or market_price >= 1:
        return 0.0
    # Decimal odds for a $1 bet at market_price: win (1/market_price - 1)
    b = (1.0 / market_price) - 1.0
    q = 1.0 - our_prob
    kelly = (our_prob * b - q) / b
    if kelly <= 0:
        return 0.0
    stake = bankroll * kelly * fraction
    return round(min(stake, config.MAX_BET_USDC), 2)


def decide(ws: WeatherSnapshot, market: PolymarketMarket) -> Optional[BetDecision]:
    """Return a BetDecision if there is sufficient edge, else None."""
    our_prob = weather_rain_prob(ws)

    # Try to match the market question to YES=rain or YES=no-rain
    q_lower = market.question.lower()
    yes_means_rain = any(word in q_lower for word in ["rain", "precipitation", "wet", "shower"])

    if yes_means_rain:
        market_yes_prob = market.yes_price if market.yes_price is not None else 0.5
        edge_yes = our_prob - market_yes_prob
        edge_no = (1 - our_prob) - (1 - market_yes_prob)

        if edge_yes >= config.MIN_EDGE and market.yes_price:
            stake = kelly_stake(our_prob, market.yes_price, config.MAX_BET_USDC, config.KELLY_FRACTION)
            return BetDecision(
                market=market,
                side="YES",
                token_id=market.yes_token_id,
                our_prob=our_prob,
                market_prob=market_yes_prob,
                edge=edge_yes,
                stake_usdc=stake,
                limit_price=round(market.yes_price + 0.01, 3),
                reason=f"Weather says {our_prob*100:.0f}% rain; market says {market_yes_prob*100:.0f}%",
            )
        elif edge_no >= config.MIN_EDGE and market.no_price:
            no_prob = 1 - our_prob
            stake = kelly_stake(no_prob, market.no_price, config.MAX_BET_USDC, config.KELLY_FRACTION)
            return BetDecision(
                market=market,
                side="NO",
                token_id=market.no_token_id,
                our_prob=no_prob,
                market_prob=1 - market_yes_prob,
                edge=edge_no,
                stake_usdc=stake,
                limit_price=round(market.no_price + 0.01, 3),
                reason=f"Weather says {(1-our_prob)*100:.0f}% no-rain; market says {(1-market_yes_prob)*100:.0f}%",
            )

    return None


def summarise_decision(d: Optional[BetDecision]) -> str:
    if d is None:
        return "No edge found — skipping this market."
    return (
        f"BET {d.side} on: {d.market.question}\n"
        f"  Our probability : {d.our_prob*100:.1f}%\n"
        f"  Market price    : {d.market_prob*100:.1f}%\n"
        f"  Edge            : {d.edge*100:.1f}%\n"
        f"  Stake           : ${d.stake_usdc:.2f} USDC\n"
        f"  Limit price     : {d.limit_price}\n"
        f"  Reason          : {d.reason}\n"
    )
