"""
Rich live console dashboard — refreshes every second.
Runs as an independent asyncio task; never blocks the trading path.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from .executor import Executor
    from .risk import RiskManager
    from .scanner import Scanner

logger = logging.getLogger(__name__)
console = Console()

_DIVIDER = Text("─" * 58, style="dim")


class Monitor:
    def __init__(
        self,
        risk_mgr: "RiskManager",
        scanner: "Scanner",
        executor: "Executor",
        dry_run: bool = True,
    ):
        self._risk = risk_mgr
        self._scanner = scanner
        self._executor = executor
        self._dry_run = dry_run
        self._start_time = datetime.utcnow()
        self._running = False
        self._recent_trades: list[dict] = []

    def record_trade(self, trade_dict: dict) -> None:
        self._recent_trades.append(trade_dict)
        if len(self._recent_trades) > 20:
            self._recent_trades.pop(0)

    async def run(self) -> None:
        self._running = True
        try:
            with Live(
                self._render(),
                console=console,
                refresh_per_second=1,
                screen=False,
                vertical_overflow="visible",
            ) as live:
                while self._running:
                    try:
                        live.update(self._render())
                    except Exception:
                        pass
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug(f"Monitor render error (non-fatal): {exc}")

    def stop(self) -> None:
        self._running = False

    def _render(self) -> Panel:
        now = datetime.utcnow()
        up = now - self._start_time
        h, rem = divmod(int(up.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m:02d}m {s:02d}s"

        scanner_stats = self._scanner.stats
        risk_stats = self._risk.get_stats()

        mode_tag = (
            "[bold red on white] LIVE [/bold red on white]"
            if not self._dry_run
            else "[bold yellow on black] DRY RUN [/bold yellow on black]"
        )

        # ── Section: header ───────────────────────────────────────────
        header = Table.grid(padding=(0, 1))
        header.add_column(justify="left")
        header.add_column(justify="right")
        header.add_row(
            f"[bold cyan]POLYMARKET ARB BOT[/bold cyan]  {mode_tag}",
            f"[dim]{now.strftime('%Y-%m-%d %H:%M:%S UTC')}[/dim]",
        )

        # ── Section: activity ─────────────────────────────────────────
        fill_rate = risk_stats.get("fill_rate", 0)
        act = Table.grid(padding=(0, 2))
        act.add_column(style="dim", min_width=22)
        act.add_column(style="white", min_width=12)
        act.add_column(style="dim", min_width=22)
        act.add_column(style="white")
        act.add_row("Uptime", uptime_str, "Markets Scanned", f"{scanner_stats.get('markets_scanned', 0):,}")
        act.add_row("Opportunities Found", str(self._executor.opportunities_seen), "Trades Executed", str(self._executor.trades_executed))
        act.add_row("Fill Rate", f"{fill_rate * 100:.1f}%", "Avg Latency", f"{self._executor.avg_latency_ms:.0f}ms")

        # ── Section: capital ──────────────────────────────────────────
        deployed = risk_stats.get("total_deployed", 0)
        daily_pnl = risk_stats.get("daily_pnl", 0)
        total_pnl = risk_stats.get("total_pnl", 0)
        open_pos = risk_stats.get("open_positions", 0)
        single_leg = risk_stats.get("single_leg_warnings", 0)

        d_color = "green" if daily_pnl >= 0 else "red"
        t_color = "green" if total_pnl >= 0 else "red"

        cap = Table.grid(padding=(0, 2))
        cap.add_column(style="dim", min_width=22)
        cap.add_column(style="white", min_width=12)
        cap.add_column(style="dim", min_width=22)
        cap.add_column(style="white")
        cap.add_row(
            "Capital Deployed",
            f"${deployed:,.2f}",
            "Daily P&L",
            f"[{d_color}]${daily_pnl:+,.2f}[/{d_color}]",
        )
        cap.add_row(
            "Open Positions",
            str(open_pos),
            "Total P&L",
            f"[{t_color}]${total_pnl:+,.2f}[/{t_color}]",
        )
        if single_leg:
            cap.add_row(
                "[bold red]⚠ Single-Leg Warnings[/bold red]",
                f"[bold red]{single_leg}[/bold red]",
                "", "",
            )

        # ── Section: recent trades ────────────────────────────────────
        trades_tbl = Table(
            show_header=True,
            header_style="bold dim",
            box=None,
            padding=(0, 1),
        )
        trades_tbl.add_column("Time", width=8, no_wrap=True)
        trades_tbl.add_column("Market", max_width=36, no_wrap=True)
        trades_tbl.add_column("P&L", justify="right", width=8)
        trades_tbl.add_column("Status", width=12)

        for t in reversed(self._recent_trades[-8:]):
            status = t.get("status", "")
            pnl = t.get("pnl_usdc", 0)
            c = {"filled": "green", "dry_run": "yellow", "partial": "red", "failed": "red"}.get(status, "white")
            ts_raw = t.get("executed_at", "")
            ts = ts_raw[11:19] if len(ts_raw) >= 19 else ts_raw[:8]
            trades_tbl.add_row(
                ts,
                t.get("question", "")[:36],
                f"[{c}]${pnl:+.2f}[/{c}]",
                f"[{c}]{status.upper()[:10]}[/{c}]",
            )

        # ── Assemble ──────────────────────────────────────────────────
        grid = Table.grid()
        grid.add_column()
        grid.add_row(header)
        grid.add_row(_DIVIDER)
        grid.add_row(act)
        grid.add_row(_DIVIDER)
        grid.add_row(cap)
        grid.add_row(_DIVIDER)
        grid.add_row(Text("RECENT TRADES", style="bold dim"))
        if self._recent_trades:
            grid.add_row(trades_tbl)
        else:
            grid.add_row(Text("  (none yet)", style="dim"))

        return Panel(grid, title="[bold cyan]Polymarket Binary Arbitrage Bot[/bold cyan]", border_style="cyan")
