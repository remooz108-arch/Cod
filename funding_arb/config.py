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
HYPERLIQUID_WALLET = os.getenv("HYPERLIQUID_WALLET", "")
HYPERLIQUID_KEY    = os.getenv("HYPERLIQUID_KEY", "")
# MEXC — highest altcoin funding rates; often 2-5× Gate.io on same coins
MEXC_API_KEY       = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET        = os.getenv("MEXC_SECRET", "")
# Bitget — strong altcoin selection, competitive rates, copy-trading liquidity
BITGET_API_KEY     = os.getenv("BITGET_API_KEY", "")
BITGET_SECRET      = os.getenv("BITGET_SECRET", "")
BITGET_PASSPHRASE  = os.getenv("BITGET_PASSPHRASE", "")

# ── Capital (the ONE number you need to change) ───────────────────────────────
# Everything else derives from this automatically — position size, compound
# threshold, daily target, circuit breaker.  Just set this and go.
MAX_TOTAL_USDC = float(os.getenv("MAX_TOTAL_USDC", "5000"))
MAX_POSITIONS  = int(os.getenv("MAX_POSITIONS",  "10"))

# ── Auto-derived scaling ──────────────────────────────────────────────────────
# These set sensible proportional defaults for any capital level.
# Override any of them in .env if you want specific values.

# Position size = equal share of capital across all slots.
_pos_default = MAX_TOTAL_USDC / MAX_POSITIONS
POSITION_SIZE_USDC = float(os.getenv("POSITION_SIZE_USDC", str(_pos_default)))

# Compound trigger = 2% of capital earned (min $2 to avoid never triggering).
_compound_default = max(2.0, round(MAX_TOTAL_USDC * 0.02, 2))
COMPOUND_THRESHOLD = float(os.getenv("COMPOUND_THRESHOLD", str(_compound_default)))

# Daily income target for the progress bar = 0.3%/day at entry-rate floor.
# At MIN_FUNDING_RATE (0.03%/8h × 3/day × capital) this is modest but achievable.
_daily_default = max(0.10, round(MAX_TOTAL_USDC * 0.003, 2))
TARGET_DAILY_USDC = float(os.getenv("TARGET_DAILY_USDC", str(_daily_default)))

# Circuit breaker = trip after losing 1/3 of positions to rate flips (min 2).
_cb_default = max(2, MAX_POSITIONS // 3)
CIRCUIT_BREAKER_EXITS = int(os.getenv("CIRCUIT_BREAKER_EXITS", str(_cb_default)))

# ── Strategy ────────────────────────────────────────────────────────────────
# 0.03 %/8h ≈ 32 % APY  — conservative entry; altcoins regularly hit 0.1–1 %
MIN_FUNDING_RATE  = float(os.getenv("MIN_FUNDING_RATE",  "0.0003"))
EXIT_FUNDING_RATE = float(os.getenv("EXIT_FUNDING_RATE", "0.0001"))
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "60"))
LIVE_TRADING      = os.getenv("LIVE_TRADING", "false").lower() == "true"

# ── State persistence ─────────────────────────────────────────────────────────
STATE_FILE = os.getenv("STATE_FILE", "./funding_arb_state.json")

# ── Altcoin filters ─────────────────────────────────────────────────────────
_USER_BLACKLIST = set(b.upper() for b in os.getenv("BLACKLIST_BASES", "").split(",") if b)
BLACKLIST_BASES  = _USER_BLACKLIST | {"LUNA", "LUNC", "UST", "USTC", "FTT", "BUSD"}
MIN_MARK_PRICE   = float(os.getenv("MIN_MARK_PRICE", "0"))

# ── Spike alerts ────────────────────────────────────────────────────────────
SPIKE_ALERT_RATE = float(os.getenv("SPIKE_ALERT_RATE", "0.002"))

