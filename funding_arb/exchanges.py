"""
Exchange connectivity via ccxt.

Exchanges:
  Binance, Bybit, OKX       — CEX with spot + linear perp
  Gate.io                    — CEX with strong altcoin selection
  Hyperliquid                — DEX perp-only; scanned for rate signals only.
                               To arb Hyperliquid rates: buy spot on a CEX,
                               short the perp on Hyperliquid manually.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

import ccxt

import config
from models import FundingRate, Position


# Exchanges without native spot trading — can scan rates but not auto-execute.
PERP_ONLY_EXCHANGES = {"hyperliquid"}


# ── Client factory ────────────────────────────────────────────────────────────

def build_exchanges() -> dict[str, Any]:
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

    if config.GATE_API_KEY:
        exchanges["gateio"] = ccxt.gateio({
            "apiKey": config.GATE_API_KEY,
            "secret": config.GATE_SECRET,
        })

    if config.HYPERLIQUID_WALLET and config.HYPERLIQUID_KEY:
        try:
            exchanges["hyperliquid"] = ccxt.hyperliquid({
                "walletAddress": config.HYPERLIQUID_WALLET,
                "privateKey": config.HYPERLIQUID_KEY,
            })
        except Exception:
            exchanges["hyperliquid"] = ccxt.hyperliquid()

    # Read-only fallbacks for any exchange without credentials (rate scanning)
    fallbacks = [
        ("binance",     ccxt.binance),
        ("bybit",       ccxt.bybit),
        ("okx",         ccxt.okx),
        ("gateio",      ccxt.gateio),
        ("hyperliquid", ccxt.hyperliquid),
    ]
    for name, cls in fallbacks:
        if name not in exchanges:
            try:
                exchanges[name] = cls()
            except Exception:
                pass

    return exchanges


# ── Funding rate scanning ─────────────────────────────────────────────────────

def fetch_funding_rates(exchange_name: str, ex: Any) -> list[FundingRate]:
    """Return all positive funding rates on a single exchange."""
    perp_only = exchange_name in PERP_ONLY_EXCHANGES
    rates: list[FundingRate] = []

    try:
        markets = ex.load_markets()
        perp_symbols = [
            s for s, m in markets.items()
            if m.get("type") in ("swap", "future")
            and m.get("linear")
            and "USDT" in s
            and s.split("/")[0] not in config.BLACKLIST_BASES
        ]

        if hasattr(ex, "fetch_funding_rates"):
            try:
                bulk = ex.fetch_funding_rates(perp_symbols[:200])
                for symbol, info in bulk.items():
                    r = _extract_rate(exchange_name, symbol, info, perp_only)
                    if r:
                        rates.append(r)
                return rates
            except Exception:
                pass  # fall through to per-symbol fetch

        # Per-symbol fallback (slower but universal)
        for symbol in perp_symbols[:120]:
            try:
                info = ex.fetch_funding_rate(symbol)
                r = _extract_rate(exchange_name, symbol, info, perp_only)
                if r:
                    rates.append(r)
                time.sleep(ex.rateLimit / 1000)
            except Exception:
                continue

    except Exception as exc:
        print(f"  [warn] {exchange_name} scan failed: {exc}")

    return rates


def fetch_all_funding_rates(exchanges: dict[str, Any]) -> list[FundingRate]:
    """Scan all exchanges in parallel, deduplicate, sort descending by rate."""
    all_rates: list[FundingRate] = []

    with ThreadPoolExecutor(max_workers=min(len(exchanges), 6)) as pool:
        futures = {
            pool.submit(fetch_funding_rates, name, ex): name
            for name, ex in exchanges.items()
        }
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                all_rates.extend(fut.result(timeout=50))
            except Exception as exc:
                print(f"  [warn] {name} scan timed out: {exc}")

    seen: dict[str, FundingRate] = {}
    for r in all_rates:
        key = f"{r.exchange}:{r.symbol}"
        if key not in seen or r.rate_8h > seen[key].rate_8h:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: r.rate_8h, reverse=True)


def _extract_rate(
    exchange: str, symbol: str, info: dict, perp_only: bool = False
) -> Optional[FundingRate]:
    try:
        rate = float(info.get("fundingRate") or info.get("rate") or 0)
        if rate <= 0:
            return None
        mark = float(info.get("markPrice") or info.get("mark") or 0)
        if config.MIN_MARK_PRICE and mark and mark < config.MIN_MARK_PRICE:
            return None
        base = symbol.split("/")[0]
        if base in config.BLACKLIST_BASES:
            return None
        next_ts = info.get("fundingDatetime") or info.get("nextFundingDatetime")
        next_dt = (
            datetime.fromisoformat(next_ts.replace("Z", "+00:00"))
            if next_ts else None
        )
        return FundingRate(
            exchange=exchange,
            symbol=symbol,
            base=base,
            rate_8h=rate,
            apy=config.rate_to_apy(rate),
            next_funding=next_dt,
            mark_price=mark,
            perp_only=perp_only,
        )
    except Exception:
        return None


# ── Spot market validation ────────────────────────────────────────────────────

def has_spot_market(ex: Any, base: str) -> bool:
    try:
        markets = getattr(ex, "markets", None) or ex.load_markets()
        m = markets.get(f"{base}/USDT")
        if m is None:
            return False
        mtype = m.get("type")
        # Some exchanges leave type=None for spot markets; accept both.
        return mtype in ("spot", None)
    except Exception:
        # Can't verify — assume True and let the order placement handle failure.
        return True


# ── Order placement ───────────────────────────────────────────────────────────

def get_spot_symbol(exchange_name: str, base: str) -> str:
    return f"{base}/USDT"


def place_spot_buy(ex: Any, base: str, usdc_amount: float) -> dict:
    symbol = get_spot_symbol(ex.id, base)
    ticker = ex.fetch_ticker(symbol)
    price = ticker["ask"]
    qty   = ex.amount_to_precision(symbol, usdc_amount / price)
    return ex.create_market_buy_order(symbol, float(qty))


def place_perp_short(ex: Any, perp_symbol: str, usdc_amount: float) -> dict:
    ticker = ex.fetch_ticker(perp_symbol)
    price  = ticker["ask"]
    qty    = ex.amount_to_precision(perp_symbol, usdc_amount / price)
    return ex.create_market_sell_order(
        perp_symbol, float(qty), params={"reduceOnly": False}
    )


def close_spot_position(ex: Any, base: str, qty: float) -> dict:
    symbol  = get_spot_symbol(ex.id, base)
    qty_str = ex.amount_to_precision(symbol, qty)
    return ex.create_market_sell_order(symbol, float(qty_str))


def close_perp_position(ex: Any, perp_symbol: str, qty: float) -> dict:
    qty_str = ex.amount_to_precision(perp_symbol, qty)
    return ex.create_market_buy_order(
        perp_symbol, float(qty_str), params={"reduceOnly": True}
    )


def fetch_current_funding_rate(ex: Any, perp_symbol: str) -> Optional[float]:
    try:
        info = ex.fetch_funding_rate(perp_symbol)
        return float(info.get("fundingRate") or 0)
    except Exception:
        return None


def set_leverage(ex: Any, symbol: str, leverage: int) -> None:
    """Set leverage for a perp symbol before opening a short. Silent if unsupported."""
    try:
        ex.set_leverage(leverage, symbol)
    except Exception:
        pass  # Not all exchanges require or support explicit leverage setting


def fetch_margin_ratio(ex: Any, symbol: str) -> Optional[float]:
    """
    Return the margin health ratio for a short position on `symbol`.

    Uses CCXT-normalised `marginRatio` (maintenanceMargin / collateral).
    Higher values mean closer to liquidation; 1.0 = liquidation threshold.
    Returns None if the exchange doesn't expose this data.
    """
    try:
        positions = ex.fetch_positions([symbol])
        for p in positions:
            if p.get("symbol") != symbol:
                continue
            mr = p.get("marginRatio")
            if mr is not None:
                return float(mr)
            # Fallback: compute from components if raw fields are available.
            maint  = float(p.get("maintenanceMargin") or 0)
            margin = float(p.get("initialMargin") or p.get("collateral") or 0)
            if margin > 0:
                return maint / margin
    except Exception:
        pass
    return None
