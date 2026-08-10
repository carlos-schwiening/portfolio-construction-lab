"""
Monte Carlo Terminal Wealth Projection (Forward-Looking)
=======================================================================
Run with: python core/monte_carlo.py

Simulates a DISTRIBUTION of possible future terminal wealth outcomes for a
given allocation archetype, start capital, and horizon — not a single point
estimate. Function-based (simulate_terminal_wealth) so a later dashboard can
call it directly.

METHOD (deliberately chosen, do not change without revisiting the rationale):
  - Base portfolio: the ANNUALLY REBALANCED portfolio from core/risk_engine.py
    (not buy-and-hold) — a forward projection must stay consistent with the
    chosen target allocation, not an allocation that has silently drifted.
  - Frequency: historical daily returns of the rebalanced portfolio are
    aggregated to MONTHLY returns.
  - Simulation: BLOCK BOOTSTRAP from the real historical monthly returns, NOT
    a normal distribution (real returns are fat-tailed; normal would
    understate tail risk). Random blocks of consecutive months (default 6,
    configurable) are drawn and concatenated until the horizon is covered,
    then truncated to horizon_years * 12 months. This preserves volatility
    clustering and crisis sequences that an i.i.d. draw would destroy.
  - 10,000 paths by default, fixed random seed (reproducibility matters for
    a portfolio project).

Results are NOMINAL (no inflation adjustment) and assume the future return
distribution resembles the historical 2007-today one — see Interpretation
for why that is optimistic, and why this script's Sensitivity section exists.

No charts here (come with the dashboard). No DB writes.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import sys
from typing import Literal, Union, cast, overload

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import numpy as np
import pandas as pd

try:
    from .allocations import get_normalized_weights, list_archetypes
    from .risk_engine import load_common_daily_returns, compute_portfolio_path
except ImportError:  # running directly as a script (python core/monte_carlo.py)
    from allocations import get_normalized_weights, list_archetypes  # type: ignore[import-not-found,no-redef]
    from risk_engine import load_common_daily_returns, compute_portfolio_path  # type: ignore[import-not-found,no-redef]

MONTHS_PER_YEAR = 12

DEMO_START_CAPITAL  = 100_000
DEMO_HORIZON_YEARS  = 20
DEMO_DETAIL_ARCHETYPE = "balanced"
DEMO_HAIRCUT          = 0.02  # 2pp annual haircut for the Sensitivity section (TEIL C)
# endregion


# ----------------------------------------------------------------------------
# region LOAD DATA (COMMON WINDOW, DAILY RETURNS)
# ----------------------------------------------------------------------------
# Reuses core/risk_engine.py's loader (same 9 active buckets, same runtime-determined
# common window) instead of duplicating the DB/window logic here.
daily_returns, common_start, first_valid_per_ticker = load_common_daily_returns()
# endregion


# ----------------------------------------------------------------------------
# region REBALANCED PORTFOLIO -> MONTHLY RETURNS
# ----------------------------------------------------------------------------
def get_historical_monthly_returns(archetype: str) -> np.ndarray:
    """
    Rebalanced (annual_rebalance=True) daily returns for the archetype, via
    core/risk_engine.py's compute_portfolio_path, compounded to monthly returns.
    """
    weights = get_normalized_weights(archetype)
    rebalanced_daily_returns, _weights_over_time = compute_portfolio_path(
        weights, daily_returns, annual_rebalance=True
    )
    monthly_returns = (1 + rebalanced_daily_returns).resample("ME").prod() - 1
    return np.asarray(monthly_returns.values)
# endregion


# ----------------------------------------------------------------------------
# region MONTE CARLO SIMULATION
# ----------------------------------------------------------------------------
def _simulate_block_bootstrap_paths(
    archetype: str, start_capital: float, horizon_years: int, n_paths: int,
    block_months: int, annual_return_haircut: float, seed: int,
) -> np.ndarray:
    """
    Shared block-bootstrap core, reused by simulate_terminal_wealth() and
    simulate_wealth_paths_percentiles() so both stay on the identical
    methodology (same seed, same block-draw logic) instead of duplicating it.

    Draws random blocks of `block_months` consecutive historical monthly
    returns (with replacement) from the archetype's rebalanced-portfolio
    history, concatenates them until horizon_years*12 months are covered,
    then truncates to that length. annual_return_haircut is subtracted
    pro-rata (haircut/12) from every drawn monthly return before compounding.

    Returns wealth_paths: np.ndarray, shape (n_paths, horizon_years*12) — the
    full monthly wealth value of every simulated path (month 1..horizon*12;
    month 0 / start_capital is not included here, callers add it if needed).
    """
    monthly_returns = get_historical_monthly_returns(archetype)
    monthly_haircut = annual_return_haircut / MONTHS_PER_YEAR
    monthly_returns_adjusted = monthly_returns - monthly_haircut

    n_available_months = len(monthly_returns_adjusted)
    n_months_total = horizon_years * MONTHS_PER_YEAR
    n_blocks_needed = int(np.ceil(n_months_total / block_months))

    rng = np.random.default_rng(seed)
    block_starts = rng.integers(0, n_available_months - block_months + 1, size=(n_paths, n_blocks_needed))

    offsets = np.arange(block_months)
    month_indices = block_starts[:, :, None] + offsets[None, None, :]
    month_indices = month_indices.reshape(n_paths, n_blocks_needed * block_months)[:, :n_months_total]

    path_returns = monthly_returns_adjusted[month_indices]  # shape (n_paths, n_months_total)
    cumulative_growth = np.cumprod(1 + path_returns, axis=1)
    wealth_paths = start_capital * cumulative_growth
    return wealth_paths


@overload
def simulate_terminal_wealth(
    archetype: str, start_capital: float, horizon_years: int, n_paths: int = 10000,
    block_months: int = 6, annual_return_haircut: float = 0.0, seed: int = 42,
    return_paths: Literal[False] = False,
) -> np.ndarray: ...


@overload
def simulate_terminal_wealth(
    archetype: str, start_capital: float, horizon_years: int, n_paths: int = 10000,
    block_months: int = 6, annual_return_haircut: float = 0.0, seed: int = 42,
    *, return_paths: Literal[True],
) -> tuple[np.ndarray, pd.DataFrame]: ...


def simulate_terminal_wealth(
    archetype: str, start_capital: float, horizon_years: int, n_paths: int = 10000,
    block_months: int = 6, annual_return_haircut: float = 0.0, seed: int = 42,
    return_paths: bool = False,
) -> Union[np.ndarray, tuple[np.ndarray, pd.DataFrame]]:
    """
    Block-bootstrap Monte Carlo projection of terminal wealth (see
    _simulate_block_bootstrap_paths for the methodology).

    Returns terminal_wealth (np.ndarray, shape (n_paths,)).
    If return_paths=True, also returns percentile_paths_df: a DataFrame
    indexed by month (1..horizon_years*12) with columns p5/p10/p25/p50/p75/p90/p95
    of the cumulative wealth path across all simulated paths (for later
    charting — not persisted here).
    """
    wealth_paths = _simulate_block_bootstrap_paths(
        archetype, start_capital, horizon_years, n_paths, block_months, annual_return_haircut, seed,
    )
    terminal_wealth = wealth_paths[:, -1]

    if not return_paths:
        return terminal_wealth

    n_months_total = horizon_years * MONTHS_PER_YEAR
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    percentile_values = np.percentile(wealth_paths, percentiles, axis=0)
    percentile_paths_df = pd.DataFrame(
        percentile_values.T,
        columns=[f"p{p}" for p in percentiles],
        index=pd.RangeIndex(1, n_months_total + 1, name="month"),
    )
    return terminal_wealth, percentile_paths_df


def simulate_wealth_paths_percentiles(
    archetype: str, start_capital: float, horizon_years: int, n_paths: int = 10000,
    block_months: int = 6, annual_return_haircut: float = 0.0, seed: int = 42,
) -> pd.DataFrame:
    """
    Full monthly wealth-path percentiles (P5/P25/Median/P75/P95) across all
    simulated paths, for a fan chart of projected wealth over time. Same
    block-bootstrap methodology and same default seed as simulate_terminal_wealth
    (via the shared _simulate_block_bootstrap_paths helper) — with the same
    archetype/capital/horizon/seed, the P50 value at the final month equals
    the median of simulate_terminal_wealth's terminal_wealth array.

    Month 0 is start_capital for every percentile (every path starts there
    identically). Full tail not capped. Vectorized (np.percentile over all
    paths at once) — no per-path Python loop.

    Returns a DataFrame with columns month, year, p5, p25, p50, p75, p95 and
    horizon_years*12 + 1 rows (month 0 through month horizon_years*12).
    """
    wealth_paths = _simulate_block_bootstrap_paths(
        archetype, start_capital, horizon_years, n_paths, block_months, annual_return_haircut, seed,
    )
    n_months_total = horizon_years * MONTHS_PER_YEAR

    percentiles = [5, 25, 50, 75, 95]
    percentile_values = np.percentile(wealth_paths, percentiles, axis=0)  # shape (5, n_months_total)

    start_column = np.full((len(percentiles), 1), start_capital)
    percentile_values = np.hstack([start_column, percentile_values])  # prepend month 0

    months = np.arange(0, n_months_total + 1)
    df = pd.DataFrame(percentile_values.T, columns=[f"p{p}" for p in percentiles])
    df.insert(0, "month", months)
    df.insert(1, "year", months / MONTHS_PER_YEAR)
    return df
# endregion


# ----------------------------------------------------------------------------
# region DEMO RUN
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"=== Monte Carlo Terminal Wealth Projection ===\n"
          f"start_capital = {DEMO_START_CAPITAL:,.0f}, horizon_years = {DEMO_HORIZON_YEARS}\n")

    # ---- TEIL A: all 4 archetypes, historical mean (haircut = 0) ----
    print("--- TEIL A: All Archetypes, Historical Mean (haircut = 0) ---")
    teil_a_rows = []
    teil_a_terminal_wealth = {}

    for archetype in list_archetypes():
        terminal_wealth = simulate_terminal_wealth(
            archetype, DEMO_START_CAPITAL, DEMO_HORIZON_YEARS, annual_return_haircut=0.0,
        )
        teil_a_terminal_wealth[archetype] = terminal_wealth

        teil_a_rows.append({
            "archetype": archetype,
            "p5": np.percentile(terminal_wealth, 5),
            "p25": np.percentile(terminal_wealth, 25),
            "median": np.percentile(terminal_wealth, 50),
            "p75": np.percentile(terminal_wealth, 75),
            "p95": np.percentile(terminal_wealth, 95),
            "shortfall_prob": np.mean(terminal_wealth < DEMO_START_CAPITAL),
        })

    df_teil_a = pd.DataFrame(teil_a_rows).set_index("archetype").loc[list_archetypes()]
    df_teil_a_display = df_teil_a.copy()
    for col in ["p5", "p25", "median", "p75", "p95"]:
        df_teil_a_display[col] = df_teil_a_display[col].map(lambda v: f"{v:,.0f}")
    df_teil_a_display["shortfall_prob"] = df_teil_a_display["shortfall_prob"].map(lambda v: f"{v:.2%}")
    print(df_teil_a_display.to_string())

    # ---- TEIL B: detail view for one archetype (balanced) ----
    print(f"\n--- TEIL B: Detail View — '{DEMO_DETAIL_ARCHETYPE}' ---")
    detail_wealth = teil_a_terminal_wealth[DEMO_DETAIL_ARCHETYPE]
    detail_percentiles = [5, 10, 25, 50, 75, 90, 95]
    for p in detail_percentiles:
        print(f"    p{p:>2}: {np.percentile(detail_wealth, p):>12,.0f}")

    median_wealth = np.percentile(detail_wealth, 50)
    implied_cagr_at_median = (median_wealth / DEMO_START_CAPITAL) ** (1 / DEMO_HORIZON_YEARS) - 1
    print(f"    Implied annualized return at median: {implied_cagr_at_median:+.2%}")

    # ---- TEIL C: sensitivity, balanced with haircut = 0 vs haircut = 0.02 ----
    print(f"\n--- TEIL C: Sensitivity — '{DEMO_DETAIL_ARCHETYPE}', haircut 0pp vs {DEMO_HAIRCUT:.0%} ---")
    haircut_wealth = simulate_terminal_wealth(
        DEMO_DETAIL_ARCHETYPE, DEMO_START_CAPITAL, DEMO_HORIZON_YEARS, annual_return_haircut=DEMO_HAIRCUT,
    )

    sensitivity_rows = [
        {
            "haircut": "0pp (historical mean)",
            "median": np.percentile(detail_wealth, 50),
            "p5": np.percentile(detail_wealth, 5),
            "shortfall_prob": np.mean(detail_wealth < DEMO_START_CAPITAL),
        },
        {
            "haircut": f"{DEMO_HAIRCUT:.0%} annual haircut",
            "median": np.percentile(haircut_wealth, 50),
            "p5": np.percentile(haircut_wealth, 5),
            "shortfall_prob": np.mean(haircut_wealth < DEMO_START_CAPITAL),
        },
    ]
    df_sensitivity = pd.DataFrame(sensitivity_rows).set_index("haircut")
    df_sensitivity_display = df_sensitivity.copy()
    for col in ["median", "p5"]:
        df_sensitivity_display[col] = df_sensitivity_display[col].map(lambda v: f"{v:,.0f}")
    df_sensitivity_display["shortfall_prob"] = df_sensitivity_display["shortfall_prob"].map(lambda v: f"{v:.2%}")
    print(df_sensitivity_display.to_string())
    # endregion (Demo Run output)

    # ------------------------------------------------------------------------
    # region INTERPRETATION
    # ------------------------------------------------------------------------
    print("\n=== Interpretation ===")

    print(">>> Results are NOMINAL — no inflation adjustment. Over a 20-year horizon this materially "
          "overstates real purchasing power; treat all wealth figures above as before-inflation.")

    print(">>> The simulation assumes the future return distribution resembles the historical 2007-today "
          "one. That period contained an extraordinary bond bull market (falling rates for most of it), "
          "so the historical mean used for haircut=0 is likely optimistic going forward — exactly why "
          "the haircut sensitivity in TEIL C exists.")

    median_diff = cast(float, df_sensitivity.loc[f"{DEMO_HAIRCUT:.0%} annual haircut", "median"]) - cast(
        float, df_sensitivity.loc["0pp (historical mean)", "median"])
    shortfall_diff = cast(float, df_sensitivity.loc[f"{DEMO_HAIRCUT:.0%} annual haircut", "shortfall_prob"]) - cast(
        float, df_sensitivity.loc["0pp (historical mean)", "shortfall_prob"])
    print(f">>> A {DEMO_HAIRCUT:.0%} annual return haircut moves the '{DEMO_DETAIL_ARCHETYPE}' median terminal "
          f"wealth by {median_diff:+,.0f} and the shortfall probability by {shortfall_diff:+.2%} — a small "
          "annual assumption change compounds into a large 20-year outcome difference.")

    print(">>> No transaction costs or taxes are modeled.")

    print(">>> Block bootstrap preserves volatility clustering and historical crisis sequences (e.g. 2008, "
          "2020), but still assumes the underlying return DISTRIBUTION is stationary going forward — regime "
          "shifts such as the stock-bond correlation flip (see core/risk_engine.py) are NOT modeled here.")
    # endregion

    # ------------------------------------------------------------------------
    # region LEGENDE
    # ------------------------------------------------------------------------
    print("\n=== Legende ===")
    print("simulate_terminal_wealth = Block-bootstrap Monte Carlo function; returns an array of n_paths terminal wealth outcomes")
    print("block_months             = Length of each resampled block of consecutive historical months (default 6)")
    print("annual_return_haircut    = Annual return deduction (pro-rata monthly) applied to every drawn return; 0.0 = pure historical mean")
    print("n_paths                  = Number of simulated wealth paths (default 10,000)")
    print("seed                     = Fixed random seed for reproducibility")
    print("p5/p25/median/p75/p95    = Percentiles of the terminal wealth distribution across all simulated paths")
    print("shortfall_prob           = Fraction of simulated paths ending below start_capital (nominal)")
    print("implied_cagr_at_median   = Annualized return implied by the median terminal wealth outcome")
    print("percentile_paths_df      = Optional (return_paths=True) month-by-month percentile wealth paths, for later charting")
    # endregion