# ── Auto-compounding ─────────────────────────────────────────────────────────
COMPOUND_ENABLED = os.getenv("COMPOUND_ENABLED", "true").lower() == "true"
# COMPOUND_THRESHOLD derived above from capital size.

# ── Position rotation ─────────────────────────────────────────────────────────
ROTATION_ENABLED   = os.getenv("ROTATION_ENABLED",  "true").lower() == "true"
ROTATION_THRESHOLD = float(os.getenv("ROTATION_THRESHOLD", "1.5"))
MIN_HOLD_PERIODS   = int(os.getenv("MIN_HOLD_PERIODS", "2"))

# ── Concentration caps ────────────────────────────────────────────────────────
MAX_EXCHANGE_FRACTION = float(os.getenv("MAX_EXCHANGE_FRACTION", "0.5"))  # 50% per exchange
MAX_ASSET_FRACTION    = float(os.getenv("MAX_ASSET_FRACTION",    "0.3"))  # 30% per coin

# ── Entry quality gate ────────────────────────────────────────────────────────
TAKER_FEE_PCT         = float(os.getenv("TAKER_FEE_PCT",         "0.0005"))
MAX_BREAKEVEN_PERIODS = int(os.getenv("MAX_BREAKEVEN_PERIODS",    "12"))

# ── Rate stability filter ─────────────────────────────────────────────────────
RATE_STABILITY_ENABLED = os.getenv("RATE_STABILITY_ENABLED", "true").lower() == "true"
RATE_STABILITY_SCANS   = int(os.getenv("RATE_STABILITY_SCANS", "3"))

# ── Rate consistency filter (rolling mean / volatility) ───────────────────────
# Beyond "positive for N scans", track a longer rolling window per asset and
# require the AVERAGE rate to clear MIN_FUNDING_RATE and the rate to be
# CONSISTENT (low coefficient of variation = std/mean). A rate that averages
# 0.15%/8h steadily beats one that spiked once to 0.15% but averages 0.01%.
RATE_HISTORY_SAMPLES = int(os.getenv("RATE_HISTORY_SAMPLES", "40"))   # rolling window length
RATE_CV_FILTER_ENABLED = os.getenv("RATE_CV_FILTER_ENABLED", "true").lower() == "true"
MAX_RATE_CV = float(os.getenv("MAX_RATE_CV", "1.0"))                  # std/mean ceiling (1.0 = std ≤ mean)

# ── Cooldown guard ────────────────────────────────────────────────────────────
# After a position exits, block re-entry of the SAME asset for this many hours.
# Prevents whipsawing in and out of a coin whose rate is oscillating around
# the threshold. (Idea adapted from OpenAlice's CooldownGuard.)
COOLDOWN_ENABLED = os.getenv("COOLDOWN_ENABLED", "true").lower() == "true"
COOLDOWN_HOURS   = float(os.getenv("COOLDOWN_HOURS", "2"))

# ── Balance-aware sizing ──────────────────────────────────────────────────────
# When live, size each position as a fraction of REAL available exchange
# balance rather than a fixed dollar amount — the bot self-calibrates as your
# capital grows. Falls back to the fixed/compounded size if balance is
# unavailable. (Idea adapted from OpenAlice's %-of-equity sizing.)
BALANCE_AWARE_SIZING = os.getenv("BALANCE_AWARE_SIZING", "false").lower() == "true"
BALANCE_FRACTION     = float(os.getenv("BALANCE_FRACTION", "0.10"))  # 10% of free balance per position

# ── Equity curve snapshots ────────────────────────────────────────────────────
# Append total deployed + all-time earned + open count to a CSV once per hour,
# building a time series you can plot to watch your wealth grow.
EQUITY_CURVE_FILE     = os.getenv("EQUITY_CURVE_FILE", "./funding_arb_equity.csv")
EQUITY_SNAPSHOT_HOURS = float(os.getenv("EQUITY_SNAPSHOT_HOURS", "1"))

