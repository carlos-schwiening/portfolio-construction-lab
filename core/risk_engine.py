"""
Risk Engine — Buy-and-Hold vs Annual Rebalancing, All Archetypes + Rolling Metrics
=======================================================================
Run with: python core/risk_engine.py

Computes aggregate risk/return metrics (CAGR, annualized vol, max drawdown,
VaR/CVaR 95%, worst calendar year, 2008 return) for ALL 4 archetypes from
allocations.list_archetypes() (conservative, moderate, balanced, growth).
Loads adjusted-close prices for the 9 active buckets (QAI/Alternatives
excluded, see project status) from data\\portfolio_data.db, determines the
common backtest window AT RUNTIME (latest per-ticker inception date — not
hardcoded).

Two portfolio construction variants, side by side:
  - buy_and_hold:  weights start at target and DRIFT freely with cumulative
                   performance for the entire window. No resets at all.
  - rebalanced:    weights reset to target on the first trading day of every
                   calendar year, then drift within the year. No transaction
                   costs/taxes modeled (frictionless rebalancing assumption).
Both use only past information for any reset (no lookahead bias).

CORRECTION vs the Step 3/4 version of this script: the old single-variant
calculation (`sum(w_i * r_i(t))` with FIXED w_i every day) is mathematically
a DAILY-rebalanced portfolio, not buy-and-hold, despite being labeled "no
rebalancing" — fixed weights every day can only hold if you trade daily to
maintain them. This version replaces it with true drifting buy-and-hold and
adds the annually-rebalanced variant next to it, so the comparison in TEIL B/C
is meaningful. Some previously reported numbers (e.g. growth volatility)
change slightly as a result — this is the corrected, intended calculation.

Adds rolling 1-year metrics to make non-stationarity visible:
  - rolling 252-day annualized volatility, per archetype (buy-and-hold)
  - rolling 252-day correlation between SPY and AGG (portfolio-independent,
    printed once) — shows that stock/bond diversification is NOT stationary
    (negative/mixed pre-~2021, drifting positive after).

Rolling time series, and the daily drifting-weight paths, are computed at
runtime only and NOT persisted to the DB.

REUSABILITY: all computation lives in return-based functions (no printing) so
a dashboard (app.py) can import and call them directly — see in particular
get_archetype_metrics() for a single archetype's buy-and-hold + rebalanced
aggregate metrics. The __main__ block below is purely a thin terminal report
on top of these functions; running this file directly is unaffected.
"""

# region Imports & Configuration
import sys
import os
import sqlite3

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from allocations import get_normalized_weights, list_archetypes, PROXY_LABELS

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH      = os.path.join(PROJECT_ROOT, "data", "portfolio_data.db")

ACTIVE_TICKERS    = list(PROXY_LABELS.keys())  # the 9 active buckets, QAI already excluded
TRADING_DAYS_YEAR = 252
VAR_CONFIDENCE    = 0.95
ROLLING_WINDOW    = 252  # ~1 trading year

CORRELATION_CHECKPOINT_YEARS = [2008, 2012, 2016, 2020, 2022, 2024]
EQUITY_TICKERS    = ["SPY", "EFA", "EEM"]
DRIFT_DEMO_ARCHETYPE = "growth"  # drift is largest here, per TEIL C

ARCHETYPE_ORDER = list_archetypes()  # conservative -> growth, as defined in allocations.py
# endregion


# region Load Data
def load_price_matrix(db_path, tickers):
    """Loads adj_close for the given tickers from the prices table, pivoted to date x symbol."""
    conn = sqlite3.connect(db_path)
    placeholders = ",".join("?" * len(tickers))
    query = f"SELECT symbol, date, adj_close FROM prices WHERE symbol IN ({placeholders})"
    df_long = pd.read_sql_query(query, conn, params=tickers)
    conn.close()

    df_long["date"] = pd.to_datetime(df_long["date"])
    price_matrix = df_long.pivot(index="date", columns="symbol", values="adj_close").sort_index()
    return price_matrix


