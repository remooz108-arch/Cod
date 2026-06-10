# Geopolitical News Signal Bot

Scans news RSS feeds every 5 minutes. When a single article mentions **Trump**, **Iran**, AND **Israel** together, it fires bracket orders on **XLE** (oil ETF) and **GLD** (gold ETF) — the two assets that reliably spike on Middle East tension.

## Signal logic

```
FOR each new article across 6 RSS feeds:
    IF "trump" AND "iran" AND "israel" all appear in title + body:
        → SIGNAL FIRED
        → BUY XLE  (energy/oil ETF)
        → BUY GLD  (gold ETF)
        → bracket order: stop loss -1%  |  take profit +1%  (1:1)
```

## News sources scanned

- Reuters World + Politics
- BBC World
- Al Jazeera
- AP Top News
- CNN World
- NewsAPI (optional, needs free key)

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in Alpaca API keys
```

## Usage

```bash
# Single scan, dry-run (great for testing)
python bot.py --once

# Continuous polling every 5 minutes, dry-run
python bot.py

# Continuous polling, submit real orders
python bot.py --live
```

## What gets created at runtime

| File | Contents |
|---|---|
| `seen_articles.json` | Article IDs already processed (prevents re-triggering) |
| `cooldowns.json` | Last trade time per ticker (prevents rapid re-entry) |
| `signals.log` | Log of every article that fired a signal |

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `POLL_INTERVAL` | `300` | Seconds between scans |
| `RISK_PER_TRADE_USD` | `100` | Max dollars at risk per ticker |
| `TRADE_COOLDOWN` | `3600` | Seconds before re-entering same ticker |
| `LIVE_ORDERS` | `false` | Must be `true` to submit real orders |
