"""
Optional Telegram notifications — phone alerts for position events, spikes, daily summary.

Setup:
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Start a chat with your new bot, then visit:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     to find your chat_id.
  3. Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env
"""

from __future__ import annotations

import threading

import config


def _send(text: str) -> None:
    """Fire-and-forget: send in a background thread so the main loop never blocks."""
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    threading.Thread(target=_post, args=(text,), daemon=True).start()


def _post(text: str) -> None:
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception as exc:
        print(f"  [notify] Telegram failed: {exc}")


def position_opened(exchange: str, base: str, size_usdc: float, rate_8h: float, apy: float) -> None:
    _send(
        f"🟢 <b>ENTERED</b> {exchange.upper()} {base}\n"
        f"Size: ${size_usdc:.0f}  |  Rate: {rate_8h:.4%}/8h  |  APY: {apy:.0f}%"
    )


def position_closed(exchange: str, base: str, reason: str, earned: float) -> None:
    _send(
        f"🔴 <b>EXITED</b> {exchange.upper()} {base}\n"
        f"Reason: {reason}  |  Collected: ${earned:.4f}"
    )


def rotation(old_base: str, old_rate: float, new_base: str, new_rate: float) -> None:
    _send(
        f"🔄 <b>ROTATION</b>\n"
        f"Closed  {old_base}  ({old_rate:.4%}/8h)\n"
        f"Opening {new_base}  ({new_rate:.4%}/8h)"
    )


def spike_alert(exchange: str, base: str, rate_8h: float, apy: float) -> None:
    _send(
        f"⚡ <b>RATE SPIKE</b>  {exchange.upper()} {base}\n"
        f"{rate_8h:.4%}/8h  =  {apy:.0f}% APY"
    )


def margin_alert(exchange: str, base: str, ratio: float, action: str) -> None:
    exited = action.upper() == "EXITED"
    _send(
        f"{'🔴' if exited else '🟡'} <b>MARGIN {action.upper()}</b>  {exchange.upper()} {base}\n"
        f"Margin ratio: {ratio:.2f}  "
        f"{'— Position closed to prevent liquidation!' if exited else '— Monitor closely, approaching danger zone.'}"
    )


def hedge_drift_alert(exchange: str, base: str, drift_pct: float) -> None:
    _send(
        f"⚠️ <b>HEDGE DRIFT</b>  {exchange.upper()} {base}\n"
        f"Price has moved {drift_pct:.1%} from entry — delta-neutral hedge is drifting.\n"
        f"Auto-exit triggers at {config.HEDGE_DRIFT_EXIT_PCT:.0%}."
    )


def circuit_breaker_alert(exits_in_hour: int) -> None:
    _send(
        f"🚨 <b>CIRCUIT BREAKER OPEN</b>\n"
        f"{exits_in_hour} positions exited due to rate flips in the last hour.\n"
        f"New entries paused until regime stabilises."
    )


def daily_summary(
    earned_today: float, total_earned: float, open_positions: int, target: float
) -> None:
    pct = earned_today / max(target, 0.01) * 100
    _send(
        f"📊 <b>DAILY SUMMARY</b>\n"
        f"Today:    ${earned_today:.4f}  ({pct:.0f}% of ${target:.0f} target)\n"
        f"All-time: ${total_earned:.4f}\n"
        f"Open positions: {open_positions}"
    )