def load_common_daily_returns(db_path=DB_PATH, tickers=ACTIVE_TICKERS):
    """
    Loads the 9 active buckets, determines the common backtest window at
    runtime (latest per-ticker inception date), and returns daily returns
    inner-joined across all tickers from that point on.

    Returns (daily_returns: DataFrame, common_start: Timestamp,
    first_valid_per_ticker: Series).
    """
    price_matrix_raw = load_price_matrix(db_path, tickers)

    first_valid_per_ticker = price_matrix_raw.apply(lambda col: col.first_valid_index())
    common_start = first_valid_per_ticker.max()

    price_matrix = price_matrix_raw.loc[price_matrix_raw.index >= common_start]
    price_matrix = price_matrix.dropna(how="any")  # inner join across all 9 tickers

    daily_returns = price_matrix.pct_change().dropna(how="any")
    return daily_returns, common_start, first_valid_per_ticker
# endregion


# region Portfolio Construction (Buy-and-Hold vs Annual Rebalancing)
def compute_portfolio_path(weights, returns, annual_rebalance):
    """
    Builds the daily portfolio return series and the daily realized (drifting)
    weights for one archetype.

    annual_rebalance=False -> true buy-and-hold: weights start at target and
        drift freely with cumulative asset performance for the whole window.
    annual_rebalance=True  -> weights reset to target on the first trading
        day of every calendar year, using only the prior day's drifted
        weights (no lookahead), then drift again within the year.

    Returns (portfolio_returns: Series, weights_over_time: DataFrame).
    """
    tickers = list(returns.columns)
    target_weights = np.array([weights[t] for t in tickers])
    returns_arr = returns.values
    dates = returns.index
    years = dates.year.values

    n_days, n_assets = returns_arr.shape
    portfolio_returns = np.empty(n_days)
    weights_over_time = np.empty((n_days, n_assets))

    current_weights = target_weights.copy()
    for i in range(n_days):
        if annual_rebalance and i > 0 and years[i] != years[i - 1]:
            current_weights = target_weights.copy()  # reset using prior day's value, no lookahead

        day_returns = returns_arr[i]
        portfolio_returns[i] = np.dot(current_weights, day_returns)
        weights_over_time[i] = current_weights

        grown = current_weights * (1 + day_returns)
        current_weights = grown / grown.sum()  # drift for the next day

    portfolio_returns_series = pd.Series(portfolio_returns, index=dates)
    weights_over_time_df = pd.DataFrame(weights_over_time, index=dates, columns=tickers)
    return portfolio_returns_series, weights_over_time_df


def compute_aggregate_metrics(portfolio_returns):
    """CAGR, annualized vol, max drawdown, VaR/CVaR(95%), worst year, 2008 return."""
    cumulative_path = (1 + portfolio_returns).cumprod()
    n_trading_days = len(portfolio_returns)
    n_years = n_trading_days / TRADING_DAYS_YEAR

    cagr = cumulative_path.iloc[-1] ** (1 / n_years) - 1
    annualized_vol = portfolio_returns.std() * np.sqrt(TRADING_DAYS_YEAR)

    running_max = cumulative_path.cummax()
    drawdown_path = cumulative_path / running_max - 1
    max_drawdown = drawdown_path.min()

    var_95 = portfolio_returns.quantile(1 - VAR_CONFIDENCE)
    cvar_95 = portfolio_returns[portfolio_returns <= var_95].mean()

    calendar_year_returns = (1 + portfolio_returns).groupby(portfolio_returns.index.year).prod() - 1
    worst_year = calendar_year_returns.idxmin()
    worst_year_return = calendar_year_returns.min()
    year_2008_return = calendar_year_returns.get(2008, None)

    return {
        "cagr": cagr,
        "annualized_vol": annualized_vol,
        "max_drawdown": max_drawdown,
        "var_95": var_95,
        "cvar_95": cvar_95,
        "worst_year": worst_year,
        "worst_year_return": worst_year_return,
        "year_2008_return": year_2008_return,
    }


