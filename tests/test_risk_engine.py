"""
test_risk_engine — Unit tests for the pure, return-based functions in core/risk_engine.py.
Uses small synthetic return series instead of the real database (load_price_matrix /
load_common_daily_returns are DB-backed and intentionally not unit-tested here).
Run with: python -m pytest tests/test_risk_engine.py
"""

import os
import sys

CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import pandas as pd
import pytest

from risk_engine import compute_portfolio_path, compute_aggregate_metrics, value_at_or_before


# ----------------------------------------------------------------------------
# region COMPUTE_PORTFOLIO_PATH
# ----------------------------------------------------------------------------
def _two_asset_returns():
    """4 business days straddling a year boundary (2020-12-30 .. 2021-01-05), 2 tickers."""
    dates = pd.to_datetime(["2020-12-30", "2020-12-31", "2021-01-04", "2021-01-05"])
    return pd.DataFrame({"A": [0.10, 0.0, 0.0, 0.0], "B": [0.0, 0.0, 0.0, 0.0]}, index=dates)


def test_buy_and_hold_weights_drift_with_performance():
    """A outperforms on day 0 -> its realized weight must grow past the 60% target, never reset."""
    returns = _two_asset_returns()
    bh_returns, bh_weights = compute_portfolio_path({"A": 0.6, "B": 0.4}, returns, annual_rebalance=False)
    assert bh_returns.iloc[0] == pytest.approx(0.06)   # 0.6*0.10 + 0.4*0.0
    assert bh_weights.iloc[-1]["A"] == pytest.approx(0.6226415094339622)


def test_annual_rebalance_resets_weights_at_year_boundary():
    """Same returns, but annual_rebalance=True must reset weights back to target on 2021-01-04."""
    returns = _two_asset_returns()
    rb_returns, rb_weights = compute_portfolio_path({"A": 0.6, "B": 0.4}, returns, annual_rebalance=True)
    # Row index 2 = 2021-01-04, the first trading day of the new year.
    assert rb_weights.iloc[2]["A"] == pytest.approx(0.6)
    assert rb_weights.iloc[2]["B"] == pytest.approx(0.4)


def test_buy_and_hold_and_rebalanced_agree_before_any_year_boundary():
    """With no reset triggered yet, both variants must produce identical portfolio returns."""
    returns = _two_asset_returns()
    bh_returns, _ = compute_portfolio_path({"A": 0.6, "B": 0.4}, returns, annual_rebalance=False)
    rb_returns, _ = compute_portfolio_path({"A": 0.6, "B": 0.4}, returns, annual_rebalance=True)
    assert bh_returns.iloc[0] == pytest.approx(rb_returns.iloc[0])
# endregion


# ----------------------------------------------------------------------------
# region COMPUTE_AGGREGATE_METRICS
# ----------------------------------------------------------------------------
def _drawdown_test_series():
    """5 daily returns with a known, hand-verified drawdown/VaR/CVaR shape."""
    return pd.Series([0.0, -0.10, -0.05, 0.20, 0.0], index=pd.date_range("2021-01-01", periods=5, freq="B"))


def test_max_drawdown_matches_known_value():
    metrics = compute_aggregate_metrics(_drawdown_test_series())
    assert metrics["max_drawdown"] == pytest.approx(-0.145)


def test_var_and_cvar_95():
    metrics = compute_aggregate_metrics(_drawdown_test_series())
    assert metrics["var_95"] == pytest.approx(-0.09)
    assert metrics["cvar_95"] == pytest.approx(-0.10)


def test_worst_year_ignores_a_stub_year():
    """
    A partial year must not win the worst-year label. The backtest window opens
    mid-December and ends on whatever today is, so both edge years are stubs; a
    handful of bad days there would otherwise outrank a real crisis year.
    """
    full = pd.Series(-0.0005, index=pd.date_range("2022-01-03", periods=260, freq="B"))
    stub = pd.Series(-0.05, index=pd.date_range("2023-01-02", periods=5, freq="B"))
    metrics = compute_aggregate_metrics(pd.concat([full, stub]))
    assert metrics["worst_year"] == 2022


def test_worst_year_falls_back_when_no_year_is_complete():
    """A short series still reports a worst year — a wrong label beats none."""
    metrics = compute_aggregate_metrics(_drawdown_test_series())
    assert metrics["worst_year"] == 2021


def test_worst_year_and_missing_2008_return():
    metrics = compute_aggregate_metrics(_drawdown_test_series())
    assert metrics["worst_year"] == 2021
    assert metrics["year_2008_return"] is None
# endregion


# ----------------------------------------------------------------------------
# region VALUE_AT_OR_BEFORE
# ----------------------------------------------------------------------------
def test_value_at_or_before_returns_last_value_up_to_date():
    series = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2021-01-01", "2021-01-05", "2021-01-10"]))
    date_used, value = value_at_or_before(series, "2021-01-07")
    assert value == 2.0


def test_value_at_or_before_returns_none_when_series_starts_later():
    series = pd.Series([1.0], index=pd.to_datetime(["2021-06-01"]))
    date_used, value = value_at_or_before(series, "2021-01-01")
    assert date_used is None
    assert value is None
# endregion
