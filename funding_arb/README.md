# Funding Rate Arbitrage Bot — v2

## The strategy

Perpetual futures contracts pay a **funding rate** every 8 hours between longs and shorts. When the rate is positive, longs pay shorts. The bot captures that payment by holding a **delta-neutral** position:

```
Buy $250 BTC spot  (long)
Short $250 BTC perp (short)

Net directional exposure = $0  ← price moves don't matter
Income = funding rate × position size, paid every 8 hours
```

### Altcoin rates vs BTC/ETH

BTC rarely exceeds 0.05%/8h. Altcoins spike regularly to 0.3–1%/8h during hype cycles. This bot scans **everything** across 5 exchanges simultaneously, not just BTC.

| Asset   | Rate typical | APY equiv | Daily on $500 |
|---------|-------------|-----------|--------------|
| BTC     | 0.03%/8h    | 32%       | $0.45        |
| ETH     | 0.04%/8h    | 44%       | $0.60        |
| SOL     | 0.08%/8h    | 94%       | $1.20        |
| PEPE    | 0.15%/8h    | 185%      | $2.25        |
| WIF/BONK| 0.30%/8h    | 408%      | $4.50        |
| Spike   | 1.00%/8h    | 1,983%    | $15.00       |

### Getting to $50/day

| Capital | Strategy |
|---------|---------|
| $500    | Chase altcoin spikes on Gate.io/Hyperliquid (manual + auto) |
| $2,000  | 4 altcoin positions at 0.2%/8h = ~$48/day during hype |
| $5,000  | 10 positions mixed BTC/altcoin, compounding over weeks |
| $10,000 | Conservative, reaches $50/day even on slow days |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Add API keys for any combination of: Binance, Bybit, OKX, Gate.io, Hyperliquid
```

## Usage

```bash
# Scan all 5 exchanges and show live dashboard — no orders placed
python bot.py

# Live trading
python bot.py --live

# Headless / server mode
python bot.py --no-ui
```

## Exchange API keys

- **Binance**: [binance.com/en/my/settings/api-management](https://www.binance.com/en/my/settings/api-management) — enable Spot + Futures
- **Bybit**: [bybit.com/app/user/api-management](https://www.bybit.com/app/user/api-management) — enable Unified Trading
- **OKX**: [okx.com/account/my-api](https://www.okx.com/account/my-api) — enable Trade
- **Gate.io**: [gate.io/myaccount/apikeys](https://www.gate.io/myaccount/apikeys) — enable Spot + Futures. Best for PEPE, SHIB, WIF, BONK, DOGE.
- **Hyperliquid**: No API key needed — just deposit USDC at [app.hyperliquid.xyz](https://app.hyperliquid.xyz). Set `HYPERLIQUID_WALLET` and `HYPERLIQUID_KEY` in `.env`. **No KYC required.** The bot scans rates here and flags signals; manual execution is cross-exchange (buy spot on Binance, short perp on HL).

## Auto-compounding

Every time total funding earned crosses a multiple of `COMPOUND_THRESHOLD` (default $100), the effective position size grows 10%. After $1,000 earned, each position is 2.6× its starting size. The dashboard shows compound progress as a bar.

```
$0    earned → position = $500 base
$100  earned → position = $550  (step 1, +10%)
$200  earned → position = $605  (step 2, +10%)
$500  earned → position = $805  (step 5, +61%)
$1000 earned → position = $1296 (step 10, +159%)
```

## Rate spike alerts

Any rate above `SPIKE_ALERT_RATE` (default 0.2%/8h = ~220% APY) triggers a visible `⚡ SPIKE` alert in the dashboard and log. These moments — liquidation cascades, memecoin mania — are peak income windows.

## Risks

- **Funding rate flip**: rate goes negative → you now PAY funding. Bot exits automatically when rate drops below `EXIT_FUNDING_RATE`.
- **Exchange risk**: funds on centralised exchanges. Don't keep more than you can afford to lose on any single exchange.
- **Execution risk**: if spot buy succeeds but perp short fails, you have an unhedged position. Bot logs a CRITICAL warning and does not proceed.
- **Slippage**: market orders have slippage. For large positions (>$5k), use limit orders manually.
- **Altcoin liquidity**: small-cap tokens can have thin order books. `MIN_MARK_PRICE` and `BLACKLIST_BASES` let you filter them out.

## What this bot does better than most

1. **Scans altcoins** — not just BTC/ETH. Altcoins are where the real rates are.
2. **5 exchanges in parallel** — Binance, Bybit, OKX, Gate.io, Hyperliquid simultaneously via `ThreadPoolExecutor`
3. **Auto-compound** — position size snowballs as profits accumulate, no manual adjustments needed
4. **Spike detection** — surfaces unusual rate events immediately (these are the alpha moments)
5. **Clean exits** — auto-exits when rate deteriorates, never holds through a flip
6. **Daily income tracking** — progress bar toward your daily target every scan
