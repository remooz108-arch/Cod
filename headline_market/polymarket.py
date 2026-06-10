"""
Polymarket integration for the headline prediction market.

When the headline signal fires, this module:
  1. Searches for active escalation-related prediction markets
  2. Filters by price bounds (avoid markets that have already moved)
  3. Places YES bets via FOK market orders
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import requests
import config

# ── SDK detection ─────────────────────────────────────────────────────────────

_SDK = "none"
try:
    from py_clob_client_v2 import ClobClient, MarketOrderArgs, OrderType, Side  # type: ignore
    _SDK = "v2"
except ImportError:
    try:
        from py_clob_client.client import ClobClient  # type: ignore
        from py_clob_client.clob_types import MarketOrderArgs, OrderType  # type: ignore
        from py_clob_client.order_builder.constants import BUY  # type: ignore
        class Side:  # type: ignore
            BUY = BUY
        _SDK = "legacy"
    except ImportError:
        ClobClient = None
        _SDK = "none"


# ── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class BetTarget:
    condition_id: str
    question: str
    yes_token_id: str
    yes_price: float
    end_date: str


@dataclass
class BetResult:
    question: str
    yes_price: float
    amount_usdc: float
    status: str          # "placed" | "dry_run" | "skipped" | "failed"
    order_id: Optional[str]
    error: Optional[str]


# ── Client ────────────────────────────────────────────────────────────────────

def init_client() -> Optional[Any]:
    if _SDK == "none":
        return None
    if not config.POLY_PRIVATE_KEY or config.POLY_PRIVATE_KEY.startswith("0x_your"):
        return None
    try:
        if _SDK == "v2":
            l1 = ClobClient(
                host=config.CLOB_HOST,
                chain_id=config.CHAIN_ID,
                key=config.POLY_PRIVATE_KEY,
            )
            creds = l1.create_or_derive_api_key()
            return ClobClient(
                host=config.CLOB_HOST,
                chain_id=config.CHAIN_ID,
                key=config.POLY_PRIVATE_KEY,
                creds=creds,
            )
        else:
            c = ClobClient(
                host=config.CLOB_HOST,
                chain_id=config.CHAIN_ID,
                key=config.POLY_PRIVATE_KEY,
            )
            try:
                c.set_api_creds(c.create_or_derive_api_creds())
            except Exception:
                pass
            return c
    except Exception as exc:
        print(f"  [polymarket] Auth failed: {exc}")
        return None


# ── Market search ─────────────────────────────────────────────────────────────

def find_targets() -> list[BetTarget]:
    """Search Gamma API for escalation markets and return those within price bounds."""
    seen: set[str] = set()
    targets: list[BetTarget] = []

    for term in config.POLY_SEARCH_TERMS:
        try:
            resp = requests.get(
                f"{config.GAMMA_HOST}/markets",
                params={"keyword": term, "active": "true", "closed": "false", "limit": 10},
                timeout=10,
            )
            resp.raise_for_status()
            batch = resp.json()
        except Exception as exc:
            print(f"  [polymarket] Search '{term}' failed: {exc}")
            continue

        for m in batch:
            cid = m.get("conditionId") or m.get("condition_id", "")
            if not cid or cid in seen:
                continue

            raw_ids = m.get("clobTokenIds", "[]")
            token_ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            if len(token_ids) != 2:
                continue

            yes_token_id = str(token_ids[0])
            yes_price = _best_ask(yes_token_id)

            if yes_price is None:
                continue
            if not (config.MIN_YES_PRICE <= yes_price <= config.MAX_YES_PRICE):
                continue

            seen.add(cid)
            targets.append(BetTarget(
                condition_id=cid,
                question=m.get("question", ""),
                yes_token_id=yes_token_id,
                yes_price=yes_price,
                end_date=(m.get("endDate") or m.get("end_date", "unknown"))[:10],
            ))

    # Sort by price ascending — cheapest YES bets first (most upside)
    targets.sort(key=lambda t: t.yes_price)
    return targets


def _best_ask(token_id: str) -> Optional[float]:
    try:
        resp = requests.get(
            f"{config.CLOB_HOST}/book",
            params={"token_id": token_id},
            timeout=8,
        )
        if not resp.ok:
            return None
        asks = resp.json().get("asks", [])
        if not asks:
            return None
        return min(float(a["price"]) for a in asks)
    except Exception:
        return None


# ── Betting ───────────────────────────────────────────────────────────────────

def place_bets(client: Optional[Any], targets: list[BetTarget]) -> list[BetResult]:
    """Place YES bets on all targets. Respects LIVE_BETTING flag."""
    results: list[BetResult] = []

    for t in targets:
        if not config.LIVE_BETTING or client is None:
            results.append(BetResult(
                question=t.question,
                yes_price=t.yes_price,
                amount_usdc=config.BET_AMOUNT_USDC,
                status="dry_run",
                order_id=None,
                error=None,
            ))
            continue

        try:
            if _SDK == "v2":
                resp = client.create_and_post_market_order(
                    order_args=MarketOrderArgs(
                        token_id=t.yes_token_id,
                        amount=config.BET_AMOUNT_USDC,
                        side=Side.BUY,
                    ),
                    order_type=OrderType.FOK,
                )
            else:
                resp = client.create_and_post_market_order(
                    MarketOrderArgs(
                        token_id=t.yes_token_id,
                        amount=config.BET_AMOUNT_USDC,
                        side=Side.BUY,
                    ),
                    OrderType.FOK,
                )

            order_id = resp.get("orderID") or resp.get("id")
            results.append(BetResult(
                question=t.question,
                yes_price=t.yes_price,
                amount_usdc=config.BET_AMOUNT_USDC,
                status="placed",
                order_id=order_id,
                error=None,
            ))
        except Exception as exc:
            results.append(BetResult(
                question=t.question,
                yes_price=t.yes_price,
                amount_usdc=config.BET_AMOUNT_USDC,
                status="failed",
                order_id=None,
                error=str(exc),
            ))

    return results


def display_results(targets: list[BetTarget], results: list[BetResult]) -> str:
    if not targets:
        return "  No eligible markets found."
    lines = []
    for t, r in zip(targets, results):
        icon = {"placed": "✅", "dry_run": "🔵", "failed": "❌", "skipped": "⏭"}.get(r.status, "?")
        lines.append(
            f"  {icon} [{r.status.upper():7s}]  YES @ {t.yes_price:.3f}  "
            f"${r.amount_usdc:.2f}  →  {t.question[:55]}"
            + (f"\n           order: {r.order_id}" if r.order_id else "")
            + (f"\n           error: {r.error}" if r.error else "")
        )
    return "\n".join(lines)
