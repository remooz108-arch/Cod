"""Unit tests for RiskManager: position limits, daily loss, cooldowns."""

import pytest
import sys
import os
import time
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import Config
from src.models import Market, Opportunity, Trade
from src.risk import RiskManager


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_config(**overrides) -> Config:
    base = dict(
        private_key="",
        funder_address="",
        min_spread_bps=50,
        max_position_usdc=100.0,
        max_total_deployed_usdc=500.0,
        daily_loss_limit_usdc=50.0,
        scan_interval_ms=500,
        use_websocket=False,
        dry_run=True,
        log_file="test.jsonl",
        max_concurrent_markets=50,
        cooldown_after_failures=5,
        min_market_liquidity_usdc=100.0,
    )
    base.update(overrides)
    return Config(**base)


def make_opportunity(condition_id: str = "cond_001") -> Opportunity:
    market = Market(
        condition_id=condition_id,
        question="Test market?",
        yes_token_id="yes",
        no_token_id="no",
        tick_size=0.01,
        min_order_size=5.0,
        outcome_prices=(0.45, 0.45),
        active=True,
        accepting_orders=True,
    )
    return Opportunity(
        market=market,
        best_ask_yes=0.45,
        best_ask_no=0.45,
        pair_cost=0.90,
        estimated_profit_pct=0.098,
        estimated_profit_usdc=9.8,
        depth_yes_usdc=500.0,
        depth_no_usdc=500.0,
        detected_at=datetime.utcnow(),
    )


def make_trade(opp: Opportunity, status: str = "filled", size: float = 100.0) -> Trade:
    return Trade(
        opportunity=opp,
        yes_order_id="yes_ord_001",
        no_order_id="no_ord_001",
        yes_fill_price=0.45,
        no_fill_price=0.45,
        size_usdc=size,
        status=status,
        executed_at=datetime.utcnow(),
        pnl_usdc=9.8,
    )


# ── Tests: can_trade ──────────────────────────────────────────────────────────

class TestCanTrade:
    def test_allows_trade_when_all_clear(self):
        rm = RiskManager(make_config())
        opp = make_opportunity()
        ok, reason = rm.can_trade(opp)
        assert ok is True
        assert reason == "OK"

    def test_blocks_when_total_deployed_at_limit(self):
        # max_position=100, max_total=500, already deployed 450 → would hit 550
        config = make_config(max_position_usdc=100.0, max_total_deployed_usdc=500.0)
        rm = RiskManager(config)
        rm._total_deployed = 450.0  # inject state

        opp = make_opportunity()
        ok, reason = rm.can_trade(opp)
        assert ok is False
        assert "Capital limit" in reason

    def test_blocks_when_daily_loss_exceeded(self):
        config = make_config(daily_loss_limit_usdc=50.0)
        rm = RiskManager(config)
        rm._daily_pnl = -60.0  # injected loss

        opp = make_opportunity()
        ok, reason = rm.can_trade(opp)
        assert ok is False
        assert "loss limit" in reason

    def test_blocks_duplicate_market(self):
        config = make_config()
        rm = RiskManager(config)
        opp = make_opportunity("cond_dup")
        trade = make_trade(opp, status="filled")
        rm._open_positions["cond_dup"] = trade  # inject existing position

        ok, reason = rm.can_trade(opp)
        assert ok is False
        assert "open position" in reason

    def test_allows_different_markets(self):
        config = make_config()
        rm = RiskManager(config)
        existing_opp = make_opportunity("cond_001")
        rm._open_positions["cond_001"] = make_trade(existing_opp)

        new_opp = make_opportunity("cond_002")
        ok, reason = rm.can_trade(new_opp)
        assert ok is True

    def test_blocks_during_cooldown(self):
        config = make_config(cooldown_after_failures=10)
        rm = RiskManager(config)
        rm._cooldown_until = time.monotonic() + 9.0  # active cooldown

        opp = make_opportunity()
        ok, reason = rm.can_trade(opp)
        assert ok is False
        assert "Cooldown" in reason

    def test_allows_after_cooldown_expires(self):
        config = make_config()
        rm = RiskManager(config)
        rm._cooldown_until = time.monotonic() - 1.0  # expired

        opp = make_opportunity()
        ok, reason = rm.can_trade(opp)
        assert ok is True


