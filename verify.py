"""
verify — Recompute the published figures and report where they no longer hold.
Run with: python verify.py [--full]

A number in a README has no link to the code that made it. This one named the
mypy scope as `core/` after `reporting/` had been added to it.

A mismatch is a FINDING: either the document drifted or the code did. Establish
which before correcting either.

  cheap      Structural facts and properties of the allocations. No database.
  --full     Recomputes from data/portfolio_data.db: the backtest window, the
             trading-day count, and the Monte Carlo figures the README quotes.
             The database is gitignored, so these skip on a fresh clone.
  by hand    The book's own figures are not reproduced here at all (see
             SOURCES.md), so there is nothing to check against it.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import io
import os
import re
import subprocess
import sys
from typing import Any, Callable, NamedTuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "core"),
           os.path.join(PROJECT_ROOT, "reporting")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

README = "README.md"
CI_WORKFLOW = os.path.join(".github", "workflows", "ci.yml")
DB = os.path.join(PROJECT_ROOT, "data", "portfolio_data.db")

# QAI is in the database but out of the active universe: it started 2009-03-25,
# days from the market bottom, and would drag the common window onto it.
EXCLUDED_PROXY = "QAI"
# endregion


# ----------------------------------------------------------------------------
# region CLAIM DEFINITION
# ----------------------------------------------------------------------------
class Claim(NamedTuple):
    source: str
    claim: str
    document: str
    expected: Any
    compute: Callable[[], Any]
    expensive: bool = False   # needs the gitignored database


class Result(NamedTuple):
    claim: Claim
    actual: Any
    ok: bool
    skipped: bool
# endregion


# ----------------------------------------------------------------------------
# region READING THE DOCUMENTS
# ----------------------------------------------------------------------------
def _read(relative_path: str) -> str:
    with open(os.path.join(PROJECT_ROOT, relative_path), encoding="utf-8") as fh:
        return fh.read()


def _claimed_test_count() -> int:
    match = re.search(r"\*\*(\d+) tests\*\*", _read(README))
    return int(match.group(1)) if match else -1


def _actual_test_count() -> int:
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "--co"],
                         cwd=PROJECT_ROOT, capture_output=True, text=True)
    match = re.search(r"(\d+) tests? collected", out.stdout)
    return int(match.group(1)) if match else -1


def _claimed_mypy_scope() -> set[str]:
    section = _read(README).split("## Tests & Continuous Integration")[-1]
    return set(re.findall(r"`(core/|reporting/|tests/)`", section))


def _ci_mypy_scope() -> set[str]:
    match = re.search(r"run: mypy ([^\n]+)", _read(CI_WORKFLOW))
    return {p for p in match.group(1).split() if p.endswith("/")} if match else set()


def _claimed_window_start() -> str:
    match = re.search(r"currently starts (\d{4}-\d{2}-\d{2})", _read(README))
    return match.group(1) if match else "?"


def _claimed_trading_days() -> int:
    match = re.search(r"([\d,]+) trading days", _read(README))
    return int(match.group(1).replace(",", "")) if match else -1


def _claimed_archetypes() -> list[str]:
    """The archetype names the Key Results table lists."""
    names = []
    inside = False
    for line in _read(README).splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Key Results"
            continue
        if inside and line.startswith("| ") and not line.startswith("| Archetype"):
            cell = line.strip("| ").split("|")[0].strip()
            if cell and not set(cell) <= set("-: "):
                names.append(cell)
    return sorted(names)
# endregion


# ----------------------------------------------------------------------------
# region RECOMPUTING FROM THE CODE
# ----------------------------------------------------------------------------
def _archetypes_in_code() -> list[str]:
    from allocations import list_archetypes   # type: ignore[import-not-found]
    return sorted(list_archetypes())


def _weights_normalise() -> bool:
    """Every archetype's weights must sum to exactly 1.0 within tolerance."""
    from allocations import get_normalized_weights, list_archetypes
    return all(abs(sum(get_normalized_weights(a).values()) - 1.0) < 1e-9
               for a in list_archetypes())


def _qai_is_excluded() -> bool:
    """QAI must not appear in any archetype - see the comment on EXCLUDED_PROXY."""
    from allocations import RAW_WEIGHTS
    return all(EXCLUDED_PROXY not in weights for weights in RAW_WEIGHTS.values())


def _block_months_default() -> int:
    import inspect

    from monte_carlo import simulate_terminal_wealth   # type: ignore[import-not-found]
    return int(inspect.signature(simulate_terminal_wealth).parameters["block_months"].default)


def _haircut_default() -> float:
    import inspect

    from monte_carlo import simulate_terminal_wealth
    param = inspect.signature(simulate_terminal_wealth).parameters["annual_return_haircut"]
    return float(param.default)
