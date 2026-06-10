import os
from dotenv import load_dotenv

load_dotenv()

# Exchange credentials
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET     = os.getenv("BINANCE_SECRET", "")
BYBIT_API_KEY      = os.getenv("BYBIT_API_KEY", "")
BYBIT_SECRET       = os.getenv("BYBIT_SECRET", "")
OKX_API_KEY        = os.getenv("OKX_API_KEY", "")
OKX_SECRET         = os.getenv("OKX_SECRET", "")
OKX_PASSPHRASE     = os.getenv("OKX_PASSPHRASE", "")

# Strategy
MIN_FUNDING_RATE   = float(os.getenv("MIN_FUNDING_RATE",  "0.0003"))  # per 8h
EXIT_FUNDING_RATE  = float(os.getenv("EXIT_FUNDING_RATE", "0.0001"))  # per 8h
POSITION_SIZE_USDC = float(os.getenv("POSITION_SIZE_USDC", "500"))
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS", "5"))
MAX_TOTAL_USDC     = float(os.getenv("MAX_TOTAL_USDC", "5000"))
SCAN_INTERVAL      = int(os.getenv("SCAN_INTERVAL", "60"))
LIVE_TRADING       = os.getenv("LIVE_TRADING", "false").lower() == "true"

# Annualised equivalents for display (3 funding periods per day × 365)
PERIODS_PER_YEAR   = 3 * 365

def rate_to_apy(rate_per_8h: float) -> float:
    return ((1 + rate_per_8h) ** PERIODS_PER_YEAR - 1) * 100
