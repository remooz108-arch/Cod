# Funding Rate Arbitrage Bot

## The strategy

Perpetual futures contracts pay a **funding rate** every 8 hours between longs and shorts. When the rate is positive, longs pay shorts. This bot captures that payment by holding a **delta-neutral** position:

```
Buy $250 BTC spot  (long)
Short $250 BTC perp (short)

Net directional exposure = $0  ← price moves don't matter
Income = funding rate × position size, paid every 8 hours
```

### Real numbers

| Funding rate | APY equivalent | Monthly on $5,000 |
|---|---|---|
| 0.01% / 8h | 13.5% | $56 |
| 0.03% / 8h | 40.9% | $170 |
| 0.05% / 8h | 68.9% | $287 |
| 0.10% / 8h | 147% | $613 |

During high-volatility events (liquidation cascades, major news), funding rates can spike to 0.5–1% per 8h for hours or days.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Add API keys for Binance, Bybit, and/or OKX
```

## Usage

```bash
# Scan and show dashboard — no orders placed
python bot.py

# Live trading
python bot.py --live

# Headless / server mode
python bot.py --no-ui
```

## How to get exchange API keys

- **Binance**: [binance.com/en/my/settings/api-management](https://www.binance.com/en/my/settings/api-management) — enable Spot + Futures trading
- **Bybit**: [bybit.com/app/user/api-management](https://www.bybit.com/app/user/api-management) — enable Unified Trading
- **OKX**: [okx.com/account/my-api](https://www.okx.com/account/my-api) — enable Trade permission

## Risks

- **Funding rate flip**: rate goes negative → you now PAY funding. Bot exits automatically when rate drops below `EXIT_FUNDING_RATE`.
- **Exchange risk**: funds held on centralised exchange. Never keep more than you can afford to lose on any single exchange.
- **Execution risk**: if spot buy succeeds but perp short fails, you have an unhedged position. Bot logs a critical warning and does not proceed.
- **Slippage**: market orders have slippage. For large positions, use limit orders (manual).

## What separates this from most bots

1. Multi-exchange scanning (Binance, Bybit, OKX simultaneously)
2. Auto-exit when rate deteriorates — doesn't hold through a rate flip
3. Hard capital caps prevent overexposure
4. Execution safety: aborts cleanly if perp leg fails after spot fills