def compute_archetype_portfolios(archetype, daily_returns):
    """Buy-and-hold and rebalanced portfolio paths for one archetype. Returns (bh_returns, bh_weights, rb_returns)."""
    weights = get_normalized_weights(archetype)
    bh_returns, bh_weights = compute_portfolio_path(weights, daily_returns, annual_rebalance=False)
    rb_returns, _rb_weights = compute_portfolio_path(weights, daily_returns, annual_rebalance=True)
    return bh_returns, bh_weights, rb_returns


def get_archetype_metrics(archetype, daily_returns):
    """
    Single-archetype entry point for callers (e.g. a dashboard) that only need
    one archetype's numbers. Returns a dict:
      {"buy_and_hold": {...aggregate metrics...}, "rebalanced": {...aggregate metrics...}}
    Each sub-dict has keys: cagr, annualized_vol, max_drawdown, var_95, cvar_95,
    worst_year, worst_year_return, year_2008_return.
    """
    bh_returns, _bh_weights, rb_returns = compute_archetype_portfolios(archetype, daily_returns)
    return {
        "buy_and_hold": compute_aggregate_metrics(bh_returns),
        "rebalanced": compute_aggregate_metrics(rb_returns),
    }


def compute_all_portfolios(daily_returns, archetype_order=ARCHETYPE_ORDER):
    """
    Runs compute_archetype_portfolios for every archetype and assembles the
    buy-and-hold comparison table and the buy-and-hold-vs-rebalanced table.
    Returns a dict with the per-archetype return/weight series (for downstream
    rolling-metric and drift-demo functions) plus the two comparison DataFrames.
    """
    bh_returns_by_archetype = {}
    bh_weights_by_archetype = {}
    rb_returns_by_archetype = {}

    bh_comparison_rows = []
    bh_vs_rb_rows = []

    for archetype in archetype_order:
        bh_returns, bh_weights, rb_returns = compute_archetype_portfolios(archetype, daily_returns)
        bh_returns_by_archetype[archetype] = bh_returns
        bh_weights_by_archetype[archetype] = bh_weights
        rb_returns_by_archetype[archetype] = rb_returns

        bh_metrics = compute_aggregate_metrics(bh_returns)
        rb_metrics = compute_aggregate_metrics(rb_returns)

        bh_comparison_rows.append({"archetype": archetype, **bh_metrics})

        for metric in ["cagr", "annualized_vol", "max_drawdown", "cvar_95"]:
            bh_vs_rb_rows.append({
                "archetype": archetype,
                "metric": metric,
                "buy_and_hold": bh_metrics[metric],
                "rebalanced": rb_metrics[metric],
                "diff_rb_minus_bh": rb_metrics[metric] - bh_metrics[metric],
            })

    df_comparison = pd.DataFrame(bh_comparison_rows).set_index("archetype").loc[archetype_order]
    df_bh_vs_rb = pd.DataFrame(bh_vs_rb_rows)

    return {
        "bh_returns_by_archetype": bh_returns_by_archetype,
        "bh_weights_by_archetype": bh_weights_by_archetype,
        "rb_returns_by_archetype": rb_returns_by_archetype,
        "df_comparison": df_comparison,
        "df_bh_vs_rb": df_bh_vs_rb,
    }
# endregion


# region Rolling Metrics (Buy-and-Hold)
def get_rolling_vol_summary(bh_returns_by_archetype, archetype_order=ARCHETYPE_ORDER):
    """Min/max/current rolling 252-day annualized vol per archetype (buy-and-hold). Returns a DataFrame."""
    rows = []
    for archetype in archetype_order:
        returns = bh_returns_by_archetype[archetype]
        rolling_vol = (returns.rolling(ROLLING_WINDOW).std() * np.sqrt(TRADING_DAYS_YEAR)).dropna()
        rows.append({
            "archetype": archetype,
            "rolling_vol_min": rolling_vol.min(),
            "rolling_vol_max": rolling_vol.max(),
            "rolling_vol_current": rolling_vol.iloc[-1],
        })
    return pd.DataFrame(rows).set_index("archetype").loc[archetype_order]


