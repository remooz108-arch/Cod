from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    private_key: str
    funder_address: str
    signature_type: int = 2
    min_spread_bps: int = 50
    max_position_usdc: float = 500.0
    max_total_deployed_usdc: float = 5000.0
    daily_loss_limit_usdc: float = 100.0
    scan_interval_ms: int = 500
    use_websocket: bool = True
    dry_run: bool = True
    log_file: str = "trades.jsonl"
    max_concurrent_markets: int = 50
    cooldown_after_failures: int = 5
    min_market_liquidity_usdc: float = 100.0

    @property
    def min_spread(self) -> float:
        return self.min_spread_bps / 10_000.0


def load_config(env_path: str = ".env") -> Config:
    load_dotenv(env_path, override=False)

    private_key = os.getenv("POLY_PRIVATE_KEY", "")
    funder_address = os.getenv("POLY_FUNDER_ADDRESS", "")
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    errors: list[str] = []
    if not private_key or private_key.startswith("0x_your"):
        if not dry_run:
            errors.append("POLY_PRIVATE_KEY is required for live trading")
        else:
            private_key = ""
    if not funder_address or funder_address.startswith("0x_your"):
        if not dry_run:
            errors.append("POLY_FUNDER_ADDRESS is required for live trading")
        else:
            funder_address = ""

    if errors:
        raise ValueError("Configuration errors:\n  " + "\n  ".join(errors))

    return Config(
        private_key=private_key,
        funder_address=funder_address,
        signature_type=int(os.getenv("POLY_SIGNATURE_TYPE", "2")),
        min_spread_bps=int(os.getenv("MIN_SPREAD_BPS", "50")),
        max_position_usdc=float(os.getenv("MAX_POSITION_USDC", "500")),
        max_total_deployed_usdc=float(os.getenv("MAX_TOTAL_DEPLOYED_USDC", "5000")),
        daily_loss_limit_usdc=float(os.getenv("DAILY_LOSS_LIMIT_USDC", "100")),
        scan_interval_ms=int(os.getenv("SCAN_INTERVAL_MS", "500")),
        use_websocket=os.getenv("USE_WEBSOCKET", "true").lower() == "true",
        dry_run=dry_run,
        log_file=os.getenv("LOG_FILE", "trades.jsonl"),
        max_concurrent_markets=int(os.getenv("MAX_CONCURRENT_MARKETS", "50")),
        cooldown_after_failures=int(os.getenv("COOLDOWN_AFTER_FAILURES", "5")),
        min_market_liquidity_usdc=float(os.getenv("MIN_MARKET_LIQUIDITY_USDC", "100")),
    )


def print_config_summary(config: Config) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    t = Table(title="Bot Configuration", show_header=False, border_style="cyan", padding=(0, 2))
    t.add_column("Setting", style="dim", min_width=28)
    t.add_column("Value", style="white")

    mode = "[bold red]LIVE TRADING[/bold red]" if not config.dry_run else "[bold yellow]DRY RUN (no orders)[/bold yellow]"
    funder_display = (
        f"{config.funder_address[:8]}...{config.funder_address[-6:]}"
        if len(config.funder_address) > 14
        else (config.funder_address or "[dim]not set[/dim]")
    )

    t.add_row("Mode", mode)
    t.add_row("Funder Address", funder_display)
    t.add_row("Signature Type", str(config.signature_type))
    t.add_row("Min Spread", f"{config.min_spread_bps} bps ({config.min_spread:.4f})")
    t.add_row("Max Position", f"${config.max_position_usdc:,.2f} USDC")
    t.add_row("Max Total Deployed", f"${config.max_total_deployed_usdc:,.2f} USDC")
    t.add_row("Daily Loss Limit", f"${config.daily_loss_limit_usdc:,.2f} USDC")
    t.add_row("Scan Interval", f"{config.scan_interval_ms} ms")
    t.add_row("WebSocket Mode", "enabled" if config.use_websocket else "disabled (REST only)")
    t.add_row("Max Markets", str(config.max_concurrent_markets))
    t.add_row("Min Liquidity", f"${config.min_market_liquidity_usdc:,.2f} USDC per side")
    t.add_row("Cooldown on Failures", f"{config.cooldown_after_failures}s after 3 failures")
    t.add_row("Log File", config.log_file)

    console.print(t)
