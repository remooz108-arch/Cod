# Polymarket Batumi Weather Bot

A Python bot that fetches weather forecast data for **Batumi, Georgia** and places bets on Polymarket rain/no-rain prediction markets when it finds a favourable edge.

## How it works

1. **Weather** — Queries OpenWeatherMap for Batumi's 24-hour forecast and calculates a rain probability.
2. **Markets** — Searches Polymarket's Gamma API for active Batumi rain/weather markets.
3. **Strategy** — Compares the weather-implied probability against each market's current price. Uses fractional Kelly criterion to size each bet.
4. **Execute** — Places limit orders via the Polymarket CLOB API if edge ≥ `MIN_EDGE`.

## Setup

```bash
# 1. Clone and install dependencies
pip install -r requirements.txt

# 2. Copy and fill in credentials
cp .env.example .env
# Edit .env with your API keys and wallet private key
```

## Required credentials

| Variable | Where to get it |
|---|---|
| `WEATHER_API_KEY` | Free at [openweathermap.org/api](https://openweathermap.org/api) |
| `PRIVATE_KEY` | Your Polygon wallet private key |

## Usage

```bash
# Dry-run (default) — prints decisions but places no orders
python bot.py

# Live trading
python bot.py --live
# or set LIVE_TRADING=true in .env
```

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `MAX_BET_USDC` | `10` | Max USDC per trade |
| `MIN_EDGE` | `0.05` | Minimum edge (5%) required to bet |
| `KELLY_FRACTION` | `0.25` | Quarter-Kelly bet sizing |
| `LIVE_TRADING` | `false` | Must be `true` to place real orders |

## Project structure

```
bot.py               # Entry point
weather.py           # OpenWeatherMap fetcher for Batumi
market_finder.py     # Searches Polymarket Gamma API
strategy.py          # Weather→probability + Kelly sizing
polymarket_client.py # CLOB order placement wrapper
config.py            # Env-based config
```

## Risk disclaimer

Prediction market trading involves financial risk. Run in dry-run mode first to validate the strategy. Never bet more than you can afford to lose.