# ── Trailing rate stop ────────────────────────────────────────────────────────
TRAILING_RATE_STOP = float(os.getenv("TRAILING_RATE_STOP", "0.5"))

# ── Hedge drift monitor ───────────────────────────────────────────────────────
HEDGE_DRIFT_ALERT_PCT = float(os.getenv("HEDGE_DRIFT_ALERT_PCT", "0.05"))
HEDGE_DRIFT_EXIT_PCT  = float(os.getenv("HEDGE_DRIFT_EXIT_PCT",  "0.15"))

# ── Perp leverage ─────────────────────────────────────────────────────────────
PERP_LEVERAGE = int(os.getenv("PERP_LEVERAGE", "1"))

# ── Margin health guard ───────────────────────────────────────────────────────
MARGIN_ALERT_RATIO = float(os.getenv("MARGIN_ALERT_RATIO", "0.5"))
MARGIN_EXIT_RATIO  = float(os.getenv("MARGIN_EXIT_RATIO",  "0.8"))

# ── Circuit breaker ───────────────────────────────────────────────────────────
CIRCUIT_BREAKER_ENABLED = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"
# CIRCUIT_BREAKER_EXITS derived above from MAX_POSITIONS.

# ── Trade journal ─────────────────────────────────────────────────────────────
TRADE_JOURNAL_FILE = os.getenv("TRADE_JOURNAL_FILE", "./funding_arb_trades.csv")

# ── Adaptive scan speed ───────────────────────────────────────────────────────
SCAN_INTERVAL_FAST  = int(os.getenv("SCAN_INTERVAL_FAST",  "30"))
FAST_SCAN_THRESHOLD = float(os.getenv("FAST_SCAN_THRESHOLD", "0.5"))

# ── Maker-order entry ─────────────────────────────────────────────────────────
# Post-only limit at best bid/ask; falls back to market if not filled in time.
# Saves ~0.03–0.05 % per round trip on Bybit/OKX (taker avoided, rebate earned).
MAKER_ORDER_ENABLED = os.getenv("MAKER_ORDER_ENABLED", "true").lower() == "true"
MAKER_FILL_TIMEOUT  = int(os.getenv("MAKER_FILL_TIMEOUT", "20"))   # seconds

# ── Sector concentration cap ──────────────────────────────────────────────────
# No more than MAX_SECTOR_POSITIONS open at once from the same narrative cluster.
# Prevents 4 memecoins or 3 L1s exiting simultaneously in a sentiment reversal.
MAX_SECTOR_POSITIONS = int(os.getenv("MAX_SECTOR_POSITIONS", "2"))
SECTOR_CLUSTERS: dict[str, set[str]] = {
    "l1":     {"BTC","ETH","SOL","BNB","AVAX","ADA","DOT","MATIC","NEAR","APT","SUI","SEI","TON"},
    "meme":   {"DOGE","SHIB","PEPE","WIF","BONK","FLOKI","NEIRO","MEME","POPCAT","BOME","TURBO","MOG"},
    "defi":   {"UNI","AAVE","CRV","MKR","SNX","SUSHI","COMP","1INCH","JUP","ORCA","PENDLE","CAKE"},
    "ai":     {"FET","AGIX","OCEAN","RNDR","WLD","TAO","ARKM","GRT","AIOZ"},
    "gaming": {"AXS","MANA","SAND","ENJ","GALA","IMX","RON","BEAM","PIXEL","MAGIC","YGG"},
}

# ── Funding timing gate ───────────────────────────────────────────────────────
# When next_funding is known and < TIMING_GATE_MINUTES away, bypass the
# rate-stability scan — the payment is imminent, collect it immediately.
TIMING_GATE_ENABLED = os.getenv("TIMING_GATE_ENABLED", "true").lower() == "true"
TIMING_GATE_MINUTES = int(os.getenv("TIMING_GATE_MINUTES", "15"))

