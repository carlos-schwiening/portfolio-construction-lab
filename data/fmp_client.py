"""
fmp_client — Minimal, self-contained FMP API client for this project.

Only the two price endpoints the data pull needs are implemented. The module is
deliberately standalone: it has no dependency on any directory outside this
repository, so `python data/db_pull_v1.py` runs from a fresh clone on any OS.

API key resolution, in order:
  1. FMP_API_KEY environment variable
  2. a .env file in the working directory or above (needs python-dotenv)
  3. a workspace-internal Config/Api_keys.py (only present in the original
     development workspace; absent for anyone cloning this repository)

Raises a clear error if none of the three yields a key, instead of failing later
with an opaque HTTP 401.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import os
import time
from datetime import date, timedelta

import pandas as pd
import requests

BASE_URL  = "https://financialmodelingprep.com/stable/"
SLEEP_SEC = 0.3   # pause between calls when looping over several symbols


def _resolve_api_key() -> str:
    """Find the FMP API key; see module docstring for the order of sources."""
    key = os.environ.get("FMP_API_KEY")
    if key:
        return key

    try:  # optional: python-dotenv is not a hard dependency
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
        key = os.environ.get("FMP_API_KEY")
        if key:
            return key
    except ImportError:
        pass

    try:  # only present inside the original development workspace
        from Api_keys import FMP_API_KEY  # type: ignore[import-not-found]

        return str(FMP_API_KEY)
    except ImportError:
        pass

    raise RuntimeError(
        "No FMP API key found. Set the FMP_API_KEY environment variable, or put "
        "FMP_API_KEY=<your key> into a .env file. A free key is available at "
        "https://site.financialmodelingprep.com/developer/docs"
    )
# endregion


# ----------------------------------------------------------------------------
# region HTTP HELPER
# ----------------------------------------------------------------------------
def _fetch(endpoint: str, params: dict, context: str) -> list:
    """GET against the FMP API. Returns a list of dicts, or [] on error/empty."""
    params = dict(params)
    params["apikey"] = _resolve_api_key()

    try:
        response = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=30)
    except requests.exceptions.RequestException as exc:
        print(f"Request failed for {context}: {exc}")
        return []

    if response.status_code != 200:
        print(f"Request failed for {context}: HTTP {response.status_code}")
        return []

    try:
        data = response.json()
    except ValueError:
        print(f"Request failed for {context}: response is not valid JSON")
        return []

    if not isinstance(data, list) or len(data) == 0:
        print(f"Note: empty response for {context}")
        return []

    time.sleep(SLEEP_SEC)
    return data
# endregion


# ----------------------------------------------------------------------------
# region PRICE HISTORY
# ----------------------------------------------------------------------------
def _fetch_chunked_history(endpoint: str, symbol: str, years: int, chunk_years: int) -> pd.DataFrame:
    """
    The FMP historical-price endpoints cap a single response at 5000 rows
    (~19.8 trading years) and silently drop earlier history instead of raising.
    This queries non-overlapping date sub-windows well under that cap and
    concatenates them.
    """
    to_date_overall   = date.today()
    from_date_overall = to_date_overall - timedelta(days=int(years * 365.25))

    chunks = []
    chunk_end = to_date_overall
    while chunk_end > from_date_overall:
        chunk_start = max(from_date_overall, chunk_end - timedelta(days=int(chunk_years * 365.25)))
        data = _fetch(
            endpoint,
            {"symbol": symbol, "from": chunk_start.isoformat(), "to": chunk_end.isoformat()},
            f"{symbol} ({endpoint}, chunk {chunk_start}..{chunk_end})",
        )
        if data:
            chunks.append(pd.DataFrame(data))
        chunk_end = chunk_start - timedelta(days=1)

    if not chunks:
        return pd.DataFrame()

    df = pd.concat(chunks, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)


def get_historical_price_full(symbol: str, years: int = 30, chunk_years: int = 15) -> pd.DataFrame:
    """
    Price-only daily history. Columns: date, open, high, low, close, volume.
    Contains NO adjClose — use get_dividend_adjusted_price_full when total
    return matters.
    """
    return _fetch_chunked_history("historical-price-eod/full", symbol, years, chunk_years)


def get_dividend_adjusted_price_full(symbol: str, years: int = 30, chunk_years: int = 15) -> pd.DataFrame:
    """
    Dividend-adjusted (total return) daily history via the separate
    /historical-price-eod/dividend-adjusted endpoint. Required for bond ETFs,
    where most of the return comes from distributions rather than price moves.
    Columns: date, adjOpen, adjHigh, adjLow, adjClose, volume.
    """
    return _fetch_chunked_history("historical-price-eod/dividend-adjusted", symbol, years, chunk_years)
# endregion
