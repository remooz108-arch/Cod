# Polymarket Binary Arbitrage Bot

A production-ready Python bot that continuously scans Polymarket's binary prediction markets for pricing inefficiencies. When `best_ask_YES + best_ask_NO < 1.00 - fees`, buying both sides locks in risk-free profit at resolution. The bot detects these mispricings and executes simultaneous FOK (Fill-or-Kill) orders on both outcome tokens before the window closes.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       main.py                           │
│            asyncio event loop + graceful shutdown        │
└──────┬──────────────┬─────────────────┬─────────────────┘
       │              │                 │
  ┌────▼────┐   ┌─────▼─────┐   ┌──────▼──────┐
  │ Scanner │   │ RiskMgr   │   │   Monitor   │
  │         │   │           │   │ (Rich UI)   │
  │ Gamma   │   │ position  │   └─────────────┘
  │ API     │   │ limits    │
  │ + REST  │   │ daily P&L │
  │ + WS    │   │ cooldowns │
  └────┬────┘   └─────▲─────┘
       │               │
       │  Opportunity  │  Trade result
       ▼               │
  ┌────────────────────┘
  │    Executor
  │    re-fetch books → re-validate
  │    YES FOK order → NO FOK order
  │    leg-risk handling
  └──────────────────────────────────
           │
      ┌────▼────┐
      │  CLOB   │  py-clob-client-v2
      │   API   │  (Polygon chain 137)
      └─────────┘
```

---

## Prerequisites

- Python 3.11+
- A Polygon wallet funded with USDC (chain ID 137)
- A [Polymarket](https://polymarket.com) account with the same wallet
- Free [Alpaca](https://alpaca.markets) account only if using the TSLA bot in this repo

---

## Setup

```bash
# 1. Clone and enter the directory
git clone https://github.com/remooz108-arch/Cod
cd Cod/polymarket-arb

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env — fill in POLY_PRIVATE_KEY and POLY_FUNDER_ADDRESS
```

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `POLY_PRIVATE_KEY` | required | Your Polygon wallet private key |
| `POLY_FUNDER_ADDRESS` | required | Same wallet address (or deposit wallet) |
| `POLY_SIGNATURE_TYPE` | `2` | 2 = deposit wallet, 0 = EOA/MetaMask |
| `MIN_SPREAD_BPS` | `50` | Minimum net profit in basis points (50 = 0.5%) |
| `MAX_POSITION_USDC` | `500` | Max USDC per arb pair |
| `MAX_TOTAL_DEPLOYED_USDC` | `5000` | Total capital cap |
| `DAILY_LOSS_LIMIT_USDC` | `100` | Stop trading if daily loss exceeds this |
| `SCAN_INTERVAL_MS` | `500` | REST polling interval (ignored when WS active) |
| `USE_WEBSOCKET` | `true` | Use WebSocket for real-time book updates |
| `DRY_RUN` | `true` | **Default: true. Must set false to trade.** |
| `MAX_CONCURRENT_MARKETS` | `50` | Markets checked per scan cycle |
| `MIN_MARKET_LIQUIDITY_USDC` | `100` | Skip markets with thin depth |
| `COOLDOWN_AFTER_FAILURES` | `5` | Pause seconds after 3 fill failures |

---

## Usage

```bash
# Dry-run (default) — scans and logs, places no orders
python -m src.main

# Scan only — log opportunities, skip executor entirely
python -m src.main --scan-only

# Headless mode (no Rich dashboard — better for servers/pipes)
python -m src.main --no-dashboard

# Alternate config file
python -m src.main --config /path/to/production.env
```

### Going live

1. Set `DRY_RUN=false` in `.env` (or pass `--live`)
2. Start with a small `MAX_POSITION_USDC` (e.g. `10`)
3. Monitor `signals.log` and `trades.jsonl` for the first few hours
4. Watch for `SINGLE-LEG EXPOSURE` warnings — these require manual attention

```bash
python -m src.main --live
```

---

## Fee explanation

Polymarket charges **~2% on net winnings only** (not on the purchase price). The formula used:

```
gross_profit = 1.00 - pair_cost
net_profit   = gross_profit × (1 - 0.02)
```

The bot only trades when `net_profit ≥ MIN_SPREAD_BPS / 10000`. At the default 50 bps, the pair cost must be below ~0.995 after fees.

---

## Output files

| File | Contents |
|---|---|
| `trades.jsonl` | Every opportunity detected + every trade attempted (JSON lines) |
| Console | Rich live dashboard (or plain logs with `--no-dashboard`) |

---

## Running tests

```bash
pytest tests/ -v
```

---

## Risk warnings

- **Not financial advice.** This is experimental software. Use at your own risk.
- Always test on dry-run first and verify the P&L logic matches your expectations.
- **Single-leg exposure**: if the YES order fills but the NO order fails, you hold a directional position. The bot logs a `CRITICAL` warning. Hedge or close manually via the Polymarket UI.
- Start with small position sizes. Arb windows are rare and close fast.
- Polymarket markets can be paused or resolved early — open positions may behave unexpectedly.

---

## License

MIT
