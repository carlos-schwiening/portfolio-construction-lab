"""
Portfolio Construction Lab — Dashboard (Stage 2: Supporting Visualizations)
=======================================================================
Run with: streamlit run app.py

Streamlit dashboard on top of core/allocations.py, core/risk_engine.py, and
core/monte_carlo.py: pick an allocation archetype, see its historical
risk/return metrics (annually rebalanced) and a forward-looking Monte Carlo
terminal-wealth projection. The Stage 1 primary view (metrics + histogram)
is unchanged above; Stage 2 adds three supporting visualizations in tabs
below it: the stock-bond correlation regime shift, buy-and-hold vs annual
rebalancing for the selected archetype, and Monte Carlo return-assumption
sensitivity. No new analytics here — everything calls existing functions in
core/risk_engine.py and core/monte_carlo.py.

Visual design (Step 8): all charts use the shared reporting/plot_style.py template
(same light Bloomberg/FT visual language as semiconductor-risk-analysis) and
the surrounding Streamlit UI uses the matching light theme in
.streamlit/config.toml — no dark-UI/light-chart mismatch.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# core/ is pure computation; the Plotly template is presentation and lives in
# reporting/ — the split the project structure is built on.
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))       # allocations, risk_engine, monte_carlo
sys.path.insert(0, os.path.join(PROJECT_ROOT, "reporting"))  # plot_style

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from allocations import list_archetypes
from risk_engine import load_common_daily_returns, get_archetype_metrics, get_spy_agg_rolling_correlation
from monte_carlo import simulate_terminal_wealth, simulate_wealth_paths_percentiles
from plot_style import (
    LAYOUT, BLUE_1, BLUE_2, BLUE_3, GRAY_1, TITLE_FONT, AXIS_FONT, ANNOTATION_FONT, SOURCE_FONT,
    AXIS_DEFAULTS, SOURCE_TEXT, styled_distribution_histogram, hex_to_rgba,
)
# endregion


# ----------------------------------------------------------------------------
# region CACHED DATA / ENGINE CALLS
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading price history from the database...")
def cached_load_data():
    """Common-window daily returns for the 9 active buckets. Cached so the DB is read once per session."""
    daily_returns, common_start, first_valid_per_ticker = load_common_daily_returns()
    return daily_returns, common_start


@st.cache_data(show_spinner="Computing risk metrics...")
def cached_archetype_metrics(archetype):
    """Buy-and-hold + rebalanced aggregate metrics for one archetype."""
    daily_returns, _common_start = cached_load_data()
    return get_archetype_metrics(archetype, daily_returns)


@st.cache_data(show_spinner="Running Monte Carlo simulation...")
def cached_simulation(archetype, start_capital, horizon_years):
    """Block-bootstrap terminal wealth simulation (10,000 paths, default settings)."""
    return simulate_terminal_wealth(archetype, start_capital, horizon_years)


@st.cache_data(show_spinner="Running sensitivity simulation...")
def cached_simulation_with_haircut(archetype, start_capital, horizon_years, haircut):
    """Same as cached_simulation but with an explicit annual_return_haircut, for the sensitivity tab."""
    return simulate_terminal_wealth(archetype, start_capital, horizon_years, annual_return_haircut=haircut)


@st.cache_data(show_spinner="Simulating wealth paths over time...")
def cached_wealth_path_percentiles(archetype, start_capital, horizon_years):
    """Full monthly wealth-path percentiles (P5/P25/Median/P75/P95), for the fan chart. 10,000 paths, default settings."""
    return simulate_wealth_paths_percentiles(archetype, start_capital, horizon_years)


@st.cache_data(show_spinner="Computing rolling stock-bond correlation...")
def cached_rolling_correlation():
    """Full rolling 252-day SPY-AGG correlation time series. Portfolio-independent."""
    daily_returns, _common_start = cached_load_data()
    return get_spy_agg_rolling_correlation(daily_returns)
# endregion


# ----------------------------------------------------------------------------
# region SIDEBAR INPUTS
# ----------------------------------------------------------------------------
st.set_page_config(page_title="Portfolio Construction Lab", layout="wide")

st.sidebar.header("Inputs")
archetype = st.sidebar.selectbox("Allocation archetype", list_archetypes())
start_capital = st.sidebar.number_input("Start capital ($)", min_value=1_000, value=100_000, step=1_000)
horizon_years = st.sidebar.slider("Investment horizon (years)", min_value=1, max_value=30, value=20)
# endregion


# ----------------------------------------------------------------------------
# region HEADER
# ----------------------------------------------------------------------------
st.title("Portfolio Construction Lab")
st.write(
    "Explores multi-asset allocation archetypes on an asset-class/ETF-proxy level: "
    "historical risk/return metrics and a forward-looking Monte Carlo wealth projection."
)
# endregion


# ----------------------------------------------------------------------------
# region SECTION 1 — RISK/RETURN METRICS (ANNUALLY REBALANCED)
# ----------------------------------------------------------------------------
st.header(f"Risk/Return Metrics — {archetype} (annually rebalanced)")

metrics = cached_archetype_metrics(archetype)["rebalanced"]

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("CAGR", f"{metrics['cagr']:+.2%}")
col2.metric("Annualized Vol", f"{metrics['annualized_vol']:.2%}")
col3.metric("Max Drawdown", f"{metrics['max_drawdown']:.2%}")
col4.metric("CVaR (95%)", f"{metrics['cvar_95']:.2%}")
col5.metric("Worst Year", f"{metrics['worst_year_return']:+.2%}", help=f"Year: {metrics['worst_year']}")
year_2008 = metrics["year_2008_return"]
col6.metric("2008 Return", f"{year_2008:+.2%}" if year_2008 is not None else "N/A")
# endregion


# ----------------------------------------------------------------------------
# region SECTION 2 — MONTE CARLO PROJECTION
# ----------------------------------------------------------------------------
st.header("Monte Carlo Wealth Projection")
st.caption(
    "Block-bootstrap simulation from historical monthly returns of the annually "
    "rebalanced portfolio. Nominal (no inflation adjustment), no transaction costs/taxes."
)

terminal_wealth = cached_simulation(archetype, start_capital, horizon_years)
median_wealth = np.percentile(terminal_wealth, 50)
p5_wealth = np.percentile(terminal_wealth, 5)
p95_wealth = np.percentile(terminal_wealth, 95)
shortfall_prob = np.mean(terminal_wealth < start_capital)

mc_col1, mc_col2, mc_col3, mc_col4 = st.columns(4)
mc_col1.metric("Median Terminal Wealth", f"${median_wealth:,.0f}")
mc_col2.metric("5th Percentile", f"${p5_wealth:,.0f}")
mc_col3.metric("95th Percentile", f"${p95_wealth:,.0f}")
mc_col4.metric("Shortfall Probability", f"{shortfall_prob:.2%}", help=f"Share of paths ending below ${start_capital:,.0f}")

# Histogram styling lives in reporting/plot_style.py (styled_distribution_histogram)
# so it's defined once and reused by any future distribution chart, not
# maintained inline here. See that function's docstring for what it encapsulates
# (100 bins by default, BLUE_1 fill, thin bin borders, no reference lines, full
# tail never capped).
fig = styled_distribution_histogram(
    values=terminal_wealth,
    title=f"Simulated Terminal Wealth Distribution — {archetype}, {horizon_years}y",
    x_axis_label="Terminal Wealth ($)",
)

st.plotly_chart(fig, width="stretch")

# Fan chart: percentile corridor of projected wealth over time (not just the
# terminal-wealth snapshot above). Two nested filled bands (P5-P95 outer,
# P25-P75 inner) plus a median line, built from simulate_wealth_paths_percentiles
# — same block-bootstrap methodology/seed as the histogram, full paths kept
# instead of only the terminal value. Full tail not capped, consistent with
# the histogram above.
path_percentiles = cached_wealth_path_percentiles(archetype, start_capital, horizon_years)

fan_fig = go.Figure()

# Outer band (P5-P95): lower bound is an invisible anchor, upper bound fills
# back to it via fill="tonexty".
fan_fig.add_trace(go.Scatter(
    x=path_percentiles["year"], y=path_percentiles["p5"],
    mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
))
fan_fig.add_trace(go.Scatter(
    x=path_percentiles["year"], y=path_percentiles["p95"],
    mode="lines", line=dict(width=0), fill="tonexty", fillcolor=hex_to_rgba(BLUE_3, 0.35),
    name="5-95% range", hoverinfo="skip",
))

# Inner band (P25-P75): same technique, filled against its own lower anchor.
fan_fig.add_trace(go.Scatter(
    x=path_percentiles["year"], y=path_percentiles["p25"],
    mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
))
fan_fig.add_trace(go.Scatter(
    x=path_percentiles["year"], y=path_percentiles["p75"],
    mode="lines", line=dict(width=0), fill="tonexty", fillcolor=hex_to_rgba(BLUE_2, 0.55),
    name="25-75% range", hoverinfo="skip",
))

# Median line on top, as an orientation anchor.
fan_fig.add_trace(go.Scatter(
    x=path_percentiles["year"], y=path_percentiles["p50"],
    mode="lines", line=dict(color=BLUE_1, width=2), name="Median",
))

fan_fig.update_layout(
    **LAYOUT,
    title=dict(
        text=f"Wealth Projection Over Time — {archetype}, {horizon_years}y",
        x=0.0,
        font=TITLE_FONT,
    ),
    xaxis=dict(**AXIS_DEFAULTS, title=dict(text="Years", font=AXIS_FONT), dtick=1, tick0=0),
    yaxis=dict(**AXIS_DEFAULTS, title=dict(text="Projected Wealth ($)", font=AXIS_FONT)),
    margin=dict(l=60, r=60, t=80, b=60),
    height=480,
)
fan_fig.add_annotation(
    text=SOURCE_TEXT, xref="paper", yref="paper",
    x=1.0, y=1.08, showarrow=False, font=SOURCE_FONT,
)

st.plotly_chart(fan_fig, width="stretch")
# endregion


# ----------------------------------------------------------------------------
# region SECTION 3 — SUPPORTING VISUALIZATIONS (SEQUENTIAL)
# ----------------------------------------------------------------------------
st.header("Supporting Visualizations")

# ---- 3.1: Stock-Bond Correlation Regime (portfolio-independent) ----
st.subheader("Stock-Bond Correlation Regime")

rolling_corr = cached_rolling_correlation()

corr_fig = go.Figure()
corr_fig.add_trace(go.Scatter(
    x=rolling_corr.index, y=rolling_corr.values,
    mode="lines", line=dict(color=BLUE_1, width=1.5), name="SPY-AGG 1Y correlation",
))
corr_fig.add_hline(y=0, line_dash="dash", line_color=GRAY_1)

corr_fig.update_layout(
    **LAYOUT,
    title=dict(text="Rolling 1-Year SPY-AGG Correlation", x=0.0, font=TITLE_FONT),
    xaxis=dict(**AXIS_DEFAULTS, title=dict(text="Date", font=AXIS_FONT)),
    yaxis=dict(**AXIS_DEFAULTS, title=dict(text="Correlation", font=AXIS_FONT)),
    margin=dict(l=60, r=60, t=80, b=60),
    showlegend=False,
    height=420,
)
corr_fig.add_annotation(
    text=SOURCE_TEXT, xref="paper", yref="paper",
    x=1.0, y=1.08, showarrow=False, font=SOURCE_FONT,
)

# The sharp March 2020 spike (and its smaller March 2021 echo, ~252 trading days
# later when the same days roll out of the window) is a REAL effect, not a data
# gap or calculation bug — diagnosed in Step 14: SPY and AGG both have complete,
# gap-free histories, and the identical spike appears even computing correlation
# from SPY+AGG's own joint calendar alone. It is the 252-day window reacting to
# the COVID "dash for cash" days, when stocks and bonds briefly sold off together.
# Annotated (not smoothed) so it reads as a real event, not a chart artifact.
corr_fig.add_annotation(
    x="2020-03-13", y=0.27, xref="x", yref="y",
    text="COVID liquidity crisis: stocks and bonds fell together",
    showarrow=True, arrowhead=0, arrowsize=0.6, arrowwidth=1, arrowcolor=GRAY_1,
    ax=90, ay=-40,
    font=dict(ANNOTATION_FONT, color=GRAY_1), align="left",
)

st.plotly_chart(corr_fig, width="stretch")

st.write(
    "Stock-bond correlation was negative over long stretches (bonds diversified equity risk), "
    "but has been consistently positive since roughly 2022 — the diversification this portfolio "
    "construction relies on is **not stable over time**. In March 2020 it briefly failed entirely, "
    "as stocks and bonds sold off together during the COVID liquidity crisis."
)

st.divider()

# ---- 3.2: Buy-and-Hold vs. Annual Rebalancing (selected archetype) ----
st.subheader("Buy-and-Hold vs. Annual Rebalancing")

archetype_metrics = cached_archetype_metrics(archetype)
bh = archetype_metrics["buy_and_hold"]
rb = archetype_metrics["rebalanced"]

rebalancing_rows = []
for label, key in [("CAGR", "cagr"), ("Annualized Vol", "annualized_vol"),
                    ("Max Drawdown", "max_drawdown"), ("CVaR (95%)", "cvar_95")]:
    rebalancing_rows.append({
        "Metric": label,
        "Buy-and-Hold": f"{bh[key]:+.2%}",
        "Rebalanced": f"{rb[key]:+.2%}",
        "Diff (Rebalanced - BH)": f"{rb[key] - bh[key]:+.2%}",
    })
df_rebalancing = pd.DataFrame(rebalancing_rows).set_index("Metric")
st.dataframe(df_rebalancing, width="stretch")

st.write(
    f"For **{archetype}**: rebalancing reliably lowers average volatility, but can deepen the max "
    "drawdown in a prolonged crisis, because it buys back into the falling asset class counter-"
    "cyclically — there is no blanket \"rebalancing reduces risk\" statement that holds for every metric."
)

st.divider()

# ---- 3.3: Return Assumption Sensitivity (selected archetype + current inputs) ----
st.subheader("Return Assumption Sensitivity")

baseline_wealth = cached_simulation(archetype, start_capital, horizon_years)  # haircut = 0.0
haircut_wealth = cached_simulation_with_haircut(archetype, start_capital, horizon_years, 0.02)

sensitivity_rows = [
    {
        "Scenario": "0pp (historical mean)",
        "Median": np.percentile(baseline_wealth, 50),
        "5th Percentile": np.percentile(baseline_wealth, 5),
        "Shortfall Probability": np.mean(baseline_wealth < start_capital),
    },
    {
        "Scenario": "2pp annual haircut",
        "Median": np.percentile(haircut_wealth, 50),
        "5th Percentile": np.percentile(haircut_wealth, 5),
        "Shortfall Probability": np.mean(haircut_wealth < start_capital),
    },
]
df_sensitivity = pd.DataFrame(sensitivity_rows).set_index("Scenario")
df_sensitivity_display = df_sensitivity.copy()
df_sensitivity_display["Median"] = df_sensitivity_display["Median"].map(lambda v: f"${v:,.0f}")
df_sensitivity_display["5th Percentile"] = df_sensitivity_display["5th Percentile"].map(lambda v: f"${v:,.0f}")
df_sensitivity_display["Shortfall Probability"] = df_sensitivity_display["Shortfall Probability"].map(lambda v: f"{v:.2%}")
st.dataframe(df_sensitivity_display, width="stretch")

st.write(
    "A small, plausible 2pp annual return haircut shifts the outcome substantially (e.g. the "
    "shortfall probability multiplies several times over) — Monte Carlo results are highly "
    "sensitive to the return assumption and are **not a prediction**."
)
# endregion
