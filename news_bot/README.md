# Trump + Iran + Israel Headline Prediction Bot

Polls 6 major news RSS feeds. If a **single headline** contains **Trump**, **Iran**, and **Israel** all at once, the bot searches Polymarket for active prediction markets related to the conflict and places YES bets on them.

## Signal rule

```
FOR each new RSS headline (title only):
    IF "trump" AND "iran" AND "israel" all appear in the title:
        → Search Polymarket for Israel/Iran conflict markets
        → BET YES on each relevant market
```

Only headline **titles** are matched — not article bodies.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in POLY_PRIVATE_KEY and POLY_FUNDER_ADDRESS for live betting
# Leave blank for scan-only / dry-run mode
```

## Usage

```bash
# Dry-run loop (scans every 2 minutes, prints signal but places no bets)
python bot.py

# Single scan, dry-run (good for testing)
python bot.py --once

# Find matching headlines and show markets, never bet
python bot.py --scan-only

# Live betting
python bot.py --live
```

## Output files

| File | Contents |
|---|---|
| `seen_headlines.json` | Headline IDs already processed (prevents re-triggering) |
| `signals.log` | Every headline that fired the signal + markets found + bets placed |
