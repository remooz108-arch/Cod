"""Search Polymarket's Gamma API for Batumi rain/weather markets."""

import requests
from dataclasses import dataclass
from typing import Optional
import config


@dataclass
class PolymarketMarket:
    condition_id: str
    question: str
    end_date: str
    # Token ID for YES outcome
    yes_token_id: str
    # Token ID for NO outcome
    no_token_id: str
    # Current best ask price for YES (0-1)
    yes_price: Optional[float]
    # Current best ask price for NO (0-1)
    no_price: Optional[float]
    active: bool
    closed: bool


_SEARCH_TERMS = [
    "batumi rain",
    "batumi weather",
    "georgia rain batumi",
    "rain batumi",
]


def _fetch_markets(keyword: str) -> list[dict]:
    resp = requests.get(
        f"{config.GAMMA_API}/markets",
        params={"keyword": keyword, "limit": 20, "active": "true", "closed": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _clob_prices(clob_token_ids: list[str], clob_host: str) -> dict[str, float]:
    """Return {token_id: best_ask_price} from the CLOB mid-point book."""
    prices: dict[str, float] = {}
    for token_id in clob_token_ids:
        try:
            resp = requests.get(
                f"{clob_host}/price",
                params={"token_id": token_id, "side": "buy"},
                timeout=10,
            )
            if resp.ok:
                prices[token_id] = float(resp.json().get("price", 0))
        except Exception:
            pass
    return prices


def find_rain_markets(clob_host: str = config.CLOB_HOST) -> list[PolymarketMarket]:
    seen: set[str] = set()
    markets: list[PolymarketMarket] = []

    for term in _SEARCH_TERMS:
        try:
            raw = _fetch_markets(term)
        except Exception as exc:
            print(f"  [warn] gamma search for '{term}' failed: {exc}")
            continue

        for m in raw:
            cid = m.get("conditionId") or m.get("condition_id", "")
            if not cid or cid in seen:
                continue
            seen.add(cid)

            tokens = m.get("tokens", []) or m.get("clob_token_ids", [])
            if len(tokens) < 2:
                continue

            # Gamma returns tokens as list of dicts or plain strings
            if isinstance(tokens[0], dict):
                yes_id = tokens[0].get("token_id", "")
                no_id = tokens[1].get("token_id", "")
            else:
                yes_id, no_id = str(tokens[0]), str(tokens[1])

            price_map = _clob_prices([yes_id, no_id], clob_host)

            markets.append(PolymarketMarket(
                condition_id=cid,
                question=m.get("question", ""),
                end_date=m.get("endDate") or m.get("end_date", "unknown"),
                yes_token_id=yes_id,
                no_token_id=no_id,
                yes_price=price_map.get(yes_id),
                no_price=price_map.get(no_id),
                active=m.get("active", True),
                closed=m.get("closed", False),
            ))

    return markets


def summarise_markets(markets: list[PolymarketMarket]) -> str:
    if not markets:
        return "No Batumi rain markets found on Polymarket."
    lines = [f"Found {len(markets)} relevant market(s):\n"]
    for i, m in enumerate(markets, 1):
        yes_str = f"{m.yes_price:.3f}" if m.yes_price is not None else "n/a"
        no_str = f"{m.no_price:.3f}" if m.no_price is not None else "n/a"
        lines.append(
            f"  [{i}] {m.question}\n"
            f"       Ends: {m.end_date}\n"
            f"       YES price: {yes_str}  |  NO price: {no_str}\n"
            f"       Condition ID: {m.condition_id[:20]}...\n"
        )
    return "\n".join(lines)
