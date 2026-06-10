"""Alpaca bracket order placement for the news signal bot."""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from trades import TradeSetup
import config


def make_trading_client() -> TradingClient:
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=config.PAPER,
    )


def make_data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
    )


def get_price(data_client: StockHistoricalDataClient, symbol: str) -> float:
    req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
    quote = data_client.get_stock_latest_quote(req)[symbol]
    ask = float(quote.ask_price or 0)
    bid = float(quote.bid_price or 0)
    if ask > 0 and bid > 0:
        return round((ask + bid) / 2, 4)
    return 0.0


def market_is_open(trading_client: TradingClient) -> bool:
    return trading_client.get_clock().is_open


def has_open_position(trading_client: TradingClient, symbol: str) -> bool:
    try:
        trading_client.get_open_position(symbol)
        return True
    except Exception:
        return False


def place_bracket_order(trading_client: TradingClient, setup: TradeSetup) -> dict:
    order = trading_client.submit_order(
        MarketOrderRequest(
            symbol=setup.symbol,
            qty=setup.shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=setup.take_profit),
            stop_loss=StopLossRequest(stop_price=setup.stop_loss),
        )
    )
    return order


def account_equity(trading_client: TradingClient) -> float:
    return float(trading_client.get_account().equity)
