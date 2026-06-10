"""
Search Polymarket's Gamma API for active markets related to the signal.
Returns markets most likely to be YES bets when an Iran/Israel/Trump
headline fires (conflict escalation markets).
"""

import requests
from dataclasses import dataclass
from typing import Optional
import config


@dataclass
class PredictionMarket:
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    yes_price: Optional[float]   # current ask price 0–1
    end_date: str


def _best_ask(clob_host: str, token_id: str) -> Optional[float]:
    try:
        resp = requests.get(
            f"{clob_host}/book",
            params={"token_id": token_id},
            timeout=8,
        )
        if not resp.ok:
            return None
        data = resp.json()
        asks = data.get("asks", [])
        if not asks:
            return None
        return min(float(a["price"]) for a in asks)
    except Exception:
        return None


def find_markets(search_terms: list[str] | None = None) -> list[PredictionMarket]:
    terms = search_terms or config.MARKET_SEARCH_TERMS
    seen: set[str] = set()
    markets: list[PredictionMarket] = []

    for term in terms:
        try:
            resp = requests.get(
                f"{config.GAMMA_HOST}/markets",
                params={
                    "keyword": term,
                    "active": "true",
                    "closed": "false",
                    "limit": 10,
                },
                timeout=12,
            )
            resp.raise_for_status()
            batch = resp.json()
        except Exception as exc:
            print(f"  [warn] Gamma search '{term}' failed: {exc}")
            continue

        for m in batch:
            cid = m.get("conditionId") or m.get("condition_id", "")
            if not cid or cid in seen:
                continue

            # Must be binary (exactly 2 outcome tokens)
            import json
            raw_ids = m.get("clobTokenIds", "[]")
            token_ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            if len(token_ids) != 2:
                continue

            seen.add(cid)
            yes_id, no_id = str(token_ids[0]), str(token_ids[1])
            yes_price = _best_ask(config.CLOB_HOST, yes_id)

            markets.append(PredictionMarket(
                condition_id=cid,
                question=m.get("question", ""),
                yes_token_id=yes_id,
                no_token_id=no_id,
                yes_price=yes_price,
                end_date=m.get("endDate") or m.get("end_date", "unknown"),
            ))

    return markets


def display(markets: list[PredictionMarket]) -> str:
    if not markets:
        return "  No related Polymarket markets found."
    lines = []
    for m in markets:
        price_str = f"{m.yes_price:.3f}" if m.yes_price is not None else "n/a"
        lines.append(
            f"  [{price_str} YES]  {m.question[:70]}\n"
            f"           Ends: {m.end_date}  |  ID: {m.condition_id[:18]}..."
        )
    return "\n".join(lines)
