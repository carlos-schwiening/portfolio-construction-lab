"""
test_monte_carlo — Tests for the block-bootstrap simulation in core/monte_carlo.py.

Different testing style than the other test files: this is a stochastic simulation,
so we do not assert exact output values. Instead we check invariants that must hold
regardless of the random draw — reproducibility under a fixed seed, structural
properties (shape, positivity, percentile ordering), and directional effects (a
return haircut must lower the outcome). Uses the real local database (module-level
load at import time; not mocked here) with a small n_paths for test speed.

Run with: python -m pytest tests/test_monte_carlo.py
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "portfolio_data.db")
if not os.path.exists(DB_PATH):
    # data/portfolio_data.db is gitignored (reproducible via data/db_pull_v1.py, not
    # redistributed). Importing monte_carlo.py no longer needs it, but every test
    # below runs a simulation on real returns, so skip cleanly instead of failing
    # in a fresh CI checkout that has no local database.
    pytest.skip(f"portfolio_data.db not found at {DB_PATH} — run data/db_pull_v1.py first",
                allow_module_level=True)

CORE_DIR = os.path.join(PROJECT_ROOT, "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import numpy as np

from monte_carlo import simulate_terminal_wealth, simulate_wealth_paths_percentiles

N_PATHS_TEST = 200   # small on purpose — these tests check properties, not precision
ARCHETYPE = "balanced"
START_CAPITAL = 100_000
HORIZON_YEARS = 20


def test_same_seed_is_fully_reproducible():
    w1 = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)
    w2 = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)
    assert np.array_equal(w1, w2)


def test_terminal_wealth_shape_and_positivity():
    wealth = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)
    assert wealth.shape == (N_PATHS_TEST,)
    assert (wealth > 0).all()   # multiplicative growth model can never go negative


def test_terminal_wealth_scales_linearly_with_start_capital():
    """Doubling start capital must exactly double every simulated outcome (same seed -> same draws)."""
    w1 = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)
    w2 = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL * 2, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)
    assert w2 == pytest.approx(w1 * 2)


def test_return_haircut_lowers_median_outcome():
    """A positive annual haircut must reduce the median terminal wealth vs. the historical-mean case."""
    baseline = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)
    haircut  = simulate_terminal_wealth(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST,
                                         seed=42, annual_return_haircut=0.05)
    assert np.median(haircut) < np.median(baseline)


def test_percentile_paths_start_at_capital_and_are_ordered():
    df = simulate_wealth_paths_percentiles(ARCHETYPE, START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS_TEST, seed=42)

    month_zero = df.iloc[0]
    for col in ["p5", "p25", "p50", "p75", "p95"]:
        assert month_zero[col] == START_CAPITAL

    assert (df["p5"] <= df["p25"]).all()
    assert (df["p25"] <= df["p50"]).all()
    assert (df["p50"] <= df["p75"]).all()
    assert (df["p75"] <= df["p95"]).all()