def value_at_or_before(series, date_str):
    """Last value of series at or before date_str, or (None, None) if none exists yet."""
    sub = series.loc[:date_str]
    if sub.empty:
        return None, None
    return sub.index[-1], sub.iloc[-1]


def get_spy_agg_rolling_correlation(daily_returns):
    """Full rolling 252-day SPY-AGG correlation time series. Portfolio-independent. Returns a Series indexed by date."""
    return daily_returns["SPY"].rolling(ROLLING_WINDOW).corr(daily_returns["AGG"]).dropna()


def get_spy_agg_correlation_checkpoints(daily_returns, checkpoint_years=CORRELATION_CHECKPOINT_YEARS):
    """Rolling 252-day SPY-AGG correlation at year-end checkpoints + current. Portfolio-independent. Returns a DataFrame."""
    rolling_spy_agg_corr = get_spy_agg_rolling_correlation(daily_returns)

    rows = []
    for year in checkpoint_years:
        checkpoint_date, value = value_at_or_before(rolling_spy_agg_corr, f"{year}-12-31")
        rows.append({
            "checkpoint": str(year),
            "date_used": checkpoint_date.date() if checkpoint_date is not None else None,
            "spy_agg_1y_corr": value,
        })
    rows.append({
        "checkpoint": "current",
        "date_used": rolling_spy_agg_corr.index[-1].date(),
        "spy_agg_1y_corr": rolling_spy_agg_corr.iloc[-1],
    })
    return pd.DataFrame(rows)
# endregion


# region Drift Demonstration (Buy-and-Hold Equity Weight)
def get_drift_demo(bh_weights_by_archetype, archetype=DRIFT_DEMO_ARCHETYPE, equity_tickers=EQUITY_TICKERS):
    """
    How far the realized equity weight (sum of equity_tickers) drifted from
    target under buy-and-hold (no resets) for one archetype. Returns a dict.
    """
    target_weights = get_normalized_weights(archetype)
    target_equity_weight = sum(target_weights[t] for t in equity_tickers)

    weights_over_time = bh_weights_by_archetype[archetype]
    equity_weight_series = weights_over_time[equity_tickers].sum(axis=1)

    return {
        "archetype": archetype,
        "target_equity_weight": target_equity_weight,
        "final_equity_weight": equity_weight_series.iloc[-1],
        "max_equity_weight": equity_weight_series.max(),
        "max_equity_weight_date": equity_weight_series.idxmax(),
    }
# endregion


