"""Structured logging: Rich console + JSONL file with 100 MB rotation."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)
_LOG_FILE_HANDLE: Path | None = None


def setup_logging(log_file: str = "trades.jsonl", level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=_console,
                rich_tracebacks=True,
                show_path=False,
                markup=True,
                log_time_format="[%X]",
            )
        ],
    )
    # Suppress noisy third-party loggers
    for name in ("aiohttp.access", "websockets.server", "websockets.protocol"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _rotate_if_needed(path: Path) -> None:
    if path.exists() and path.stat().st_size > 100 * 1024 * 1024:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path.rename(path.with_stem(f"{path.stem}_{stamp}"))


def _append_jsonl(record: dict, log_file: str) -> None:
    path = Path(log_file)
    _rotate_if_needed(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_trade(trade_dict: dict[str, Any], log_file: str = "trades.jsonl") -> None:
    _append_jsonl(trade_dict, log_file)


def log_opportunity(opp_dict: dict[str, Any], log_file: str = "trades.jsonl") -> None:
    _append_jsonl({**opp_dict, "_type": "opportunity"}, log_file)
