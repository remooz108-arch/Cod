import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_MODE = os.getenv("ALPACA_MODE", "paper").lower()

PAPER = ALPACA_MODE == "paper"
BASE_URL = (
    "https://paper-api.alpaca.markets"
    if PAPER
    else "https://api.alpaca.markets"
)

SYMBOL = "TSLA"
RISK_PER_TRADE_USD = float(os.getenv("RISK_PER_TRADE_USD", "100"))
MAX_SHARES = int(os.getenv("MAX_SHARES", "50"))
MIN_MOVE_USD = float(os.getenv("MIN_MOVE_USD", "0.15"))
LIVE_ORDERS = os.getenv("LIVE_ORDERS", "false").lower() == "true"

# New York market open
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
SIGNAL_WAIT_SECONDS = 120   # 2 minutes after open
NY_TZ = "America/New_York"
