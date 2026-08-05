"""
portfolio-construction-lab — DB Pull v1 (Asset-Class Level)
=======================================================================
Run with: python data/db_pull_v1.py

Pulls dividend-adjusted (total return) daily closes for one ETF proxy per
asset-class bucket and stores the full available history of each ticker into
a local SQLite database. The common backtest-window start (latest inception
across all tickers) is reported at the end but NOT applied here — windowing
happens later in the analysis layer, so the DB stays reusable.
"""

# region Imports & Configuration
import sys
import os
import sqlite3
import time

sys.stdout.reconfigure(encoding="utf-8")

# fmp_client.py sits next to this file, so a fresh clone works without any
# path outside the repository.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmp_client import get_dividend_adjusted_price_full

import pandas as pd

DB_PATH    = os.path.join(os.path.dirname(__file__), "portfolio_data.db")
YEARS_BACK = 30
SLEEP_SEC  = 0.3
# endregion


# region Parameters — v1 Ticker Set (one proxy per bucket)
TICKER_MAP = [
    {"ticker": "SPY", "bucket": "US Stocks (broad)"},
    {"ticker": "EFA", "bucket": "Non-US Developed Stocks"},
    {"ticker": "EEM", "bucket": "Emerging Market Stocks"},
    {"ticker": "AGG", "bucket": "Core Bonds (US Aggregate)"},
    {"ticker": "TLT", "bucket": "Long Treasury (equity diversifier)"},
    {"ticker": "HYG", "bucket": "High Yield"},
    {"ticker": "EMB", "bucket": "EM Bond"},
    {"ticker": "TIP", "bucket": "Inflation (TIPS)"},
    {"ticker": "BIL", "bucket": "Cash (T-Bills)"},
    {"ticker": "QAI", "bucket": "Alternatives (rough HFRI proxy, approximation)"},
]
# endregion


# region Database Setup
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS prices (
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        adj_close REAL NOT NULL,
        PRIMARY KEY (symbol, date)
    )
""")
conn.commit()
# endregion


# region Pull + Store
# ─────────────────────────────────────────────────────────────
# Fetches dividend-adjusted close prices via get_dividend_adjusted_price_full
# (chunked, no 5000-row cap) and writes the COMPLETE available history per
# ticker — no common-window trimming at this stage.
# ─────────────────────────────────────────────────────────────
summary = []

for i, row in enumerate(TICKER_MAP):
    ticker = row["ticker"]
    print(f"Pulling {ticker} ({row['bucket']})...")

    df_price = get_dividend_adjusted_price_full(ticker, years=YEARS_BACK)

    if df_price.empty:
        print(f">>> WARNING: no data returned for {ticker} — skipped.")
        summary.append({"ticker": ticker, "bucket": row["bucket"], "earliest_date": None,
                         "latest_date": None, "row_count": 0})
        continue

    if "adjClose" not in df_price.columns:
        print(f">>> WARNING: adjClose missing for {ticker} — skipped, NOT falling back to close.")
        summary.append({"ticker": ticker, "bucket": row["bucket"], "earliest_date": None,
                         "latest_date": None, "row_count": 0})
        continue

    df_price["date"] = df_price["date"].dt.strftime("%Y-%m-%d")

    records = [
        (ticker, d, adj_close)
        for d, adj_close in zip(df_price["date"], df_price["adjClose"])
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO prices (symbol, date, adj_close) VALUES (?, ?, ?)",
        records,
    )
    conn.commit()

    summary.append({
        "ticker": ticker,
        "bucket": row["bucket"],
        "earliest_date": df_price["date"].min(),
        "latest_date": df_price["date"].max(),
        "row_count": len(df_price),
    })

    if i < len(TICKER_MAP) - 1:
        time.sleep(SLEEP_SEC)

conn.close()
# endregion


# region Output
df_summary = pd.DataFrame(summary)
print("\n=== DB Pull Summary (per symbol) ===\n")
print(df_summary.to_string(index=False))

valid_starts = pd.to_datetime(df_summary["earliest_date"].dropna())
common_start = valid_starts.max() if not valid_starts.empty else None

print(f"\nDatabase saved: {DB_PATH}")
# endregion


# region Interpretation
print("\n=== Interpretation ===")

failed = df_summary[df_summary["row_count"] == 0]
if not failed.empty:
    print(f">>> {len(failed)} ticker(s) could not be pulled: {', '.join(failed['ticker'].tolist())}. "
          f"Backtest universe is incomplete until this is resolved.")
else:
    print(">>> All 10 tickers pulled successfully — full v1 asset-class universe is in the DB.")

if common_start is not None:
    latest_inception = df_summary.loc[pd.to_datetime(df_summary["earliest_date"]).idxmax()]
    print(f">>> Common backtest-window start (latest inception across all tickers): {common_start.date()} "
          f"— driven by {latest_inception['ticker']} ({latest_inception['bucket']}).")
    print(">>> This window is NOT applied to the stored data — each ticker keeps its full history in the DB; "
          "apply the common start at analysis time.")
# endregion


# region Legende
print("\n=== Legende ===")
print("symbol        = ETF proxy ticker (one per asset-class bucket, v1 set)")
print("bucket        = Asset-class bucket this ticker represents")
print("date           = ISO trading date (YYYY-MM-DD)")
print("adj_close      = Dividend-adjusted (total return) close price, from /historical-price-eod/dividend-adjusted")
print("earliest_date  = First stored date for this ticker (its full available history, not windowed)")
print("latest_date    = Most recent stored date for this ticker")
print("row_count      = Number of daily price rows stored for this ticker")
print("common_start   = Latest earliest_date across all tickers — the confirmed common backtest-window start")
# endregion
