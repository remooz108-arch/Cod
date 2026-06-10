import os
from dotenv import load_dotenv

load_dotenv()

# ── Exchange credentials ────────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET     = os.getenv("BINANCE_SECRET", "")
BYBIT_API_KEY      = os.getenv("BYBIT_API_KEY", "")
BYBIT_SECRET       = os.getenv("BYBIT_SECRET", "")
OKX_API_KEY        = os.getenv("OKX_API_KEY", "")
OKX_SECRET         = os.getenv("OKX_SECRET", "")
OKX_PASSPHRASE     = os.getenv("OKX_PASSPHRASE", "")
GATE_API_KEY       = os.getenv("GATE_API_KEY", "")
GATE_SECRET        = os.getenv("GATE_SECRET", "")
HYPERLIQUID_WALLET = os.getenv("HYPERLIQUID_WALLET", "")  # 0x… EVM address
HYPERLIQUID_KEY    = os.getenv("HYPERLIQUID_KEY", "")     # private key hex (no 0x prefix)

# ── Strategy ────────────────────────────────────────────────────────────────
# 0.03 %/8h ≈ 32 % APY  — conservative entry; altcoins regularly hit 0.1–1 %
MIN_FUNDING_RATE   = float(os.getenv("MIN_FUNDING_RATE",  "0.0003"))
EXIT_FUNDING_RATE  = float(os.getenv("EXIT_FUNDING_RATE", "0.0001"))
POSITION_SIZE_USDC = float(os.getenv("POSITION_SIZE_USDC", "500"))
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS", "10"))   # 10 altcoin slots
MAX_TOTAL_USDC     = float(os.getenv("MAX_TOTAL_USDC", "5000"))
SCAN_INTERVAL      = int(os.getenv("SCAN_INTERVAL", "60"))
LIVE_TRADING       = os.getenv("LIVE_TRADING", "false").lower() == "true"

# ── State persistence ─────────────────────────────────────────────────────────
# Written on every position open/close so the bot can resume after a restart
# without losing track of what is open on the exchanges.
STATE_FILE         = os.getenv("STATE_FILE", "./funding_arb_state.json")

# ── Altcoin filters ─────────────────────────────────────────────────────────
# Comma-separated list of base assets to never trade (rug-prone, zero-liquidity)
_USER_BLACKLIST = set(b.upper() for b in os.getenv("BLACKLIST_BASES", "").split(",") if b)
BLACKLIST_BASES  = _USER_BLACKLIST | {"LUNA", "LUNC", "UST", "USTC", "FTT", "BUSD"}

# Minimum USDC mark price — filters out ultra-micro-cap coins with wide spreads
MIN_MARK_PRICE = float(os.getenv("MIN_MARK_PRICE", "0"))

# ── Spike alerts ────────────────────────────────────────────────────────────
# Rate above this triggers a SPIKE alert in the dashboard and logs
# 0.002 = 0.2 %/8h ≈ 220 % APY — well above normal, worth noting
SPIKE_ALERT_RATE = float(os.getenv("SPIKE_ALERT_RATE", "0.002"))

# ── Auto-compounding ─────────────────────────────────────────────────────────
# Each time total_funding_earned crosses a multiple of COMPOUND_THRESHOLD,
# effective position size increases by 10 %.
COMPOUND_ENABLED   = os.getenv("COMPOUND_ENABLED", "true").lower() == "true"
COMPOUND_THRESHOLD = float(os.getenv("COMPOUND_THRESHOLD", "100"))  # reinvest per $100 earned

# ── Income target (display only) ─────────────────────────────────────────────
TARGET_DAILY_USDC  = float(os.getenv("TARGET_DAILY_USDC", "50"))

# ── Annualised equivalents (3 × 365 = 1095 periods per year) ─────────────────
PERIODS_PER_YEAR = 3 * 365


def rate_to_apy(rate_per_8h: float) -> float:
    return ((1 + rate_per_8h) ** PERIODS_PER_YEAR - 1) * 100


def daily_income_est(rate_per_8h: float, deployed_usdc: float) -> float:
    """Rough daily income estimate: 3 funding periods × rate × capital."""
    return deployed_usdc * rate_per_8h * 3
