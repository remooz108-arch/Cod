"""
Market discovery and opportunity detection.

Fetches all active binary markets from Gamma API (cached 60s),
then checks each market's YES+NO order books for arb mispricings.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Awaitable, Callable, Optional

import aiohttp

from .config import Config
from .models import Market, Opportunity, OrderBook
from .orderbook import WebSocketManager, get_order_books_batch
from .utils import (
    format_pct,
    format_usdc,
    is_opportunity,
    parse_price_list,
    parse_token_ids,
    profit_after_fee,
)

logger = logging.getLogger(__name__)

GAMMA_HOST = "https://gamma-api.polymarket.com"
OpportunityCallback = Callable[[Opportunity], Awaitable[None]]


class Scanner:
    def __init__(self, config: Config, ws_manager: Optional[WebSocketManager] = None):
        self._config = config
        self._ws_manager = ws_manager
        self._markets: list[Market] = []
        self._markets_fetched_at: float = 0.0
        self._markets_cache_ttl = 60.0
        self._running = False
        self._stats = {
            "markets_scanned": 0,
            "opportunities_found": 0,
            "scan_count": 0,
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, callback: OpportunityCallback) -> None:
        self._running = True
        interval = self._config.scan_interval_ms / 1000.0
        connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)
        async with aiohttp.ClientSession(
            connector=connector,
            headers={"User-Agent": "polymarket-arb-bot/1.0"},
        ) as session:
            while self._running:
                t0 = time.monotonic()
                try:
                    await self.scan_once(session, callback)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error(f"Scan loop error: {exc}", exc_info=True)

                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0.0, interval - elapsed))

    async def scan_once(
        self,
        session: aiohttp.ClientSession,
        callback: OpportunityCallback,
    ) -> None:
        await self._maybe_refresh_markets(session)

        markets = self._markets[: self._config.max_concurrent_markets]
        if not markets:
            return

        self._stats["scan_count"] += 1
        self._stats["markets_scanned"] += len(markets)

        # Determine which token IDs need a fresh REST book fetch
        need_rest: list[str] = []
        for m in markets:
            if not (self._ws_manager and self._ws_manager.is_fresh(m.yes_token_id)):
                need_rest.append(m.yes_token_id)
            if not (self._ws_manager and self._ws_manager.is_fresh(m.no_token_id)):
                need_rest.append(m.no_token_id)

        rest_books: dict[str, Optional[OrderBook]] = {}
        if need_rest:
            rest_books = await get_order_books_batch(session, need_rest)

        for m in markets:
            yes_book = (
                (self._ws_manager.get_book(m.yes_token_id) if self._ws_manager else None)
                or rest_books.get(m.yes_token_id)
            )
            no_book = (
                (self._ws_manager.get_book(m.no_token_id) if self._ws_manager else None)
                or rest_books.get(m.no_token_id)
            )

            opp = _evaluate_opportunity(m, yes_book, no_book, self._config)
            if opp is not None:
                self._stats["opportunities_found"] += 1
                logger.info(
                    f"[OPPORTUNITY] {m.question[:55]} | "
                    f"cost={opp.pair_cost:.4f} | "
                    f"net_profit={format_pct(opp.estimated_profit_pct)} | "
                    f"depth YES={format_usdc(opp.depth_yes_usdc)} "
                    f"NO={format_usdc(opp.depth_no_usdc)}"
                )
                await callback(opp)

    def stop(self) -> None:
        self._running = False

    # ── Private ───────────────────────────────────────────────────────────────

    async def _maybe_refresh_markets(self, session: aiohttp.ClientSession) -> None:
        now = time.monotonic()
        if now - self._markets_fetched_at > self._markets_cache_ttl:
            self._markets = await _fetch_binary_markets(session)
            self._markets_fetched_at = now
            if self._ws_manager:
                ids = [tid for m in self._markets for tid in (m.yes_token_id, m.no_token_id)]
                self._ws_manager.add_tokens(ids)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_binary_markets(session: aiohttp.ClientSession) -> list[Market]:
    markets: list[Market] = []
    offset, limit = 0, 100

    while True:
        try:
            async with session.get(
                f"{GAMMA_HOST}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "offset": offset,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 429:
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                batch: list[dict] = await resp.json(content_type=None)
        except Exception as exc:
            logger.warning(f"Gamma API error (offset={offset}): {exc}")
            break

        if not batch:
            break

        for raw in batch:
            m = _parse_market(raw)
            if m is not None:
                markets.append(m)

        if len(batch) < limit:
            break
        offset += limit

    logger.info(f"Loaded {len(markets)} active binary markets from Gamma API")
    return markets


def _parse_market(raw: dict) -> Optional[Market]:
    try:
        if not raw.get("active") or not raw.get("accepting_orders"):
            return None

        prices = parse_price_list(raw.get("outcomePrices", "[]"))
        token_ids = parse_token_ids(raw.get("clobTokenIds", "[]"))

        if len(prices) != 2 or len(token_ids) != 2:
            return None
        if not token_ids[0] or not token_ids[1]:
            return None

        tick_raw = raw.get("tickSize") or raw.get("tick_size")
        tick_size = float(tick_raw) if tick_raw else 0.01

        min_order_raw = raw.get("minOrderSize") or raw.get("minimum_order_size")
        min_order = float(min_order_raw) if min_order_raw else 5.0

        return Market(
            condition_id=raw.get("conditionId") or raw.get("condition_id", ""),
            question=raw.get("question", "Unknown market"),
            yes_token_id=token_ids[0],
            no_token_id=token_ids[1],
            tick_size=tick_size,
            min_order_size=min_order,
            outcome_prices=(prices[0], prices[1]),
            active=True,
            accepting_orders=True,
        )
    except Exception:
        return None


def _evaluate_opportunity(
    market: Market,
    yes_book: Optional[OrderBook],
    no_book: Optional[OrderBook],
    config: Config,
) -> Optional[Opportunity]:
    if yes_book is None or no_book is None:
        return None

    yes_ask = yes_book.best_ask
    no_ask = no_book.best_ask
    if yes_ask is None or no_ask is None:
        return None
    if yes_ask.price <= 0 or no_ask.price <= 0:
        return None

    pair_cost = yes_ask.price + no_ask.price

    if not is_opportunity(pair_cost, config.min_spread, fee_rate=0.02):
        return None

    depth_yes = yes_book.ask_depth_usdc(yes_ask.price * 1.02)
    depth_no = no_book.ask_depth_usdc(no_ask.price * 1.02)

    if depth_yes < config.min_market_liquidity_usdc:
        return None
    if depth_no < config.min_market_liquidity_usdc:
        return None

    net_profit_per_dollar = profit_after_fee(pair_cost, 0.02)
    profit_usdc = net_profit_per_dollar * min(config.max_position_usdc, depth_yes, depth_no)

    return Opportunity(
        market=market,
        best_ask_yes=yes_ask.price,
        best_ask_no=no_ask.price,
        pair_cost=pair_cost,
        estimated_profit_pct=net_profit_per_dollar,
        estimated_profit_usdc=profit_usdc,
        depth_yes_usdc=depth_yes,
        depth_no_usdc=depth_no,
        detected_at=datetime.utcnow(),
    )