# ── Rate momentum filter ──────────────────────────────────────────────────────
# Reject entries where the rate has been falling too fast.
# Momentum = (last_rate - first_rate) / first_rate over the observation window.
# -0.3 means "skip if rate has fallen more than 30% of its own value."
MOMENTUM_FILTER_ENABLED = os.getenv("MOMENTUM_FILTER_ENABLED", "true").lower() == "true"
MIN_RATE_MOMENTUM       = float(os.getenv("MIN_RATE_MOMENTUM", "-0.3"))

# ── Negative funding harvesting ───────────────────────────────────────────────
# When funding rates go NEGATIVE, shorts pay longs. Flip the hedge:
# short spot on margin + long perp to collect inverse payments.
# Requires margin/cross-margin trading to be enabled on the exchange.
NEGATIVE_FUNDING_ENABLED  = os.getenv("NEGATIVE_FUNDING_ENABLED", "false").lower() == "true"
MIN_NEGATIVE_FUNDING_RATE = float(os.getenv("MIN_NEGATIVE_FUNDING_RATE", "0.0003"))
MARGIN_INTEREST_RATE      = float(os.getenv("MARGIN_INTEREST_RATE", "0.0002"))  # 0.02%/day

# ── Rate-proportional position sizing ─────────────────────────────────────────
# Allocate more capital to higher-quality rates. A rate 3× the minimum threshold
# gets up to MAX_SIZE_MULTIPLIER × the base position size, capped at MAX_TOTAL/3.
RATE_PROPORTIONAL_SIZING = os.getenv("RATE_PROPORTIONAL_SIZING", "true").lower() == "true"
MAX_SIZE_MULTIPLIER      = float(os.getenv("MAX_SIZE_MULTIPLIER", "2.0"))

# ── Cross-exchange arbitrage ──────────────────────────────────────────────────
# Buy spot on the most liquid exchange, short perp on the highest-rate exchange.
# Requires capital pre-funded on both exchanges simultaneously.
CROSS_EXCHANGE_ARB       = os.getenv("CROSS_EXCHANGE_ARB", "true").lower() == "true"
SPOT_EXCHANGE_PREFERENCE = [
    s.strip() for s in
    os.getenv("SPOT_EXCHANGE_PREFERENCE", "binance,bybit,okx,gateio,mexc,bitget").split(",")
    if s.strip()
]

# ── Telegram notifications ────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Annualised equivalents ────────────────────────────────────────────────────
PERIODS_PER_YEAR = 3 * 365


def rate_to_apy(rate_per_8h: float) -> float:
    return ((1 + rate_per_8h) ** PERIODS_PER_YEAR - 1) * 100


def daily_income_est(rate_per_8h: float, deployed_usdc: float) -> float:
    """Rough daily income estimate: 3 funding periods × rate × capital."""
    return deployed_usdc * rate_per_8h * 3


def validate() -> list[str]:
    """
    Return a list of human-readable warnings about the current configuration.
    The bot still runs — these are advisory, not fatal.
    """
    warnings: list[str] = []
    min_viable = 15.0  # most exchanges reject orders below ~$10-15
    if POSITION_SIZE_USDC < min_viable:
        warnings.append(
            f"Position size ${POSITION_SIZE_USDC:.2f} may be below exchange minimums "
            f"(~${min_viable:.0f}). Consider reducing MAX_POSITIONS or increasing MAX_TOTAL_USDC."
        )
    if COMPOUND_THRESHOLD < 1.0:
        warnings.append(
            f"COMPOUND_THRESHOLD ${COMPOUND_THRESHOLD:.2f} is very small — "
            f"compounding will fire on almost every scan."
        )
    if MAX_POSITIONS > 1 and POSITION_SIZE_USDC * MAX_POSITIONS > MAX_TOTAL_USDC * 1.01:
        warnings.append(
            "POSITION_SIZE_USDC × MAX_POSITIONS exceeds MAX_TOTAL_USDC. "
            "The capital cap will prevent filling all slots simultaneously."
        )
    return warnings
