"""Unit tests for utils: price parsing, tick rounding, profit calculations."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils import (
    format_pct,
    format_usdc,
    is_opportunity,
    parse_price_list,
    parse_token_ids,
    profit_after_fee,
    round_to_tick,
)


class TestParsePriceList:
    def test_json_string(self):
        assert parse_price_list('["0.55","0.45"]') == [0.55, 0.45]

    def test_plain_list(self):
        assert parse_price_list([0.6, 0.4]) == [0.6, 0.4]

    def test_list_of_strings(self):
        assert parse_price_list(["0.7", "0.3"]) == [0.7, 0.3]

    def test_malformed_json(self):
        assert parse_price_list("not-json") == []

    def test_empty_string(self):
        assert parse_price_list("[]") == []

    def test_empty_list(self):
        assert parse_price_list([]) == []

    def test_single_price(self):
        assert parse_price_list('["1.0"]') == [1.0]


class TestParseTokenIds:
    def test_json_string(self):
        result = parse_token_ids('["abc123","def456"]')
        assert result == ["abc123", "def456"]

    def test_plain_list(self):
        assert parse_token_ids(["tok1", "tok2"]) == ["tok1", "tok2"]

    def test_malformed(self):
        assert parse_token_ids("bad") == []

    def test_empty(self):
        assert parse_token_ids("[]") == []


class TestRoundToTick:
    def test_exact_tick(self):
        assert round_to_tick(0.45, 0.01) == pytest.approx(0.45)

    def test_round_down(self):
        assert round_to_tick(0.459, 0.01) == pytest.approx(0.45)

    def test_zero_tick_passthrough(self):
        assert round_to_tick(0.456789, 0) == pytest.approx(0.456789)

    def test_large_tick(self):
        assert round_to_tick(0.09, 0.1) == pytest.approx(0.0)

    def test_one_cent_tick(self):
        assert round_to_tick(1.239, 0.01) == pytest.approx(1.23)


class TestProfitAfterFee:
    def test_no_profit_at_cost_one(self):
        assert profit_after_fee(1.0) == 0.0

    def test_no_profit_above_cost_one(self):
        assert profit_after_fee(1.05) == 0.0

    def test_basic_profit(self):
        # pair_cost=0.95 → gross=0.05 → net=0.05*0.98=0.049
        result = profit_after_fee(0.95, fee_rate=0.02)
        assert result == pytest.approx(0.049, abs=1e-6)

    def test_zero_fee(self):
        assert profit_after_fee(0.90, fee_rate=0.0) == pytest.approx(0.10)

    def test_high_fee(self):
        result = profit_after_fee(0.90, fee_rate=0.50)
        assert result == pytest.approx(0.05)


class TestIsOpportunity:
    def test_detects_opportunity(self):
        # pair_cost=0.90, min_spread=0.05 → profit≈0.098 ≥ 0.05
        assert is_opportunity(0.90, min_spread=0.05) is True

    def test_no_opportunity_tight_spread(self):
        # pair_cost=0.999 → profit≈0.00098 < 0.005
        assert is_opportunity(0.999, min_spread=0.005) is False

    def test_boundary_exactly_at_min(self):
        # pair_cost where net profit == min_spread exactly
        # net = (1 - cost) * 0.98 = min_spread → cost = 1 - min_spread/0.98
        min_spread = 0.005
        cost = 1 - min_spread / 0.98
        # Should pass (==)
        assert is_opportunity(cost, min_spread=min_spread) is True

    def test_at_one_no_opportunity(self):
        assert is_opportunity(1.0, min_spread=0.001) is False

    def test_above_one_no_opportunity(self):
        assert is_opportunity(1.05, min_spread=0.001) is False


class TestFormatters:
    def test_format_usdc(self):
        assert format_usdc(1234.5) == "$1,234.50"
        assert format_usdc(0) == "$0.00"
        assert format_usdc(-50.1) == "$-50.10"

    def test_format_pct(self):
        assert format_pct(0.0532) == "5.32%"
        assert format_pct(0) == "0.00%"