# region Demo Run
if __name__ == "__main__":
    daily_returns, common_start, first_valid_per_ticker = load_common_daily_returns()

    portfolios = compute_all_portfolios(daily_returns, ARCHETYPE_ORDER)
    df_comparison = portfolios["df_comparison"]
    df_bh_vs_rb = portfolios["df_bh_vs_rb"]
    bh_returns_by_archetype = portfolios["bh_returns_by_archetype"]
    bh_weights_by_archetype = portfolios["bh_weights_by_archetype"]

    df_rolling_vol_summary = get_rolling_vol_summary(bh_returns_by_archetype, ARCHETYPE_ORDER)
    df_correlation_checkpoints = get_spy_agg_correlation_checkpoints(daily_returns)
    drift_demo = get_drift_demo(bh_weights_by_archetype, DRIFT_DEMO_ARCHETYPE, EQUITY_TICKERS)
    target_equity_weight = drift_demo["target_equity_weight"]
    final_equity_weight = drift_demo["final_equity_weight"]
    max_equity_weight = drift_demo["max_equity_weight"]
    max_equity_weight_date = drift_demo["max_equity_weight_date"]

    # region Output
    print("=== Risk Engine — Buy-and-Hold vs Annual Rebalancing, All Archetypes ===\n")

    print(f"Common backtest window start (latest inception across the 9 tickers): {common_start.date()}")
    print("Per-ticker inception dates:")
    for ticker, first_date in first_valid_per_ticker.items():
        print(f"    {ticker}: {first_date.date()}")
    print(f"Trading days in window: {len(daily_returns)}  (~{len(daily_returns) / TRADING_DAYS_YEAR:.1f} years)")

    print("\n--- Buy-and-Hold Aggregate Metrics (conservative -> growth) ---")
    df_display = df_comparison.copy()
    for col in ["cagr", "annualized_vol", "max_drawdown", "var_95", "cvar_95", "worst_year_return", "year_2008_return"]:
        df_display[col] = df_display[col].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "N/A")
    print(df_display.to_string())

    print("\n--- Buy-and-Hold vs Annual Rebalancing (TEIL B) ---")
    df_bh_rb_display = df_bh_vs_rb.copy()
    for col in ["buy_and_hold", "rebalanced", "diff_rb_minus_bh"]:
        df_bh_rb_display[col] = df_bh_rb_display[col].map(lambda v: f"{v:+.2%}")
    print(df_bh_rb_display.to_string(index=False))

    print(f"\n--- Drift Demonstration: Buy-and-Hold Equity Weight (SPY+EFA+EEM), archetype '{DRIFT_DEMO_ARCHETYPE}' ---")
    print(f"Target equity weight:                {target_equity_weight:.2%}")
    print(f"Actual equity weight at window end:   {final_equity_weight:.2%}")
    print(f"Highest equity weight reached:        {max_equity_weight:.2%}  (on {max_equity_weight_date.date()})")

    print("\n--- Rolling 1-Year Volatility per Archetype (Buy-and-Hold) ---")
    df_rolling_display = df_rolling_vol_summary.copy()
    for col in df_rolling_display.columns:
        df_rolling_display[col] = df_rolling_display[col].map(lambda v: f"{v:.2%}")
    print(df_rolling_display.to_string())

    print("\n--- Rolling 1-Year SPY-AGG Correlation (portfolio-independent, printed once) ---")
    df_corr_display = df_correlation_checkpoints.copy()
    df_corr_display["spy_agg_1y_corr"] = df_corr_display["spy_agg_1y_corr"].map(
        lambda v: f"{v:+.3f}" if pd.notna(v) else "N/A"
    )
    print(df_corr_display.to_string(index=False))
    # endregion

    # region Interpretation
    print("\n=== Interpretation ===")

    print(">>> Buy-and-hold weights drift freely with cumulative performance for the whole window; "
          "annual rebalancing resets to target weights on the first trading day of each year. "
          "Frictionless assumption: no transaction costs or taxes are modeled for rebalancing.")

    vol_diffs = df_comparison["annualized_vol"].diff().dropna()
    if (vol_diffs > 0).all():
        print(">>> Buy-and-hold annualized volatility increases monotonically from conservative to growth, as expected.")
    else:
        print(">>> WARNING: Buy-and-hold annualized volatility is NOT monotonically increasing from conservative to "
              f"growth — check weights/data. Values: {df_comparison['annualized_vol'].to_dict()}")

    dd_diffs = df_comparison["max_drawdown"].diff().dropna()
    if (dd_diffs < 0).all():
        print(">>> Buy-and-hold max drawdown deepens monotonically from conservative to growth, as expected.")
    else:
        print(">>> WARNING: Buy-and-hold max drawdown does NOT deepen monotonically from conservative to growth — "
              f"check weights/data. Values: {df_comparison['max_drawdown'].to_dict()}")

    vol_diff_by_archetype = df_bh_vs_rb[df_bh_vs_rb["metric"] == "annualized_vol"].set_index("archetype")["diff_rb_minus_bh"]
    dd_diff_by_archetype = df_bh_vs_rb[df_bh_vs_rb["metric"] == "max_drawdown"].set_index("archetype")["diff_rb_minus_bh"]
    equity_heavy_archetypes = ["balanced", "growth"]

    vol_lower_for_equity_heavy = (vol_diff_by_archetype.loc[equity_heavy_archetypes] < 0).all()
    dd_shallower_for_equity_heavy = (dd_diff_by_archetype.loc[equity_heavy_archetypes] > 0).all()

    if vol_lower_for_equity_heavy and dd_shallower_for_equity_heavy:
        print(">>> Rebalancing lowers both volatility and max drawdown vs buy-and-hold for the equity-heavy "
              "archetypes (balanced, growth), as expected — uncontrolled equity-weight drift is avoided.")
    else:
        print(">>> WARNING: rebalancing does NOT clearly lower volatility/drawdown vs buy-and-hold for the "
              f"equity-heavy archetypes — flagging explicitly. Vol diff: {vol_diff_by_archetype.to_dict()}, "
              f"Drawdown diff: {dd_diff_by_archetype.to_dict()}")

    cagr_diff_by_archetype = df_bh_vs_rb[df_bh_vs_rb["metric"] == "cagr"].set_index("archetype")["diff_rb_minus_bh"]
    print(f">>> CAGR effect of rebalancing is mixed across archetypes (no consistent direction expected): "
          f"{', '.join(f'{a}: {v:+.2%}' for a, v in cagr_diff_by_archetype.items())}")

    print(f">>> '{DRIFT_DEMO_ARCHETYPE}' equity weight drifted from a {target_equity_weight:.2%} target to "
          f"{final_equity_weight:.2%} by the end of the window under buy-and-hold (peak {max_equity_weight:.2%} "
          f"on {max_equity_weight_date.date()}) — this uncontrolled drift is exactly why annual rebalancing matters.")

    corr_pre_2021 = df_correlation_checkpoints[
        df_correlation_checkpoints["checkpoint"].isin(["2008", "2012", "2016", "2020"])
    ]["spy_agg_1y_corr"]
    corr_post_2021 = df_correlation_checkpoints[
        df_correlation_checkpoints["checkpoint"].isin(["2022", "2024", "current"])
    ]["spy_agg_1y_corr"]
    if corr_pre_2021.dropna().lt(0).any() and corr_post_2021.dropna().gt(0).any():
        print(">>> SPY-AGG rolling 1-year correlation confirms the expected regime shift: negative/mixed in earlier "
              "checkpoints, drifting positive (less diversifying) in the most recent ones — stock/bond "
              "diversification is NOT stationary over this window.")
    else:
        print(">>> SPY-AGG rolling 1-year correlation does NOT clearly show the expected pre-2021-negative / "
              "post-2021-positive pattern — flagging explicitly, see checkpoint table above.")
    # endregion

    # region Legende
    print("\n=== Legende ===")
    print("ARCHETYPE_ORDER          = The 4 archetypes from allocations.list_archetypes(), conservative -> growth")
    print("common_start             = Latest per-ticker inception date — the common backtest window start, determined at runtime")
    print("daily_returns            = Daily pct-change of adj_close, date x symbol, sliced to common_start and inner-joined across all 9 tickers")
    print("buy_and_hold             = Portfolio variant where weights start at target and drift freely, never reset")
    print("rebalanced               = Portfolio variant where weights reset to target on the first trading day of each calendar year")
    print("weights_over_time        = Daily realized (drifting) per-ticker weights for one archetype/variant")
    print("CAGR                     = Compound annual growth rate of the portfolio's cumulative total-return path")
    print("annualized_vol           = std(daily portfolio returns) * sqrt(252)")
    print("max_drawdown             = Largest peak-to-trough decline of the cumulative total-return path")
    print("VaR / CVaR (95%)         = 5th percentile of daily returns, and the mean of returns at/below that threshold")
    print("worst_year / 2008_return = Calendar-year compounded portfolio returns, used as crisis sanity checks")
    print("diff_rb_minus_bh         = Rebalanced metric minus buy-and-hold metric, for the same archetype")
    print("target_equity_weight     = SPY+EFA+EEM target weight for the drift-demo archetype")
    print("equity_weight_series     = SPY+EFA+EEM realized weight over time under buy-and-hold (no resets)")
    print("rolling_vol_min/max/current = Min/max/most-recent value of the rolling 252-day annualized volatility series")
    print("spy_agg_1y_corr          = Rolling 252-day correlation between SPY and AGG daily returns (portfolio-independent)")
    # endregion
# endregion
