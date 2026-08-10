"""
Allocation Archetypes — Bucket-Level Weights
=======================================================================
Run with: python core/allocations.py (self-test only; this module is meant
to be imported by risk_engine.py and later allocation/backtest scripts)

Defines representative multi-asset allocations from conservative to growth-
oriented, on asset-class/bucket level, using one ETF proxy per bucket. Real
Assets and Alternatives (QAI) are left out (no clean proxy / inception too
late for the common backtest window — see project status) and weights are
renormalized accordingly.

NOTE: only 4 archetypes (conservative, moderate, balanced, growth) are
defined below — RAW_WEIGHTS was specified with exactly these 4 keys, not 5.
list_archetypes() reflects the actual data, not a hardcoded count.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import sys
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

TOLERANCE = 1e-9
# endregion


# ----------------------------------------------------------------------------
# region PARAMETERS — PROXY LABELS + RAW WEIGHTS
# ----------------------------------------------------------------------------
PROXY_LABELS: dict[str, str] = {
    "SPY": "US Stocks", "EFA": "Non-US Developed", "EEM": "EM Stocks",
    "AGG": "Core Bonds", "TLT": "Long Treasury", "HYG": "High Yield",
    "EMB": "EM Bond", "TIP": "TIPS", "BIL": "Cash",
}

# Raw weights in percentage points, before renormalization (do not sum to 100
# for every archetype since Real Assets/Alternatives were stripped out).
RAW_WEIGHTS: dict[str, dict[str, float]] = {
    "conservative": {"SPY": 12.5, "EFA": 0,  "EEM": 0, "AGG": 53, "TLT": 4, "HYG": 18.5, "EMB": 10, "TIP": 2, "BIL": 0},
    "moderate":     {"SPY": 27,   "EFA": 10, "EEM": 2, "AGG": 28, "TLT": 2, "HYG": 4,    "EMB": 5,  "TIP": 0, "BIL": 7},
    "balanced":     {"SPY": 32,   "EFA": 25, "EEM": 4, "AGG": 16, "TLT": 1, "HYG": 2,    "EMB": 4,  "TIP": 3, "BIL": 0},
    "growth":       {"SPY": 53,   "EFA": 19, "EEM": 3, "AGG": 11, "TLT": 1, "HYG": 1,    "EMB": 1,  "TIP": 0, "BIL": 0},
}
# endregion


# ----------------------------------------------------------------------------
# region FUNCTIONS
# ----------------------------------------------------------------------------
def get_normalized_weights(archetype: str) -> dict[str, float]:
    """Returns bucket weights for one archetype, scaled so they sum exactly to 1.0."""
    if archetype not in RAW_WEIGHTS:
        raise KeyError(f"Unknown archetype '{archetype}'. Available: {list(RAW_WEIGHTS.keys())}")

    raw = RAW_WEIGHTS[archetype]
    total = sum(raw.values())
    normalized = {ticker: weight / total for ticker, weight in raw.items()}

    weight_sum = sum(normalized.values())
    assert abs(weight_sum - 1.0) < TOLERANCE, (
        f"Normalized weights for '{archetype}' sum to {weight_sum}, expected 1.0"
    )
    return normalized


def list_archetypes() -> list[str]:
    """Returns the archetype keys actually defined in RAW_WEIGHTS."""
    return list(RAW_WEIGHTS.keys())
# endregion


# ----------------------------------------------------------------------------
# region SELF-TEST
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== allocations.py — Self-Test ===\n")
    for archetype in list_archetypes():
        weights = get_normalized_weights(archetype)
        print(f"{archetype}:")
        for ticker, weight in weights.items():
            print(f"    {ticker} ({PROXY_LABELS[ticker]}): {weight:.4f}")
        print(f"    SUM = {sum(weights.values()):.10f}\n")
# endregion
