"""
Polymarket Binary Arbitrage Bot — entry point.

Usage:
    python -m src.main                  # dry-run (default)
    python -m src.main --live           # override to live trading
    python -m src.main --scan-only      # detect opportunities, never trade
    python -m src.main --no-dashboard   # plain log output (headless servers)
    python -m src.main --config path/to/.env
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Polymarket binary arbitrage bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="Log opportunities only, no orders (default)")
    mode.add_argument("--live", dest="live", action="store_true", help="Submit real orders (overrides DRY_RUN env var)")
    mode.add_argument("--scan-only", dest="scan_only", action="store_true", help="Detect mispricings and log them, never call executor")
    p.add_argument("--no-dashboard", dest="no_dashboard", action="store_true", help="Disable Rich UI (headless / log-only mode)")
    p.add_argument("--config", dest="config", default=".env", metavar="PATH", help="Path to .env file (default: .env)")
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    from .auth import get_sdk_version, health_check, init_client
    from .config import load_config, print_config_summary
    from .executor import Executor
    from .logger import setup_logging
    from .monitor import Monitor
    from .orderbook import WebSocketManager
    from .risk import RiskManager
    from .scanner import Scanner

    # ── Config ────────────────────────────────────────────────────────
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(f"\n[ERROR] {exc}\n", file=sys.stderr)
        sys.exit(1)

    # CLI flags override env
    if args.live:
        config.dry_run = False
    elif args.dry_run or args.scan_only:
        config.dry_run = True

    setup_logging(config.log_file)
    print_config_summary(config)

    logger.info(f"SDK: {get_sdk_version()}")

    # ── Auth ──────────────────────────────────────────────────────────
    client = init_client(config)
    if client is not None and not config.dry_run:
        if not health_check(client):
            logger.error("CLOB health check failed. Exiting.")
            sys.exit(1)
    elif client is not None:
        health_check(client)

    # ── Components ────────────────────────────────────────────────────
    risk_mgr = RiskManager(config)

    ws_manager: Optional[WebSocketManager] = None
    if config.use_websocket:
        ws_manager = WebSocketManager()

    scanner = Scanner(config, ws_manager)
    executor = Executor(client, config, risk_mgr)
    monitor: Optional[Monitor] = None

    if not args.no_dashboard:
        monitor = Monitor(risk_mgr, scanner, executor, dry_run=config.dry_run)
        executor._monitor = monitor

    # ── Callback ──────────────────────────────────────────────────────
    if args.scan_only:
        async def callback(opp):
            pass
    else:
        callback = executor.on_opportunity

    # ── Shutdown handling ─────────────────────────────────────────────
    shutdown_event = asyncio.Event()

    def _shutdown(*_):
        logger.info("Shutdown signal received — stopping gracefully...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler for all signals
            signal.signal(sig, _shutdown)

    # ── Launch tasks ──────────────────────────────────────────────────
    tasks: list[asyncio.Task] = []

    async def run_with_shutdown(coro):
        task = asyncio.ensure_future(coro)
        tasks.append(task)
        await shutdown_event.wait()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    coroutines = [
        scanner.run(callback),
        risk_mgr.daily_reset_loop(),
    ]
    if ws_manager is not None:
        coroutines.append(ws_manager.run())
    if monitor is not None:
        coroutines.append(monitor.run())

    # Run all coroutines; cancel all on shutdown
    runners = [asyncio.ensure_future(c) for c in coroutines]

    async def wait_for_shutdown():
        await shutdown_event.wait()
        for t in runners:
            t.cancel()
        results = await asyncio.gather(*runners, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                logger.debug(f"Task exit: {r}")

    try:
        await asyncio.gather(
            wait_for_shutdown(),
            *runners,
            return_exceptions=True,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Cleaning up...")
        scanner.stop()
        if ws_manager:
            ws_manager.stop()
        if monitor:
            monitor.stop()
        await executor.close()
        logger.info("Bot stopped.")

        stats = risk_mgr.get_stats()
        logger.info(
            f"Session summary — "
            f"trades={stats['total_trades']} "
            f"filled={stats['filled_trades']} "
            f"daily_pnl=${stats['daily_pnl']:+.2f} "
            f"total_pnl=${stats['total_pnl']:+.2f}"
        )


def cli_main() -> None:
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli_main()
