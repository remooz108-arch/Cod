"""Real-time TSLA price fetching via Alpaca data API."""

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockLatestBarRequest
import config


def make_data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
    )


def get_latest_price(client: StockHistoricalDataClient, symbol: str = config.SYMBOL) -> float:
    """Return the latest mid-price for symbol."""
    req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
    quote = client.get_stock_latest_quote(req)[symbol]

    ask = float(quote.ask_price or 0)
    bid = float(quote.bid_price or 0)

    # Fall back to latest bar close if quote is stale
    if ask == 0 or bid == 0:
        bar_req = StockLatestBarRequest(symbol_or_symbols=[symbol])
        bar = client.get_stock_latest_bar(bar_req)[symbol]
        return float(bar.close)

    return round((ask + bid) / 2, 4)
