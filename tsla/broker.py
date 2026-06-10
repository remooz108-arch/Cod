"""Alpaca order placement — bracket orders for LONG and SHORT."""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from strategy import TradeSetup
import config


def make_trading_client() -> TradingClient:
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=config.PAPER,
    )


def market_is_open(client: TradingClient) -> bool:
    clock = client.get_clock()
    return clock.is_open


def account_equity(client: TradingClient) -> float:
    acct = client.get_account()
    return float(acct.equity)


def place_bracket_order(client: TradingClient, setup: TradeSetup) -> dict:
    """
    Submit a bracket order (entry + stop loss + take profit in one request).
    Returns the order dict on success.
    """
    side = OrderSide.BUY if setup.direction == "LONG" else OrderSide.SELL

    # Alpaca requires take_profit > stop_loss (long) or take_profit < stop_loss (short)
    order_req = MarketOrderRequest(
        symbol=config.SYMBOL,
        qty=setup.shares,
        side=side,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=setup.take_profit),
        stop_loss=StopLossRequest(stop_price=setup.stop_loss),
    )

    order = client.submit_order(order_req)
    return order


def cancel_all_open_orders(client: TradingClient) -> None:
    client.cancel_orders()
