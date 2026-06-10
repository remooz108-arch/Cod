"""Unit tests for scanner: opportunity detection with mocked order book data."""

import pytest
import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import Market, OrderBook, OrderLevel
from src.config import Config
from src.scanner import _evaluate_opportunity, _parse_market


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_config(**overrides) -> Config:
    base = dict(
        private_key="",
        funder_address="",
        min_spread_bps=50,
        max_position_usdc=500.0,
        max_total_deployed_usdc=5000.0,
        daily_loss_limit_usdc=100.0,
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


def make_market(yes_id: str = "yes_tok", no_id: str = "no_tok") -> Market:
    return Market(
        condition_id="cond_abc123",
        question="Will it rain tomorrow?",
        yes_token_id=yes_id,
        no_token_id=no_id,
        tick_size=0.01,
        min_order_size=5.0,
        outcome_prices=(0.55, 0.45),
        active=True,
        accepting_orders=True,
    )


def make_book(token_id: str, ask_price: float, ask_size: float = 1000.0) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[OrderLevel(price=ask_price - 0.01, size=1000)],
        asks=[OrderLevel(price=ask_price, size=ask_size)],
        timestamp=datetime.utcnow(),
    )


# ── Tests: _evaluate_opportunity ─────────────────────────────────────────────

class TestEvaluateOpportunity:
    def test_detects_arb_when_pair_cost_below_threshold(self):
        """YES=0.45 + NO=0.45 = 0.90. Net profit = 0.10*0.98 = 0.098 ≥ 0.005."""
        config = make_config(min_spread_bps=50, min_market_liquidity_usdc=100)
        market = make_market()
        yes_book = make_book("yes_tok", ask_price=0.45)
        no_book = make_book("no_tok", ask_price=0.45)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)

        assert opp is not None
        assert opp.pair_cost == pytest.approx(0.90)
        assert opp.best_ask_yes == pytest.approx(0.45)
        assert opp.best_ask_no == pytest.approx(0.45)
        assert opp.estimated_profit_pct > 0

    def test_no_opportunity_when_pair_cost_above_threshold(self):
        """YES=0.50 + NO=0.51 = 1.01. No profit."""
        config = make_config(min_spread_bps=50)
        market = make_market()
        yes_book = make_book("yes_tok", ask_price=0.50)
        no_book = make_book("no_tok", ask_price=0.51)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)
        assert opp is None

    def test_no_opportunity_at_exactly_one(self):
        """YES=0.50 + NO=0.50 = 1.00. Zero profit."""
        config = make_config(min_spread_bps=50)
        market = make_market()
        yes_book = make_book("yes_tok", ask_price=0.50)
        no_book = make_book("no_tok", ask_price=0.50)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)
        assert opp is None

    def test_no_opportunity_when_yes_book_is_none(self):
        config = make_config()
        market = make_market()
        no_book = make_book("no_tok", ask_price=0.45)

        opp = _evaluate_opportunity(market, None, no_book, config)
        assert opp is None

    def test_no_opportunity_when_no_book_is_none(self):
        config = make_config()
        market = make_market()
        yes_book = make_book("yes_tok", ask_price=0.45)

        opp = _evaluate_opportunity(market, yes_book, None, config)
        assert opp is None

    def test_filters_illiquid_yes_side(self):
        """YES side has only $50 depth — below min_market_liquidity_usdc=100."""
        config = make_config(min_market_liquidity_usdc=100.0)
        market = make_market()
        # ask_price=0.45, size=100 → depth = 0.45*100 = $45 < $100
        yes_book = make_book("yes_tok", ask_price=0.45, ask_size=100.0)
        no_book = make_book("no_tok", ask_price=0.45, ask_size=10000.0)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)
        assert opp is None

    def test_filters_illiquid_no_side(self):
        """NO side has only $50 depth — below threshold."""
        config = make_config(min_market_liquidity_usdc=100.0)
        market = make_market()
        yes_book = make_book("yes_tok", ask_price=0.45, ask_size=10000.0)
        no_book = make_book("no_tok", ask_price=0.45, ask_size=100.0)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)
        assert opp is None

    def test_accounts_for_fee_in_profitability_check(self):
        """
        pair_cost = 0.9951.
        gross = 0.0049, net = 0.0049 * 0.98 = 0.00480...
        min_spread = 50 bps = 0.005 → should NOT be an opportunity.
        """
        config = make_config(min_spread_bps=50, min_market_liquidity_usdc=10)
        market = make_market()
        # pair cost ~0.9951
        yes_book = make_book("yes_tok", ask_price=0.4976, ask_size=10000)
        no_book = make_book("no_tok", ask_price=0.4975, ask_size=10000)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)
        assert opp is None

    def test_opportunity_profit_usdc_calculation(self):
        """Verify estimated_profit_usdc is proportional to position size."""
        config = make_config(
            min_spread_bps=50,
            max_position_usdc=100.0,
            min_market_liquidity_usdc=50.0,
        )
        market = make_market()
        yes_book = make_book("yes_tok", ask_price=0.40, ask_size=10000)
        no_book = make_book("no_tok", ask_price=0.40, ask_size=10000)

        opp = _evaluate_opportunity(market, yes_book, no_book, config)
        assert opp is not None
        assert opp.estimated_profit_usdc > 0
        assert opp.estimated_profit_usdc <= config.max_position_usdc


# ── Tests: _parse_market ──────────────────────────────────────────────────────

class TestParseMarket:
    def _raw(self, **overrides) -> dict:
        base = {
            "conditionId": "0xabc",
            "question": "Test market?",
            "active": True,
            "accepting_orders": True,
            "outcomePrices": '["0.6","0.4"]',
            "clobTokenIds": '["tok_yes","tok_no"]',
            "tickSize": 0.01,
            "minOrderSize": 5,
        }
        base.update(overrides)
        return base

    def test_parses_valid_binary_market(self):
        m = _parse_market(self._raw())
        assert m is not None
        assert m.condition_id == "0xabc"
        assert m.yes_token_id == "tok_yes"
        assert m.no_token_id == "tok_no"
        assert m.outcome_prices == (0.6, 0.4)
        assert m.tick_size == 0.01
        assert m.min_order_size == 5.0

    def test_rejects_inactive_market(self):
        assert _parse_market(self._raw(active=False)) is None

    def test_rejects_market_not_accepting_orders(self):
        assert _parse_market(self._raw(accepting_orders=False)) is None

    def test_rejects_non_binary_market(self):
        # 3 outcomes — not binary
        raw = self._raw(
            outcomePrices='["0.33","0.33","0.34"]',
            clobTokenIds='["t1","t2","t3"]',
        )
        assert _parse_market(raw) is None

    def test_rejects_single_outcome(self):
        raw = self._raw(
            outcomePrices='["1.0"]',
            clobTokenIds='["t1"]',
        )
        assert _parse_market(raw) is None

    def test_handles_missing_tick_size(self):
        raw = self._raw()
        raw.pop("tickSize", None)
        m = _parse_market(raw)
        assert m is not None
        assert m.tick_size == 0.01  # default

    def test_handles_alternative_field_names(self):
        raw = {
            "condition_id": "0xdef",
            "question": "Alt fields?",
            "active": True,
            "accepting_orders": True,
            "outcomePrices": '["0.5","0.5"]',
            "clobTokenIds": '["a","b"]',
        }
        m = _parse_market(raw)
        assert m is not None
        assert m.condition_id == "0xdef"
