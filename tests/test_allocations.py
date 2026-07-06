"""
test_allocations — Unit tests for core/allocations.py.
Run with: python -m pytest tests/test_allocations.py
"""

import os
import sys

CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import pytest
from allocations import get_normalized_weights, list_archetypes, RAW_WEIGHTS


def test_list_archetypes_matches_raw_weights_keys():
    assert list_archetypes() == list(RAW_WEIGHTS.keys())
    assert len(list_archetypes()) == 4


@pytest.mark.parametrize("archetype", ["conservative", "moderate", "balanced", "growth"])
def test_normalized_weights_sum_to_one(archetype):
    weights = get_normalized_weights(archetype)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_normalized_weights_preserve_relative_proportions():
    """Doubling a raw weight relative to another must double the ratio after normalization too."""
    weights = get_normalized_weights("conservative")
    raw = RAW_WEIGHTS["conservative"]
    # AGG (53) is roughly 2.9x SPY (12.5) in raw terms — must still hold after normalization.
    assert weights["AGG"] / weights["SPY"] == pytest.approx(raw["AGG"] / raw["SPY"])


def test_unknown_archetype_raises_key_error():
    with pytest.raises(KeyError):
        get_normalized_weights("aggressive_growth_not_a_real_archetype")
