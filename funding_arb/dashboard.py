"""Rich terminal dashboard — live updating every second."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from risk import RiskManager

console = Console()
_DIVIDER = Text("─" * 66, style="dim")


def render(
    risk: "RiskManager",
    top_rates: list,
    scan_count: int,
    start_time: datetime,
    live_mode: bool,
) -> Panel:
    now = datetime.utcnow()
    up = now - start_time
    h, rem = divmod(int(up.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    uptime = f"{h}h {m:02d}m {s:02d}s"

    stats = risk.get_stats()
    mode_tag = "[bold red] LIVE [/bold red]" if live_mode else "[bold yellow] DRY-RUN [/bold yellow]"

    # Header row
    header = Table.grid(padding=(0, 1))
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row(
        f"[bold cyan]FUNDING RATE ARBITRAGE BOT[/bold cyan]  {mode_tag}",
        f"[dim]{now.strftime('%H:%M:%S UTC')}  uptime {uptime}[/dim]",
    )

    # Summary stats
    pnl = stats["total_funding_earned"]
    pnl_color = "green" if pnl >= 0 else "red"
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="dim", min_width=22)
    summary.add_column(style="white", min_width=10)
    summary.add_column(style="dim", min_width=22)
    summary.add_column(style="white")
    summary.add_row(
        "Open Positions",  str(stats["open_positions"]),
        "Total Deployed",  f"${stats['total_deployed']:,.2f}",
    )
    summary.add_row(
        "Funding Earned",  f"[{pnl_color}]${pnl:+,.4f}[/{pnl_color}]",
        "Scans Done",      str(scan_count),
    )
    if stats["avg_apy"]:
        summary.add_row(
            "Avg Realised APY", f"[green]{stats['avg_apy']:.1f}%[/green]",
            "", "",
        )

    # Open positions table
    pos_table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
    pos_table.add_column("Asset",    width=6)
    pos_table.add_column("Exchange", width=9)
    pos_table.add_column("Size",     width=8, justify="right")
    pos_table.add_column("Rate/8h",  width=9, justify="right")
    pos_table.add_column("APY",      width=8, justify="right")
    pos_table.add_column("Earned",   width=9, justify="right")
    pos_table.add_column("Periods",  width=7, justify="right")
    pos_table.add_column("Opened",   width=10)

    for pos in risk.open_positions():
        import config as _cfg
        apy_str = f"{pos.apy_realised:.1f}%" if pos.funding_periods > 0 else f"~{_cfg.rate_to_apy(pos.last_rate_8h):.0f}%"
        pos_table.add_row(
            pos.base,
            pos.exchange,
            f"${pos.size_usdc:.0f}",
            f"{pos.last_rate_8h:.4%}",
            f"[green]{apy_str}[/green]",
            f"${pos.funding_collected:.4f}",
            str(pos.funding_periods),
            pos.opened_at.strftime("%m/%d %H:%M"),
        )

    # Top funding rates
    rate_table = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 1))
    rate_table.add_column("Exchange", width=9)
    rate_table.add_column("Asset",    width=8)
    rate_table.add_column("Rate/8h",  width=9, justify="right")
    rate_table.add_column("APY",      width=10, justify="right")
    rate_table.add_column("Mark $",   width=12, justify="right")

    for r in top_rates[:8]:
        apy_color = "green" if r.apy >= 50 else "yellow" if r.apy >= 20 else "white"
        rate_table.add_row(
            r.exchange,
            r.base,
            f"{r.rate_8h:.4%}",
            f"[{apy_color}]{r.apy:.1f}%[/{apy_color}]",
            f"${r.mark_price:,.2f}" if r.mark_price else "n/a",
        )

    grid = Table.grid()
    grid.add_column()
    grid.add_row(header)
    grid.add_row(_DIVIDER)
    grid.add_row(summary)
    grid.add_row(_DIVIDER)
    grid.add_row(Text("OPEN POSITIONS", style="bold dim"))
    grid.add_row(pos_table if risk.open_positions() else Text("  (none)", style="dim"))
    grid.add_row(_DIVIDER)
    grid.add_row(Text("TOP FUNDING RATES (live)", style="bold dim"))
    grid.add_row(rate_table if top_rates else Text("  (scanning...)", style="dim"))

    return Panel(grid, title="[bold cyan]Funding Rate Arbitrage[/bold cyan]", border_style="cyan")


class Dashboard:
    def __init__(self, risk: "RiskManager", live_mode: bool):
        self._risk = risk
        self._live_mode = live_mode
        self._top_rates: list = []
        self._scan_count = 0
        self._start_time = datetime.utcnow()
        self._running = False
        self._thread: threading.Thread | None = None

    def update(self, top_rates: list, scan_count: int) -> None:
        self._top_rates = top_rates
        self._scan_count = scan_count

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        with Live(
            render(self._risk, self._top_rates, self._scan_count, self._start_time, self._live_mode),
            console=console,
            refresh_per_second=1,
            screen=False,
        ) as live:
            while self._running:
                live.update(render(
                    self._risk, self._top_rates, self._scan_count,
                    self._start_time, self._live_mode,
                ))
                time.sleep(1)
