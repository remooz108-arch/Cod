# TSLA Opening Momentum Bot

Waits for **9:30 AM New York time**, records TSLA's open price, waits **2 minutes**, then enters **LONG or SHORT** based on direction — with a **1:1 bracket order** (stop loss = take profit distance).

## Strategy

```
9:30:00 AM ET  →  record open_price
9:32:00 AM ET  →  record signal_price

move = signal_price - open_price

if move > +MIN_MOVE  →  LONG
if move < -MIN_MOVE  →  SHORT
else                 →  no trade (too noisy)

Stop Loss   = entry ∓ |move|
Take Profit = entry ± |move|     ← 1:1 risk/reward

Shares = floor(RISK_PER_TRADE_USD / |move|)  capped at MAX_SHARES
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in your Alpaca API keys
```

## Get Alpaca API keys (free)

1. Sign up at [alpaca.markets](https://alpaca.markets) — free account, no deposit needed
2. Go to **Paper Trading** → API Keys → Generate
3. Paste `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` into `.env`

## Usage

```bash
# Dry-run at market open (waits for 9:30 AM ET, prints trade but doesn't submit)
python bot.py

# Live bracket order at market open
python bot.py --live

# Test immediately without waiting for 9:30 (uses current price)
python bot.py --now

# Test + live order right now
python bot.py --now --live
```

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ALPACA_MODE` | `paper` | `paper` or `live` |
| `RISK_PER_TRADE_USD` | `100` | Max dollars at risk |
| `MAX_SHARES` | `50` | Hard share cap |
| `MIN_MOVE_USD` | `0.15` | Minimum 2-min move to trigger a trade |
| `LIVE_ORDERS` | `false` | Must be `true` to submit real orders |

## Risk disclaimer

This is a momentum strategy with no guarantee of profit. Always test on paper trading first. Never risk more than you can afford to lose.
