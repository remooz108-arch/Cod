"""
Place YES bets on Polymarket prediction markets using py-clob-client-v2.
Only called when a headline triggers the signal.
"""

from __future__ import annotations

from typing import Any, Optional
import config

# SDK detection — same pattern as the arb bot
_SDK = "none"
try:
    from py_clob_client_v2 import ClobClient, MarketOrderArgs, OrderType, Side  # type: ignore
    _SDK = "v2"
except ImportError:
    try:
        from py_clob_client.client import ClobClient  # type: ignore
        from py_clob_client.clob_types import MarketOrderArgs, OrderType  # type: ignore
        from py_clob_client.order_builder.constants import BUY  # type: ignore
        class Side:
            BUY = BUY
        _SDK = "legacy"
    except ImportError:
        ClobClient = None
        _SDK = "none"


def init_client() -> Optional[Any]:
    if _SDK == "none" or not config.POLY_PRIVATE_KEY:
        return None
    try:
        if _SDK == "v2":
            l1 = ClobClient(host=config.CLOB_HOST, chain_id=config.CHAIN_ID, key=config.POLY_PRIVATE_KEY)
            creds = l1.create_or_derive_api_key()
            return ClobClient(host=config.CLOB_HOST, chain_id=config.CHAIN_ID, key=config.POLY_PRIVATE_KEY, creds=creds)
        else:
            c = ClobClient(host=config.CLOB_HOST, chain_id=config.CHAIN_ID, key=config.POLY_PRIVATE_KEY)
            try:
                c.set_api_creds(c.create_or_derive_api_creds())
            except Exception:
                pass
            return c
    except Exception as exc:
        print(f"  [warn] Auth failed: {exc}")
        return None


def place_yes_bet(client: Any, token_id: str, amount_usdc: float) -> dict:
    """Place a FOK market order to buy YES shares. Returns the response dict."""
    if _SDK == "v2":
        resp = client.create_and_post_market_order(
            order_args=MarketOrderArgs(token_id=token_id, amount=amount_usdc, side=Side.BUY),
            order_type=OrderType.FOK,
        )
    else:
        resp = client.create_and_post_market_order(
            MarketOrderArgs(token_id=token_id, amount=amount_usdc, side=Side.BUY),
            OrderType.FOK,
        )
    return resp if isinstance(resp, dict) else {"raw": str(resp)}
