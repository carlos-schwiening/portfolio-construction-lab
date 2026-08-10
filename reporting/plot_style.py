"""
plot_style — Central Plotly design template for portfolio-construction-lab.
===========================================================================
Import with:
  from plot_style import (
      LAYOUT, BLUE_1, BLUE_2, BLUE_3, ORANGE_1, GRAY_1, BG, TEXT,
      TITLE_FONT, AXIS_FONT, ANNOTATION_FONT, TICK_FONT, SOURCE_FONT,
      AXIS_DEFAULTS, SOURCE_TEXT, styled_distribution_histogram,
  )

Subset of Projects\\Public\\semiconductor-risk-analysis\\plot_style.py, kept to
the same light Bloomberg/FT visual language (white background, Inter font,
muted blue) but trimmed to what this project actually uses — no ticker/stage
colors or DD thresholds, which are semiconductor-risk-analysis-specific.

Also provides styled_distribution_histogram(), the reusable chart builder for
Monte Carlo / distribution histograms (see below) — style changes for this
chart type belong HERE, not inline in app.py.
"""

import numpy as np
import plotly.graph_objects as go

# ── Color Palette ────────────────────────────────────────────────
BLUE_1   = "#1D6FD8"   # Primary blue   (main lines, bars, active elements)
BLUE_2   = "#5B9BD5"   # Secondary blue (comparison lines, positive scenarios)
BLUE_3   = "#A8C8E8"   # Tertiary blue  (background band, fill areas)

ORANGE_1 = "#D4A843"   # Warm orange (median, benchmark, reference value)

GRAY_1   = "#6B7280"   # Primary gray  (reference lines, secondary labels)

BG   = "#FFFFFF"
TEXT = "#1A1A1A"

# ── Central Layout Template ─────────────────────────────────
LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor=BG,
    plot_bgcolor=BG,
    font=dict(family="Inter, Arial, sans-serif", size=12, color=TEXT),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
)

# ── Typography ─────────────────────────────────────────────────
TITLE_FONT      = dict(family="Inter, Arial, sans-serif", size=16, color="#0B1220")
AXIS_FONT       = dict(family="Inter, Arial, sans-serif", size=11, color="#6B7280")
ANNOTATION_FONT = dict(family="Inter, Arial, sans-serif", size=10, color="#1A1A1A")
SOURCE_FONT     = dict(family="Inter, Arial, sans-serif", size=9,  color="#9CA3AF")
TICK_FONT       = dict(family="Inter, Arial, sans-serif", size=10, color="#6B7280")

# ── Axis Defaults ────────────────────────────────────────────
AXIS_DEFAULTS = dict(
    showgrid=False,
    zeroline=False,
    showline=True,
    linecolor="#E5E5E5",
    tickfont=TICK_FONT,
)

# ── Source Attribution ──────────────────────────────────────────
SOURCE_TEXT = "Source: FMP API (dividend-adjusted prices)"


def hex_to_rgba(hex_color, alpha):
    """Converts a 6-digit hex color to an rgba() string at the given opacity (no 8-digit hex, per project convention)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# ----------------------------------------------------------------------------
# region REUSABLE CHART BUILDERS
# ----------------------------------------------------------------------------
def styled_distribution_histogram(values, title, x_axis_label, y_axis_label="Number of Simulated Paths",
                                   source_text=SOURCE_TEXT, n_bins=100):
    """
    Fully styled Plotly histogram for a distribution of simulated/sampled values
    (Monte Carlo terminal wealth today; any future distribution chart can reuse
    this too — values/title/labels are parameters, nothing here is MC-specific).

    Encapsulates the settings established in app.py's Monte Carlo histogram:
    BLUE_1 fill, a thin light bin border so bars stay visually distinct, the
    shared LAYOUT/AXIS_DEFAULTS/TITLE_FONT/AXIS_FONT/SOURCE_FONT, and explicit
    bin edges (np.histogram_bin_edges, passed via xbins) so the requested
    n_bins is exact rather than just a Plotly auto-binning hint.

    No reference lines or in-plot annotations — deliberately a clean,
    unannotated distribution (any P5/median/P95 values belong in the caller's
    UI, e.g. st.metric, not drawn on the chart). The x-axis is never range-
    capped: the full tail of the distribution is always shown, by design.
    """
    bin_edges = np.histogram_bin_edges(values, bins=n_bins)
    bin_size = bin_edges[1] - bin_edges[0]

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=values,
        xbins=dict(start=bin_edges[0], end=bin_edges[-1], size=bin_size),
        autobinx=False,
        marker_color=BLUE_1,
        marker_line_width=0.5,
        marker_line_color="#F0F0F0",  # thin light border per-bin so bars stay visually distinct, not one blue mass
        opacity=0.85,
        name=y_axis_label,
    ))

    fig.update_layout(
        **LAYOUT,
        title=dict(text=title, x=0.0, font=TITLE_FONT),
        # No x-axis range override: the full right tail stays visible by design —
        # it is an honest feature of the distribution, not something to hide.
        xaxis=dict(**AXIS_DEFAULTS, title=dict(text=x_axis_label, font=AXIS_FONT)),
        yaxis=dict(**AXIS_DEFAULTS, title=dict(text=y_axis_label, font=AXIS_FONT)),
        margin=dict(l=60, r=60, t=80, b=60),
        showlegend=False,
        height=520,
    )
    fig.add_annotation(
        text=source_text, xref="paper", yref="paper",
        x=1.0, y=1.08, showarrow=False, font=SOURCE_FONT,
    )
    return fig
# endregion
