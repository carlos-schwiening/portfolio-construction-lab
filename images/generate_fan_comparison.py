"""
Wealth Projection Fan Chart Comparison — Conservative vs. Growth (Static Export)
=======================================================================
Run with: python images/generate_fan_comparison.py

Generates a single static PNG with two side-by-side wealth-projection fan
charts (conservative and growth, $100,000 start capital, 20-year horizon),
sharing ONE identical y-axis scale so the difference in uncertainty fan-out
between the two archetypes is honestly comparable. The live dashboard scales
each fan chart's y-axis independently, which would visually understate how
much wider growth's outcome range is relative to conservative's — this script
exists specifically to produce a fair side-by-side image for the README.

Uses the same simulate_wealth_paths_percentiles() function and parameters
(seed=42, n_paths=10000) as the dashboard, so the chart reflects the exact
same methodology, not a separate one-off calculation.
"""

# region Imports & Configuration
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))  # monte_carlo, plot_style

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from monte_carlo import simulate_wealth_paths_percentiles
from plot_style import (
    LAYOUT, BLUE_1, BLUE_2, BLUE_3, TITLE_FONT, AXIS_FONT, SOURCE_FONT,
    AXIS_DEFAULTS, SOURCE_TEXT, hex_to_rgba,
)

START_CAPITAL = 100_000
HORIZON_YEARS = 20
N_PATHS       = 10_000
SEED          = 42

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wealth_projection_comparison.png")
# endregion


# region Simulate
# Same methodology/parameters as the dashboard's fan chart (core/monte_carlo.py
# simulate_wealth_paths_percentiles), just called directly here instead of via
# Streamlit's cache, since this is a one-off static export.
conservative_paths = simulate_wealth_paths_percentiles(
    "conservative", START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS, seed=SEED,
)
growth_paths = simulate_wealth_paths_percentiles(
    "growth", START_CAPITAL, HORIZON_YEARS, n_paths=N_PATHS, seed=SEED,
)

# Shared y-axis range driven by the higher of the two P95 ceilings (growth's),
# so the funnel-size difference between archetypes is shown honestly rather
# than each panel auto-scaling to its own range.
shared_y_max = max(conservative_paths["p95"].max(), growth_paths["p95"].max()) * 1.05
# endregion


# region Build Chart
def add_fan_band(fig, df, col, show_legend):
    """Adds the two nested percentile bands + median line for one archetype to one subplot column."""
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["p5"], mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ), row=1, col=col)
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["p95"], mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor=hex_to_rgba(BLUE_3, 0.35),
        name="5-95% range", showlegend=show_legend, hoverinfo="skip",
    ), row=1, col=col)

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["p25"], mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ), row=1, col=col)
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["p75"], mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor=hex_to_rgba(BLUE_2, 0.55),
        name="25-75% range", showlegend=show_legend, hoverinfo="skip",
    ), row=1, col=col)

    fig.add_trace(go.Scatter(
        x=df["year"], y=df["p50"], mode="lines", line=dict(color=BLUE_1, width=2),
        name="Median", showlegend=show_legend,
    ), row=1, col=col)


fig = make_subplots(
    rows=1, cols=2,
    subplot_titles=(f"Conservative, {HORIZON_YEARS}y", f"Growth, {HORIZON_YEARS}y"),
    shared_yaxes=True,
    horizontal_spacing=0.04,
)

add_fan_band(fig, conservative_paths, col=1, show_legend=True)
add_fan_band(fig, growth_paths, col=2, show_legend=False)

# Subplot titles are plain annotations added by make_subplots; restyle them to
# match the project's TITLE_FONT instead of Plotly's default annotation font.
for annotation in fig.layout.annotations:
    annotation.font = TITLE_FONT

fig.update_layout(
    **LAYOUT,
    # No top-level title here: the subplot titles ("Conservative, 20y" / "Growth, 20y")
    # already give context, and the README adds its own heading above this image.
    margin=dict(l=70, r=60, t=60, b=60),
    height=560,
    width=1400,
)

fig.update_xaxes(**AXIS_DEFAULTS, title=dict(text="Years", font=AXIS_FONT), dtick=1, tick0=0, row=1, col=1)
fig.update_xaxes(**AXIS_DEFAULTS, title=dict(text="Years", font=AXIS_FONT), dtick=1, tick0=0, row=1, col=2)

fig.update_yaxes(**AXIS_DEFAULTS, title=dict(text="Projected Wealth ($)", font=AXIS_FONT),
                  range=[0, shared_y_max], row=1, col=1)
fig.update_yaxes(**AXIS_DEFAULTS, title=None, range=[0, shared_y_max], row=1, col=2)

fig.add_annotation(
    text=SOURCE_TEXT, xref="paper", yref="paper",
    x=1.0, y=-0.12, showarrow=False, font=SOURCE_FONT,
)
# endregion


# region Export
try:
    fig.write_image(OUTPUT_PATH, scale=2)
except Exception as e:
    if "kaleido" in str(e).lower():
        print("ERROR: PNG export requires the 'kaleido' package, which is not installed.")
        print("Run: pip install kaleido")
        sys.exit(1)
    raise
# endregion


# region Interpretation
print("=== Wealth Projection Fan Chart Comparison ===")
print(f">>> Shared y-axis upper bound: ${shared_y_max:,.0f} (growth's P95 ceiling x 1.05 headroom).")
print(f">>> Conservative P5-P95 at year {HORIZON_YEARS}: "
      f"${conservative_paths['p5'].iloc[-1]:,.0f} - ${conservative_paths['p95'].iloc[-1]:,.0f} "
      f"(spread ${conservative_paths['p95'].iloc[-1] - conservative_paths['p5'].iloc[-1]:,.0f})")
print(f">>> Growth P5-P95 at year {HORIZON_YEARS}: "
      f"${growth_paths['p5'].iloc[-1]:,.0f} - ${growth_paths['p95'].iloc[-1]:,.0f} "
      f"(spread ${growth_paths['p95'].iloc[-1] - growth_paths['p5'].iloc[-1]:,.0f})")
print(f">>> PNG saved: {OUTPUT_PATH}")
# endregion


# region Legende
print("\n=== Legende ===")
print("START_CAPITAL  = Starting capital fed into both simulations ($100,000)")
print("HORIZON_YEARS  = Projection horizon in years (20)")
print("N_PATHS / SEED = Same Monte Carlo settings as the dashboard (10,000 paths, fixed seed 42)")
print("shared_y_max   = Common y-axis upper bound for both subplots, driven by growth's P95 ceiling")
print("p5/p25/p50/p75/p95 = Percentiles of simulated wealth across all paths at each month")
# endregion
