"""
Async order book fetching via REST + live WebSocket state.

Public endpoints — no auth required for reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .models import OrderBook, OrderLevel

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


# ── REST ─────────────────────────────────────────────────────────────────────

async def get_order_book(
    session: aiohttp.ClientSession,
    token_id: str,
    retries: int = 3,
) -> Optional[OrderBook]:
    url = f"{CLOB_HOST}/book"
    backoff = 0.5
    for attempt in range(retries):
        try:
            async with session.get(
                url,
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 429:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
                if resp.status != 200:
                    logger.debug(f"Book HTTP {resp.status} for {token_id[:12]}...")
                    return None
                data = await resp.json(content_type=None)
                return _parse_book(token_id, data)

        except asyncio.TimeoutError:
            if attempt < retries - 1:
                await asyncio.sleep(backoff)
        except aiohttp.ClientError as exc:
            logger.debug(f"Book fetch error ({token_id[:12]}...): {exc}")
            if attempt < retries - 1:
                await asyncio.sleep(backoff)
    return None


async def get_order_books_batch(
    session: aiohttp.ClientSession,
    token_ids: list[str],
    concurrency: int = 20,
) -> dict[str, Optional[OrderBook]]:
    """Fetch multiple order books concurrently, respecting concurrency limit."""
    sem = asyncio.Semaphore(concurrency)

    async def _fetch(tid: str) -> tuple[str, Optional[OrderBook]]:
        async with sem:
            return tid, await get_order_book(session, tid)

    results = await asyncio.gather(*[_fetch(t) for t in token_ids], return_exceptions=False)
    return dict(results)


def get_executable_depth(book: OrderBook, max_price: float) -> float:
    """Total USDC available to fill at or below max_price on the ask side."""
    return sum(lv.price * lv.size for lv in book.asks if lv.price <= max_price)


def _parse_book(token_id: str, data: dict) -> OrderBook:
    def parse_levels(raw: list) -> list[OrderLevel]:
        out: list[OrderLevel] = []
        for item in raw:
            try:
                if isinstance(item, dict):
                    out.append(OrderLevel(
                        price=float(item.get("price", 0)),
                        size=float(item.get("size", 0)),
                    ))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    out.append(OrderLevel(price=float(item[0]), size=float(item[1])))
            except (ValueError, TypeError):
                continue
        return out

    return OrderBook(
        token_id=token_id,
        bids=parse_levels(data.get("bids", [])),
        asks=parse_levels(data.get("asks", [])),
        timestamp=datetime.utcnow(),
    )


# ── WebSocket ────────────────────────────────────────────────────────────────

class WebSocketManager:
    """
    Maintains live OrderBook snapshots for subscribed token IDs.
    Auto-reconnects with exponential backoff on disconnect.
    Provides `is_fresh()` so the executor can skip stale REST fetches.
    """

    def __init__(self, token_ids: list[str] | None = None):
        self._token_ids: set[str] = set(token_ids or [])
        self._books: Dict[str, OrderBook] = {}
        self._running = False
        self._lock = asyncio.Lock()
        self._subscribed_in_session: set[str] = set()

    def add_tokens(self, token_ids: list[str]) -> None:
        new = set(token_ids) - self._token_ids
        self._token_ids.update(new)

    def get_book(self, token_id: str) -> Optional[OrderBook]:
        return self._books.get(token_id)

    def is_fresh(self, token_id: str, max_age_ms: int = 200) -> bool:
        book = self._books.get(token_id)
        if book is None:
            return False
        age_ms = (datetime.utcnow() - book.timestamp).total_seconds() * 1000
        return age_ms <= max_age_ms

    async def run(self) -> None:
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    backoff = 1.0
                    self._subscribed_in_session.clear()
                    logger.info("WebSocket connected to Polymarket price feed")
                    await self._subscribe_pending(ws)
                    async for raw in ws:
                        await self._handle(raw)
                        # Subscribe to any tokens added since connect
                        await self._subscribe_pending(ws)

            except (ConnectionClosed, WebSocketException) as exc:
                logger.warning(f"WebSocket disconnected ({exc}). Reconnecting in {backoff:.0f}s...")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"WebSocket unexpected error: {exc}. Reconnecting in {backoff:.0f}s...")

            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

        logger.info("WebSocket manager stopped.")

    def stop(self) -> None:
        self._running = False

    async def _subscribe_pending(self, ws) -> None:
        unsubscribed = self._token_ids - self._subscribed_in_session
        for token_id in unsubscribed:
            try:
                await ws.send(json.dumps({"type": "market", "assets_id": token_id}))
                self._subscribed_in_session.add(token_id)
            except Exception as exc:
                logger.debug(f"WS subscribe error for {token_id[:12]}...: {exc}")

    async def _handle(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return

            # Polymarket WS may use different field names across versions
            token_id = (
                data.get("asset_id")
                or data.get("assetId")
                or data.get("token_id")
                or data.get("market")
            )
            if not token_id:
                return

            bids_raw = data.get("bids", [])
            asks_raw = data.get("asks", [])
            if not bids_raw and not asks_raw:
                return

            def parse(raw_list: list) -> list[OrderLevel]:
                out: list[OrderLevel] = []
                for item in raw_list:
                    try:
                        if isinstance(item, dict):
                            out.append(OrderLevel(float(item["price"]), float(item["size"])))
                        elif isinstance(item, (list, tuple)) and len(item) >= 2:
                            out.append(OrderLevel(float(item[0]), float(item[1])))
                    except (KeyError, ValueError, TypeError):
                        continue
                return out

            async with self._lock:
                self._books[token_id] = OrderBook(
                    token_id=token_id,
                    bids=parse(bids_raw),
                    asks=parse(asks_raw),
                    timestamp=datetime.utcnow(),
                )
        except Exception as exc:
            logger.debug(f"WS message parse error: {exc}")
