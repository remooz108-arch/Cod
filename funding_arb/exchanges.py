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

    if config.MEXC_API_KEY:
        exchanges["mexc"] = ccxt.mexc({
            "apiKey": config.MEXC_API_KEY,
            "secret": config.MEXC_SECRET,
        })

    if config.BITGET_API_KEY:
        exchanges["bitget"] = ccxt.bitget({
            "apiKey": config.BITGET_API_KEY,
            "secret": config.BITGET_SECRET,
            "password": config.BITGET_PASSPHRASE,
        })

    # Read-only fallbacks for any exchange without credentials (rate scanning)
    fallbacks = [
        ("binance",     ccxt.binance),
        ("bybit",       ccxt.bybit),
        ("okx",         ccxt.okx),
        ("gateio",      ccxt.gateio),
        ("hyperliquid", ccxt.hyperliquid),
        ("mexc",        ccxt.mexc),
        ("bitget",      ccxt.bitget),
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
        if rate == 0:
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


def fetch_available_balance(ex: Any, quote: str = "USDT") -> Optional[float]:
    """
    Return free (available) quote-currency balance on an exchange, or None if
    it can't be determined. Used for balance-aware position sizing.
    """
    try:
        bal = ex.fetch_balance()
        free = bal.get("free", {})
        # Try USDT first, then USDC as a fallback quote.
        for q in (quote, "USDC", "USD"):
            if q in free and free[q] is not None:
                return float(free[q])
    except Exception:
        pass
    return None


def set_leverage(ex: Any, symbol: str, leverage: int) -> None:
    """Set leverage for a perp symbol before opening a short. Silent if unsupported."""
    try:
        ex.set_leverage(leverage, symbol)
    except Exception:
        pass  # Not all exchanges require or support explicit leverage setting


# ── Maker-order helpers ───────────────────────────────────────────────────────

def _await_fill(ex: Any, order_id: str, symbol: str, fill_timeout: int) -> Optional[dict]:
    """Poll until an order is filled or the timeout expires. Returns filled order or None."""
    deadline = time.time() + fill_timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            o = ex.fetch_order(order_id, symbol)
        except Exception:
            return None
        status = o.get("status", "")
        if status == "closed":
            return o
        if status in ("canceled", "rejected", "expired"):
            return None
    try:
        ex.cancel_order(order_id, symbol)
    except Exception:
        pass
    return None


def place_spot_buy_maker(ex: Any, base: str, usdc_amount: float, fill_timeout: int = 20) -> dict:
    """Post-only limit buy at best bid; falls back to market if not filled in time."""
    symbol = get_spot_symbol(ex.id, base)
    try:
        book  = ex.fetch_order_book(symbol, limit=5)
        bids  = book.get("bids", [])
        if bids:
            price = float(bids[0][0])
            qty   = float(ex.amount_to_precision(symbol, usdc_amount / price))
            order = ex.create_limit_buy_order(
                symbol, qty, price, params={"postOnly": True}
            )
            result = _await_fill(ex, order["id"], symbol, fill_timeout)
            if result:
                return result
    except Exception:
        pass
    return place_spot_buy(ex, base, usdc_amount)


def place_perp_short_maker(ex: Any, perp_symbol: str, usdc_amount: float, fill_timeout: int = 20) -> dict:
    """Post-only limit short at best ask; falls back to market if not filled in time."""
    try:
        book  = ex.fetch_order_book(perp_symbol, limit=5)
        asks  = book.get("asks", [])
        if asks:
            price = float(asks[0][0])
            qty   = float(ex.amount_to_precision(perp_symbol, usdc_amount / price))
            order = ex.create_limit_sell_order(
                perp_symbol, qty, price,
                params={"postOnly": True, "reduceOnly": False},
            )
            result = _await_fill(ex, order["id"], perp_symbol, fill_timeout)
            if result:
                return result
    except Exception:
        pass
    return place_perp_short(ex, perp_symbol, usdc_amount)


def close_spot_position_maker(ex: Any, base: str, qty: float, fill_timeout: int = 15) -> dict:
    """Post-only limit sell to close spot; falls back to market if not filled in time."""
    symbol = get_spot_symbol(ex.id, base)
    try:
        book  = ex.fetch_order_book(symbol, limit=5)
        asks  = book.get("asks", [])
        if asks:
            price   = float(asks[0][0])
            qty_str = float(ex.amount_to_precision(symbol, qty))
            order   = ex.create_limit_sell_order(
                symbol, qty_str, price, params={"postOnly": True}
            )
            result = _await_fill(ex, order["id"], symbol, fill_timeout)
            if result:
                return result
    except Exception:
        pass
    return close_spot_position(ex, base, qty)


def close_perp_position_maker(ex: Any, perp_symbol: str, qty: float, fill_timeout: int = 15) -> dict:
    """Post-only limit buy-back to close perp; falls back to market if not filled in time."""
    try:
        book  = ex.fetch_order_book(perp_symbol, limit=5)
        bids  = book.get("bids", [])
        if bids:
            price   = float(bids[0][0])
            qty_str = float(ex.amount_to_precision(perp_symbol, qty))
            order   = ex.create_limit_buy_order(
                perp_symbol, qty_str, price,
                params={"postOnly": True, "reduceOnly": True},
            )
            result = _await_fill(ex, order["id"], perp_symbol, fill_timeout)
            if result:
                return result
    except Exception:
        pass
    return close_perp_position(ex, perp_symbol, qty)


def place_spot_short(ex: Any, base: str, usdc_amount: float) -> dict:
    """Open a cross-margin short on spot for inverse funding harvesting."""
    symbol = get_spot_symbol(ex.id, base)
    ticker = ex.fetch_ticker(symbol)
    # Use ask (or last as fallback) for notional sizing — consistent with buy-side
    # and avoids None on thin markets where bid may not be populated.
    price  = ticker.get("ask") or ticker.get("last") or ticker["bid"]
    qty    = ex.amount_to_precision(symbol, usdc_amount / price)
    return ex.create_market_sell_order(
        symbol, float(qty), params={"marginMode": "cross", "type": "margin"}
    )


def close_spot_short(ex: Any, base: str, qty: float) -> dict:
    """Buy back to close a margin short position."""
    symbol  = get_spot_symbol(ex.id, base)
    qty_str = ex.amount_to_precision(symbol, qty)
    return ex.create_market_buy_order(
        symbol, float(qty_str), params={"marginMode": "cross", "type": "margin"}
    )


def place_perp_long(ex: Any, perp_symbol: str, usdc_amount: float) -> dict:
    """Open a long perp to pair with a margin spot short."""
    ticker = ex.fetch_ticker(perp_symbol)
    price  = ticker["ask"]
    qty    = ex.amount_to_precision(perp_symbol, usdc_amount / price)
    return ex.create_market_buy_order(
        perp_symbol, float(qty), params={"reduceOnly": False}
    )


def close_perp_long(ex: Any, perp_symbol: str, qty: float) -> dict:
    """Close a long perp by selling with reduceOnly."""
    qty_str = ex.amount_to_precision(perp_symbol, qty)
    return ex.create_market_sell_order(
        perp_symbol, float(qty_str), params={"reduceOnly": True}
    )


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
