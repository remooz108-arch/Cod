"""
Exchange connectivity via ccxt.

Provides:
  - build_exchanges()         → dict of authenticated ccxt instances
  - fetch_all_funding_rates() → list[FundingRate] across all exchanges
  - place_spot_order()        → market buy on spot
  - place_perp_order()        → market sell (short) on perp
  - fetch_position_funding()  → check how much funding has been paid/received
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import ccxt

import config
from models import FundingRate, Position


# ── Client factory ────────────────────────────────────────────────────────────

def build_exchanges() -> dict[str, Any]:
    """Return authenticated ccxt exchange objects for configured exchanges."""
    exchanges: dict[str, Any] = {}

    if config.BINANCE_API_KEY:
        exchanges["binance"] = ccxt.binance({
            "apiKey": config.BINANCE_API_KEY,
            "secret": config.BINANCE_SECRET,
            "options": {"defaultType": "future"},
        })

    if config.BYBIT_API_KEY:
        exchanges["bybit"] = ccxt.bybit({
            "apiKey": config.BYBIT_API_KEY,
            "secret": config.BYBIT_SECRET,
        })

    if config.OKX_API_KEY:
        exchanges["okx"] = ccxt.okx({
            "apiKey": config.OKX_API_KEY,
            "secret": config.OKX_SECRET,
            "password": config.OKX_PASSPHRASE,
        })

    # Read-only instances for exchanges without keys (for scanning)
    for name, cls in [("binance", ccxt.binance), ("bybit", ccxt.bybit), ("okx", ccxt.okx)]:
        if name not in exchanges:
            exchanges[name] = cls()

    return exchanges


# ── Funding rate scanning ─────────────────────────────────────────────────────

def fetch_funding_rates(exchange_name: str, ex: Any) -> list[FundingRate]:
    """Return all positive funding rates on a single exchange."""
    rates: list[FundingRate] = []
    try:
        markets = ex.load_markets()
        perp_symbols = [
            s for s, m in markets.items()
            if m.get("type") in ("swap", "future") and m.get("linear") and "USDT" in s
        ]

        # ccxt has fetch_funding_rates (plural) on some exchanges
        if hasattr(ex, "fetch_funding_rates"):
            try:
                bulk = ex.fetch_funding_rates(perp_symbols[:100])
                for symbol, info in bulk.items():
                    rate = _extract_rate(exchange_name, symbol, info)
                    if rate is not None:
                        rates.append(rate)
                return rates
            except Exception:
                pass  # fall through to per-symbol fetch

        # Per-symbol fallback
        for symbol in perp_symbols[:50]:
            try:
                info = ex.fetch_funding_rate(symbol)
                rate = _extract_rate(exchange_name, symbol, info)
                if rate is not None:
                    rates.append(rate)
                time.sleep(ex.rateLimit / 1000)
            except Exception:
                continue

    except Exception as exc:
        print(f"  [warn] {exchange_name} funding rate fetch failed: {exc}")

    return rates


def fetch_all_funding_rates(exchanges: dict[str, Any]) -> list[FundingRate]:
    all_rates: list[FundingRate] = []
    for name, ex in exchanges.items():
        rates = fetch_funding_rates(name, ex)
        all_rates.extend(rates)
    # Deduplicate by (exchange, symbol), keep highest rate if duplicates
    seen: dict[str, FundingRate] = {}
    for r in all_rates:
        key = f"{r.exchange}:{r.symbol}"
        if key not in seen or r.rate_8h > seen[key].rate_8h:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: r.rate_8h, reverse=True)


def _extract_rate(exchange: str, symbol: str, info: dict) -> Optional[FundingRate]:
    try:
        rate = float(info.get("fundingRate") or info.get("rate") or 0)
        if rate <= 0:
            return None
        mark = float(info.get("markPrice") or info.get("mark") or 0)
        base = symbol.split("/")[0]
        next_ts = info.get("fundingDatetime") or info.get("nextFundingDatetime")
        next_dt = datetime.fromisoformat(next_ts.replace("Z", "+00:00")) if next_ts else None

        return FundingRate(
            exchange=exchange,
            symbol=symbol,
            base=base,
            rate_8h=rate,
            apy=config.rate_to_apy(rate),
            next_funding=next_dt,
            mark_price=mark,
        )
    except Exception:
        return None


# ── Order placement ───────────────────────────────────────────────────────────

def get_spot_symbol(exchange_name: str, base: str) -> str:
    return f"{base}/USDT"


def place_spot_buy(ex: Any, base: str, usdc_amount: float) -> dict:
    """Market buy `usdc_amount` USDC worth of `base` on spot."""
    symbol = get_spot_symbol(ex.id, base)
    ticker = ex.fetch_ticker(symbol)
    price = ticker["ask"]
    qty = usdc_amount / price
    qty = ex.amount_to_precision(symbol, qty)
    return ex.create_market_buy_order(symbol, float(qty))


def place_perp_short(ex: Any, perp_symbol: str, usdc_amount: float) -> dict:
    """Market short `usdc_amount` USDC worth of `perp_symbol`."""
    ticker = ex.fetch_ticker(perp_symbol)
    price = ticker["ask"]
    qty = usdc_amount / price
    qty = ex.amount_to_precision(perp_symbol, qty)
    return ex.create_market_sell_order(perp_symbol, float(qty), params={"reduceOnly": False})


def close_spot_position(ex: Any, base: str, qty: float) -> dict:
    """Market sell `qty` of `base` to close spot leg."""
    symbol = get_spot_symbol(ex.id, base)
    qty_str = ex.amount_to_precision(symbol, qty)
    return ex.create_market_sell_order(symbol, float(qty_str))


def close_perp_position(ex: Any, perp_symbol: str, qty: float) -> dict:
    """Market buy back `qty` to close the short perp leg."""
    qty_str = ex.amount_to_precision(perp_symbol, qty)
    return ex.create_market_buy_order(perp_symbol, float(qty_str), params={"reduceOnly": True})


def fetch_current_funding_rate(ex: Any, perp_symbol: str) -> Optional[float]:
    try:
        info = ex.fetch_funding_rate(perp_symbol)
        return float(info.get("fundingRate") or 0)
    except Exception:
        return None
