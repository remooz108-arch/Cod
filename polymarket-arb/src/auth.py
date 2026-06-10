"""
CLOB client initialisation.

Tries py-clob-client-v2, then falls back to legacy py-clob-client.
In DRY_RUN mode a missing or invalid key is non-fatal — the bot scans
markets without signing any orders.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .config import Config

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

# ── SDK detection ────────────────────────────────────────────────────────────

_SDK_VERSION = "none"

try:
    from py_clob_client_v2 import (  # type: ignore
        ApiCreds,
        ClobClient,
        MarketOrderArgs,
        OrderArgs,
        OrderType,
        PartialCreateOrderOptions,
        Side,
    )
    _SDK_VERSION = "py-clob-client-v2"

except ImportError:
    try:
        from py_clob_client.client import ClobClient  # type: ignore
        from py_clob_client.clob_types import (  # type: ignore
            MarketOrderArgs,
            OrderArgs,
            OrderType,
        )
        from py_clob_client.order_builder.constants import BUY as _BUY, SELL as _SELL  # type: ignore

        class Side:  # type: ignore
            BUY = _BUY
            SELL = _SELL

        ApiCreds = None
        PartialCreateOrderOptions = None
        _SDK_VERSION = "py-clob-client (legacy)"

    except ImportError:
        ClobClient = None  # type: ignore
        MarketOrderArgs = None  # type: ignore
        OrderArgs = None  # type: ignore
        OrderType = None  # type: ignore
        Side = None  # type: ignore
        ApiCreds = None  # type: ignore
        PartialCreateOrderOptions = None  # type: ignore
        _SDK_VERSION = "none"


def get_sdk_version() -> str:
    return _SDK_VERSION


def init_client(config: Config) -> Optional[Any]:
    """
    Return an authenticated ClobClient, or None if running dry-run without a key.
    Raises on auth failure when DRY_RUN is False.
    """
    if _SDK_VERSION == "none":
        if config.dry_run:
            logger.warning(
                "No Polymarket SDK found. Running in scan-only mode. "
                "Install: pip install py-clob-client-v2"
            )
            return None
        raise ImportError(
            "No Polymarket SDK installed.\n"
            "  pip install py-clob-client-v2\n"
            "or (legacy):\n"
            "  pip install py-clob-client"
        )

    if not config.private_key:
        if config.dry_run:
            logger.warning("No private key configured — scan-only mode active.")
            return None
        raise ValueError("POLY_PRIVATE_KEY is required for live trading.")

    logger.info(f"Initialising CLOB client using SDK: {_SDK_VERSION}")

    try:
        if _SDK_VERSION == "py-clob-client-v2":
            return _init_v2(config)
        else:
            return _init_legacy(config)

    except Exception as exc:
        if config.dry_run:
            logger.warning(f"Auth failed ({exc}) — falling back to scan-only mode.")
            return None
        raise RuntimeError(f"CLOB authentication failed: {exc}") from exc


def _init_v2(config: Config) -> Any:
    """Initialise the v2 SDK: L1 key derivation → L2 authenticated client."""
    l1_client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=config.private_key,
    )
    creds = l1_client.create_or_derive_api_key()
    logger.debug(f"Derived API credentials (key={getattr(creds, 'api_key', '?')[:8]}...)")

    kwargs: dict = dict(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=config.private_key,
        creds=creds,
    )
    # Include funder if the SDK accepts it (deposit-wallet signature type 2)
    if config.funder_address and config.signature_type == 2:
        try:
            client = ClobClient(**kwargs, funder=config.funder_address)
        except TypeError:
            client = ClobClient(**kwargs)
    else:
        client = ClobClient(**kwargs)

    return client


def _init_legacy(config: Config) -> Any:
    """Initialise the legacy v1 SDK."""
    client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=config.private_key,
    )
    try:
        client.set_api_creds(client.create_or_derive_api_creds())
    except AttributeError:
        pass  # some legacy versions auto-derive
    return client


def health_check(client: Any) -> bool:
    """Return True if the CLOB endpoint is reachable and the client is authenticated."""
    try:
        if hasattr(client, "get_ok"):
            result = client.get_ok()
            ok = result == "OK" or result is True or (
                isinstance(result, dict) and result.get("status") == "OK"
            )
            if not ok:
                logger.error(f"CLOB health check returned unexpected response: {result!r}")
                return False

        if hasattr(client, "get_server_time"):
            server_time = client.get_server_time()
            logger.info(f"CLOB server time: {server_time}")

        return True

    except Exception as exc:
        logger.error(f"CLOB health check failed: {exc}")
        return False