# ── Tests: record_trade ───────────────────────────────────────────────────────

class TestRecordTrade:
    def test_filled_trade_updates_deployed_and_clears_streak(self):
        config = make_config()
        rm = RiskManager(config)
        rm._failure_streak = 2
        opp = make_opportunity()
        trade = make_trade(opp, status="filled", size=100.0)

        rm.record_trade(trade)

        assert rm.get_total_deployed() == pytest.approx(100.0)
        assert rm._failure_streak == 0
        assert "cond_001" in rm.get_open_positions()

    def test_failed_trade_increments_streak(self):
        config = make_config()
        rm = RiskManager(config)
        opp = make_opportunity()
        trade = make_trade(opp, status="failed")

        rm.record_trade(trade)
        assert rm._failure_streak == 1
        assert rm.get_total_deployed() == 0.0

    def test_partial_trade_triggers_single_leg_warning(self):
        config = make_config()
        rm = RiskManager(config)
        opp = make_opportunity()
        trade = make_trade(opp, status="partial", size=100.0)

        rm.record_trade(trade)

        assert len(rm.get_single_leg_warnings()) == 1
        assert rm.get_total_deployed() == pytest.approx(100.0)

    def test_three_failures_trigger_cooldown(self):
        config = make_config(cooldown_after_failures=5)
        rm = RiskManager(config)
        opp = make_opportunity()

        for i in range(3):
            trade = make_trade(make_opportunity(f"cond_{i}"), status="failed")
            rm.record_trade(trade)

        assert rm._cooldown_until > time.monotonic()
        assert rm._failure_streak == 0  # reset after cooldown

    def test_dry_run_trade_not_counted_in_fill_rate(self):
        config = make_config()
        rm = RiskManager(config)
        opp = make_opportunity()
        dry_trade = make_trade(opp, status="dry_run")
        rm.record_trade(dry_trade)

        # fill_rate should be 1.0 (no live trades)
        assert rm.get_fill_rate() == pytest.approx(1.0)
        assert rm.get_total_deployed() == 0.0


# ── Tests: close_position ────────────────────────────────────────────────────

class TestClosePosition:
    def test_close_removes_position_and_updates_pnl(self):
        config = make_config()
        rm = RiskManager(config)
        opp = make_opportunity("cond_close")
        trade = make_trade(opp, status="filled", size=100.0)
        rm.record_trade(trade)

        rm.close_position("cond_close", resolved_pnl=9.8)

        assert "cond_close" not in rm.get_open_positions()
        assert rm.get_total_deployed() == pytest.approx(0.0)
        assert rm.get_daily_pnl() == pytest.approx(9.8)
        assert rm.get_total_pnl() == pytest.approx(9.8)

    def test_close_nonexistent_position_is_noop(self):
        config = make_config()
        rm = RiskManager(config)
        rm.close_position("nonexistent", 10.0)  # should not raise
        assert rm.get_total_pnl() == 0.0


# ── Tests: reset_daily ───────────────────────────────────────────────────────

class TestResetDaily:
    def test_reset_clears_daily_pnl(self):
        config = make_config()
        rm = RiskManager(config)
        rm._daily_pnl = 42.0

        rm.reset_daily()
        assert rm.get_daily_pnl() == pytest.approx(0.0)

    def test_reset_does_not_clear_total_pnl(self):
        config = make_config()
        rm = RiskManager(config)
        rm._total_pnl = 100.0
        rm._daily_pnl = 42.0

        rm.reset_daily()
        assert rm.get_total_pnl() == pytest.approx(100.0)


# ── Tests: stats ─────────────────────────────────────────────────────────────

class TestStats:
    def test_get_stats_returns_all_fields(self):
        config = make_config()
        rm = RiskManager(config)
        stats = rm.get_stats()

        required_keys = {
            "total_deployed", "daily_pnl", "total_pnl",
            "open_positions", "single_leg_warnings",
            "fill_rate", "total_trades", "filled_trades",
        }
        assert required_keys.issubset(set(stats.keys()))
