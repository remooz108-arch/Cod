"""Thin wrapper around py-clob-client for order placement."""

from typing import Optional
import config

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.constants import POLYGON
    _HAS_CLOB = True
except ImportError:
    _HAS_CLOB = False


class PolymarketTrader:
    def __init__(self):
        if not _HAS_CLOB:
            raise ImportError("py-clob-client is not installed. Run: pip install py-clob-client")
        if not config.PRIVATE_KEY:
            raise ValueError("PRIVATE_KEY is not set in .env")

        self.client = ClobClient(
            host=config.CLOB_HOST,
            chain_id=config.CHAIN_ID,
            key=config.PRIVATE_KEY,
        )
        # Derive or retrieve API credentials
        self.client.set_api_creds(self.client.create_or_derive_api_creds())

    def get_balance(self) -> float:
        """Return available USDC balance."""
        try:
            bal = self.client.get_balance()
            return float(bal)
        except Exception as exc:
            print(f"  [warn] could not fetch balance: {exc}")
            return 0.0

    def place_order(
        self,
        token_id: str,
        side: str,
        size_usdc: float,
        price: float,
        order_type: str = "GTC",
    ) -> Optional[dict]:
        """
        Place a limit order.
        side: "BUY" to buy shares (bet YES/NO token)
        Returns the order response dict or None on failure.
        """
        if not config.LIVE_TRADING:
            print(f"  [dry-run] Would place {order_type} {side} order: "
                  f"{size_usdc} USDC of token {token_id[:12]}... @ {price}")
            return {"dry_run": True, "token_id": token_id, "side": side,
                    "size": size_usdc, "price": price}

        try:
            otype = OrderType.GTC if order_type == "GTC" else OrderType.FOK
            args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size_usdc / price,  # convert USDC to shares
                side=side,
            )
            resp = self.client.create_and_post_order(args)
            return resp
        except Exception as exc:
            print(f"  [error] order failed: {exc}")
            return None