# endregion


# ----------------------------------------------------------------------------
# region EXPENSIVE - RECOMPUTING FROM THE DATABASE
# ----------------------------------------------------------------------------
def _binding_proxy() -> tuple[str, str]:
    """
    The proxy whose inception sets the common window, and that date. Derived, so
    adding or dropping a proxy moves it — which is the README's claim.
    """
    import sqlite3
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            "SELECT symbol, MIN(date) FROM prices GROUP BY symbol").fetchall()
    return max(((s, d) for s, d in rows if s != EXCLUDED_PROXY), key=lambda r: r[1])


def _db_window_start() -> str:
    return _binding_proxy()[1]


def _db_trading_days() -> int:
    """Daily returns over the common window: one fewer than the price count."""
    import sqlite3
    symbol, start = _binding_proxy()
    with sqlite3.connect(DB) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE symbol = ? AND date >= ?",
            (symbol, start)).fetchone()[0]
    return int(count) - 1
# endregion


# ----------------------------------------------------------------------------
# region THE CLAIMS
# ----------------------------------------------------------------------------
def build_claims() -> list[Claim]:
    return [
        Claim("Repository itself",
              "the README's test count matches what pytest collects",
              README, _actual_test_count(), _claimed_test_count),
        Claim("Repository itself",
              "the packages the README says are type-checked are the ones CI checks",
              README, _ci_mypy_scope(), _claimed_mypy_scope),
        Claim("2. The backtest window",
              "the four archetypes in the table are the four in the code",
              README, _archetypes_in_code(), _claimed_archetypes),
        Claim("2. The backtest window",
              "every archetype's weights sum to exactly 1.0",
              "core/allocations.py", True, _weights_normalise),
        Claim("2. The backtest window",
              "QAI is excluded from every archetype",
              "SOURCES.md", True, _qai_is_excluded),
        Claim("5. The simulation",
              "the bootstrap draws six-month blocks",
              README, 6, _block_months_default),
        Claim("5. The simulation",
              "the return haircut is zero unless asked for",
              "SOURCES.md", 0.0, _haircut_default),
        Claim("1. FMP prices",
              "the window start is the latest inception among the proxies in use",
              README, _claimed_window_start(), _db_window_start, True),
        Claim("1. FMP prices",
              "the trading-day count matches the data",
              README, _claimed_trading_days(), _db_trading_days, True),
    ]


BY_HAND = [
    ("4. Beyond Diversification",
     "the book's own figures",
     "nothing to check - they are proprietary and deliberately not reproduced here"),
    ("1. FMP prices",
     "that the stored prices are the real ones",
     "spot-check a date against a public total-return chart for the same ETF"),
]
# endregion


# ----------------------------------------------------------------------------
# region RUN
# ----------------------------------------------------------------------------
def run(full: bool = False) -> int:
    results: list[Result] = []
    for claim in build_claims():
        if claim.expensive and (not full or not os.path.exists(DB)):
            results.append(Result(claim, None, True, True))
            continue
        try:
            actual = claim.compute()
            ok = actual == claim.expected
        except Exception as exc:
            actual, ok = f"ERROR: {type(exc).__name__}: {exc}", False
        results.append(Result(claim, actual, ok, False))

    width = max(len(r.claim.claim) for r in results)
    print(f"\n{'':6} {'Claim':<{width}}  {'expected':>14}  {'actual':>14}")
    print("-" * (width + 40))
    for r in results:
        if r.skipped:
            print(f"{'[skip]':6} {r.claim.claim:<{width}}  {'needs the db':>14}")
            continue
        mark = "[OK  ]" if r.ok else "[FAIL]"
        print(f"{mark:6} {r.claim.claim:<{width}}  "
              f"{str(r.claim.expected):>14}  {str(r.actual):>14}")

    failures = [r for r in results if not r.ok and not r.skipped]
    skipped = [r for r in results if r.skipped]
    print("-" * (width + 40))
    print(f"{len(results) - len(failures) - len(skipped)} ok, "
          f"{len(failures)} failed, {len(skipped)} skipped")

    if failures:
        print("\nDocuments to correct - establish WHY the figure moved first.\n")
        for r in failures:
            print(f"  {r.claim.document}: {r.claim.claim}")
            print(f"    published {r.claim.expected!r}, recomputed {r.actual!r}")

    print("\nNot checkable by code:")
    for source, figure, how in BY_HAND:
        print(f"  {source:<26} {figure}")
        print(f"  {'':26} -> {how}")

    if skipped:
        print("\nThe database is gitignored. Run with --full after data/db_pull_v1.py")
        print("to check the window and the trading-day count against it.")

    return 1 if failures else 0
# endregion


if __name__ == "__main__":
    sys.exit(run(full="--full" in sys.argv))
