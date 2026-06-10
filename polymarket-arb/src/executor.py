"""
Trade executor: dual FOK market orders with full leg-risk handling.

Critical path — every failure mode is explicitly handled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

import aiohttp

from .config import Config
from .logger import log_opportunity, log_trade
from .models import Opportunity, Trade
from .orderbook import get_order_books_batch
from .risk import RiskManager
from .utils import format_usdc, is_opportunity, profit_after_fee, round_to_tick

logger = logging.getLogger(__name__)


class Executor:
    def __init__(
        self,
        client: Optional[Any],
        config: Config,
        risk_mgr: RiskManager,
        monitor: Optional[Any] = None,
    ):
        self._client = client
        self._cfg = config
        self._risk = risk_mgr
        self._monitor = monitor
        self._session: Optional[aiohttp.ClientSession] = None

        self._opportunities_seen: int = 0
        self._trades_executed: int = 0
        self._latencies_ms: list[float] = []

    @property
    def opportunities_seen(self) -> int:
        return self._opportunities_seen

    @property
    def trades_executed(self) -> int:
        return self._trades_executed

    @property
    def avg_latency_ms(self) -> float:
        recent = self._latencies_ms[-50:]
        return sum(recent) / len(recent) if recent else 0.0

    # ── Entry point ───────────────────────────────────────────────────────────

    async def on_opportunity(self, opportunity: Opportunity) -> None:
        self._opportunities_seen += 1

        log_opportunity({
            "_type": "opportunity",
            "condition_id": opportunity.market.condition_id,
            "question": opportunity.market.question,
            "pair_cost": opportunity.pair_cost,
            "best_ask_yes": opportunity.best_ask_yes,
            "best_ask_no": opportunity.best_ask_no,
            "estimated_profit_pct": opportunity.estimated_profit_pct,
            "estimated_profit_usdc": opportunity.estimated_profit_usdc,
            "depth_yes_usdc": opportunity.depth_yes_usdc,
            "depth_no_usdc": opportunity.depth_no_usdc,
            "detected_at": opportunity.detected_at.isoformat(),
        }, self._cfg.log_file)

        ok, reason = self._risk.can_trade(opportunity)
        if not ok:
            logger.debug(f"Skipped ({reason}): {opportunity.market.question[:40]}")
            return

        t0 = time.monotonic()
        try:
            trade = await self._execute(opportunity)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Execution exception: {exc}", exc_info=True)
            self._risk.record_failure()
            return

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._latencies_ms.append(elapsed_ms)
        self._trades_executed += 1
        self._risk.record_trade(trade)

        log_trade(trade.to_dict(), self._cfg.log_file)
        if self._monitor:
            self._monitor.record_trade(trade.to_dict())

        icons = {
            "filled": "[bold green]FILLED[/bold green]",
            "partial": "[bold red]PARTIAL — SINGLE LEG[/bold red]",
            "failed": "[red]FAILED[/red]",
            "dry_run": "[yellow]DRY RUN[/yellow]",
        }
        logger.info(
            f"{icons.get(trade.status, trade.status)} "
            f"{opportunity.market.question[:45]} | "
            f"pnl={format_usdc(trade.pnl_usdc)} | "
            f"{elapsed_ms:.0f}ms"
        )

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _execute(self, opportunity: Opportunity) -> Trade:
        m = opportunity.market

        # ── DRY RUN ──────────────────────────────────────────────────────────
        if self._cfg.dry_run or self._client is None:
            size = self._calc_size(opportunity)
            pnl = profit_after_fee(opportunity.pair_cost, 0.02) * size
            return Trade(
                opportunity=opportunity,
                yes_order_id=None,
                no_order_id=None,
                yes_fill_price=opportunity.best_ask_yes,
                no_fill_price=opportunity.best_ask_no,
                size_usdc=size,
                status="dry_run",
                executed_at=datetime.utcnow(),
                pnl_usdc=pnl,
            )

        # ── LIVE: re-fetch books to guard against stale data ─────────────────
        session = await self._get_session()
        fresh = await get_order_books_batch(session, [m.yes_token_id, m.no_token_id])
        yes_book = fresh.get(m.yes_token_id)
        no_book = fresh.get(m.no_token_id)

        if yes_book is None or no_book is None:
            raise RuntimeError("Could not re-fetch order books before execution")

        yes_ask = yes_book.best_ask
        no_ask = no_book.best_ask
        if yes_ask is None or no_ask is None:
            raise RuntimeError("Empty order book on re-fetch")

        fresh_cost = yes_ask.price + no_ask.price
        if not is_opportunity(fresh_cost, self._cfg.min_spread, 0.02):
            logger.debug(f"Opportunity evaporated (fresh cost={fresh_cost:.4f})")
            return Trade(
                opportunity=opportunity,
                yes_order_id=None, no_order_id=None,
                yes_fill_price=0, no_fill_price=0,
                size_usdc=0, status="failed",
                executed_at=datetime.utcnow(), pnl_usdc=0,
            )

        size = self._calc_size(
            opportunity,
            depth_yes=yes_book.ask_depth_usdc(yes_ask.price * 1.02),
            depth_no=no_book.ask_depth_usdc(no_ask.price * 1.02),
        )

        if size < m.min_order_size:
            raise RuntimeError(
                f"Computed size ${size:.2f} is below min_order_size ${m.min_order_size}"
            )

        # ── Submit YES FOK ────────────────────────────────────────────────────
        yes_id, yes_fill = await self._submit_fok(m.yes_token_id, size)
        if yes_id is None:
            self._risk.record_failure()
            return Trade(
                opportunity=opportunity,
                yes_order_id=None, no_order_id=None,
                yes_fill_price=0, no_fill_price=0,
                size_usdc=size, status="failed",
                executed_at=datetime.utcnow(), pnl_usdc=0,
            )

        # ── Submit NO FOK ─────────────────────────────────────────────────────
        no_id, no_fill = await self._submit_fok(m.no_token_id, size)
        if no_id is None:
            # Single-leg exposure — YES filled, NO did not
            pnl_estimate = profit_after_fee(yes_fill + no_ask.price, 0.02) * size
            return Trade(
                opportunity=opportunity,
                yes_order_id=yes_id, no_order_id=None,
                yes_fill_price=yes_fill, no_fill_price=0,
                size_usdc=size, status="partial",
                executed_at=datetime.utcnow(), pnl_usdc=pnl_estimate,
            )

        # ── Both legs filled ──────────────────────────────────────────────────
        actual_pair_cost = yes_fill + no_fill
        pnl = profit_after_fee(actual_pair_cost, 0.02) * size
        return Trade(
            opportunity=opportunity,
            yes_order_id=yes_id, no_order_id=no_id,
            yes_fill_price=yes_fill, no_fill_price=no_fill,
            size_usdc=size, status="filled",
            executed_at=datetime.utcnow(), pnl_usdc=pnl,
        )

    # ── FOK submission ────────────────────────────────────────────────────────

    async def _submit_fok(
        self,
        token_id: str,
        amount_usdc: float,
        retries: int = 1,
    ) -> tuple[Optional[str], float]:
        """
        Submit a FOK market order via the v2 SDK.
        Returns (order_id, fill_price) on success, (None, 0) on failure.
        """
        try:
            from py_clob_client_v2 import MarketOrderArgs, OrderType, Side  # type: ignore
        except ImportError:
            try:
                from py_clob_client.clob_types import MarketOrderArgs, OrderType  # type: ignore
                from py_clob_client.order_builder.constants import BUY  # type: ignore

                class Side:
                    BUY = BUY
            except ImportError:
                logger.error("No SDK available for order placement")
                return None, 0

        for attempt in range(retries + 1):
            try:
                resp = self._client.create_and_post_market_order(
                    order_args=MarketOrderArgs(
                        token_id=token_id,
                        amount=amount_usdc,
                        side=Side.BUY,
                    ),
                    order_type=OrderType.FOK,
                )

                order_id = (
                    resp.get("orderID")
                    or resp.get("order_id")
                    or resp.get("id")
                )
                fill_price = float(
                    resp.get("avgPrice")
                    or resp.get("price")
                    or resp.get("avg_price")
                    or 0
                )
                status = str(resp.get("status", "")).upper()

                if status in ("MATCHED", "FILLED") or order_id:
                    return order_id, fill_price

                logger.warning(f"FOK non-fill status={status!r} for {token_id[:12]}...")
                return None, 0

            except Exception as exc:
                err = str(exc).lower()
                if "429" in err or "rate limit" in err:
                    wait = 0.5 * (2 ** attempt)
                    logger.warning(f"Rate limited — sleeping {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                if "insufficient" in err or "balance" in err:
                    logger.error(f"Insufficient balance for {token_id[:12]}...: {exc}")
                    return None, 0
                if attempt < retries:
                    await asyncio.sleep(0.5)
                    continue
                logger.error(f"FOK order failed ({token_id[:12]}...): {exc}")
                return None, 0

        return None, 0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calc_size(
        self,
        opp: Opportunity,
        depth_yes: Optional[float] = None,
        depth_no: Optional[float] = None,
    ) -> float:
        dy = depth_yes if depth_yes is not None else opp.depth_yes_usdc
        dn = depth_no if depth_no is not None else opp.depth_no_usdc
        size = min(self._cfg.max_position_usdc, dy, dn)
        tick = opp.market.tick_size * max(opp.best_ask_yes, 0.01)
        return max(round_to_tick(size, tick), 0.0)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
