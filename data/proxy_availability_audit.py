"""
portfolio-construction-lab — Proxy Availability Audit
=======================================================================
Run with: python data/proxy_availability_audit.py

Checks data availability on FMP for every ETF proxy that stands in for a
book-index position. No portfolio math here — this is a data audit only,
run before any full historical download into a database.
"""

# ----------------------------------------------------------------------------
# region IMPORTS & CONFIGURATION
# ----------------------------------------------------------------------------
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# fmp_client.py sits next to this file, so a fresh clone works without any
# path outside the repository.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmp_client import get_historical_price_full

import pandas as pd

OUTPUT_DIR  = os.path.dirname(__file__)
OUTPUT_CSV  = os.path.join(OUTPUT_DIR, "proxy_availability_audit.csv")
YEARS_BACK  = 30
CUTOFF_DATE = pd.Timestamp("2003-01-01")
# endregion


# ----------------------------------------------------------------------------
# region PARAMETERS — BOOK INDEX -> ETF PROXY MAPPING
# ----------------------------------------------------------------------------
# proxy_type "primary"   = clean single ETF proxy for this book-index position
# proxy_type "candidate" = no clean single proxy exists; ticker is one of several
#                          approximation candidates evaluated for later design decision
PROXY_MAP = [
    # US Equity
    {"category": "US Equity",    "book_index": "S&P500",          "ticker": "SPY", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "R1000Growth",     "ticker": "IWF", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "R1000Value",      "ticker": "IWD", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "MidGrowth",       "ticker": "IWP", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "MidValue",        "ticker": "IWS", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "R2000",           "ticker": "IWM", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "R2000Growth",     "ticker": "IWO", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "R2000Value",      "ticker": "IWN", "proxy_type": "primary"},
    {"category": "US Equity",    "book_index": "BXM/VolPremium",  "ticker": "PBP", "proxy_type": "primary"},

    # Non-US Equity
    {"category": "Non-US Equity", "book_index": "EAFE",          "ticker": "EFA", "proxy_type": "primary"},
    {"category": "Non-US Equity", "book_index": "EAFEGrowth",    "ticker": "EFG", "proxy_type": "primary"},
    {"category": "Non-US Equity", "book_index": "EAFEValue",     "ticker": "EFV", "proxy_type": "primary"},
    {"category": "Non-US Equity", "book_index": "Europe",        "ticker": "IEV", "proxy_type": "primary"},
    {"category": "Non-US Equity", "book_index": "Japan",         "ticker": "EWJ", "proxy_type": "primary"},
    {"category": "Non-US Equity", "book_index": "IntlSmallCap",  "ticker": "SCZ", "proxy_type": "primary"},
    {"category": "Non-US Equity", "book_index": "EM",            "ticker": "EEM", "proxy_type": "primary"},

    # Core Bonds
    {"category": "Core Bonds", "book_index": "USAgg",            "ticker": "AGG",  "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "ShortTerm",        "ticker": "BSV",  "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "GNMA",             "ticker": "VMBS", "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "CorpIG",           "ticker": "LQD",  "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "Gov/Credit",       "ticker": "GVI",  "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "Cash/Libor3M",     "ticker": "BIL",  "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "GlobalAggHedged",  "ticker": "BNDX", "proxy_type": "primary"},
    {"category": "Core Bonds", "book_index": "GlobalAggUnhedged","ticker": "BWX",  "proxy_type": "primary"},

    # Diversifying
    {"category": "Diversifying", "book_index": "TreasuryLong",   "ticker": "TLT",  "proxy_type": "primary"},
    {"category": "Diversifying", "book_index": "HighYield",      "ticker": "HYG",  "proxy_type": "primary"},
    {"category": "Diversifying", "book_index": "FloatingRate",   "ticker": "BKLN", "proxy_type": "primary"},
    {"category": "Diversifying", "book_index": "EMBond",         "ticker": "EMB",  "proxy_type": "primary"},
    {"category": "Diversifying", "book_index": "EMLocal",        "ticker": "EMLC", "proxy_type": "primary"},

    # Inflation
    {"category": "Inflation", "book_index": "BroadTIPS",         "ticker": "TIP",  "proxy_type": "primary"},
    {"category": "Inflation", "book_index": "ShortTIPS",         "ticker": "VTIP", "proxy_type": "primary"},

    # Alternative
    {"category": "Alternative", "book_index": "HFRI-Proxy(approx)", "ticker": "QAI", "proxy_type": "primary"},

    # Real Assets — no clean single proxy, candidates only (info, no mixing decision yet)
    {"category": "Real Assets", "book_index": "RealAssets", "ticker": "VNQ", "proxy_type": "candidate"},
    {"category": "Real Assets", "book_index": "RealAssets", "ticker": "GLD", "proxy_type": "candidate"},
    {"category": "Real Assets", "book_index": "RealAssets", "ticker": "XLE", "proxy_type": "candidate"},
    {"category": "Real Assets", "book_index": "RealAssets", "ticker": "DBC", "proxy_type": "candidate"},
]
# endregion


# ----------------------------------------------------------------------------
# region AUDIT PROXY AVAILABILITY
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Pulls historical prices for every proxy via the shared FMP wrapper and
# records earliest/latest date, number of data points, and whether the
# history reaches back before the 2003-01-01 backtest cutoff.
#
# Uses get_historical_price_full (chunked fetch) instead of get_historical_price
# because a single call to /historical-price-eod/full is capped at 5000 rows
# (~19.8 trading years) and silently drops earlier history rather than erroring.
# ─────────────────────────────────────────────────────────────
results = []

for row in PROXY_MAP:
    ticker = row["ticker"]
    print(f"Checking {ticker} ({row['book_index']})...")

    df_price = get_historical_price_full(ticker, years=YEARS_BACK)

    if df_price.empty:
        results.append({
            **row,
            "earliest_date": None,
            "latest_date": None,
            "data_points": 0,
            "starts_before_2003": False,
        })
        continue

    earliest_date = df_price["date"].min()
    latest_date   = df_price["date"].max()

    results.append({
        **row,
        "earliest_date": earliest_date,
        "latest_date": latest_date,
        "data_points": len(df_price),
        "starts_before_2003": bool(earliest_date <= CUTOFF_DATE),
    })

df_audit = pd.DataFrame(results)
df_audit = df_audit.sort_values("earliest_date", na_position="last").reset_index(drop=True)
# endregion


# ----------------------------------------------------------------------------
# region OUTPUT — TERMINAL TABLE + CSV EXPORT
# ----------------------------------------------------------------------------
print("\n=== Proxy Availability Audit (sorted by earliest start date) ===\n")
print(df_audit.to_string(index=False))

df_audit.to_csv(OUTPUT_CSV, index=False)
print(f"\nCSV saved: {OUTPUT_CSV}")
# endregion


# ----------------------------------------------------------------------------
# region INTERPRETATION
# ----------------------------------------------------------------------------
print("\n=== Interpretation ===")

no_data       = df_audit[df_audit["data_points"] == 0]
after_2003    = df_audit[(df_audit["data_points"] > 0) & (~df_audit["starts_before_2003"])]
no_clean_proxy = df_audit[df_audit["proxy_type"] == "candidate"]["book_index"].unique()

if not no_data.empty:
    tickers_missing = ", ".join(no_data["ticker"].tolist())
    print(f">>> No data returned for: {tickers_missing}. Check ticker validity or FMP coverage.")
else:
    print(">>> All proxies returned price data.")

if not after_2003.empty:
    print(f">>> {len(after_2003)} proxy/proxies start AFTER 2003-01-01 — this limits the common "
          f"backtest window to their later inception date:")
    for _, r in after_2003.iterrows():
        print(f"    - {r['ticker']} ({r['book_index']}): starts {r['earliest_date'].date()}")
else:
    print(">>> All proxies with data start before 2003-01-01 — no additional backtest-window constraint from this set.")

if len(no_clean_proxy) > 0:
    print(f">>> Book index position(s) with no clean single proxy (candidates only, no design decision yet): "
          f"{', '.join(no_clean_proxy)}")
# endregion


# ----------------------------------------------------------------------------
# region LEGENDE
# ----------------------------------------------------------------------------
print("\n=== Legende ===")
print("category            = Asset class bucket from the book's index list (US Equity, Core Bonds, ...)")
print("book_index           = Original book-index position being approximated")
print("ticker               = US-listed ETF proxy ticker queried via FMP")
print("proxy_type           = 'primary' (clean single proxy) or 'candidate' (no clean proxy, approximation option)")
print("earliest_date        = First available daily close date on FMP")
print("latest_date          = Most recent available daily close date on FMP")
print("data_points          = Number of daily price observations returned")
print("starts_before_2003   = True if earliest_date <= 2003-01-01 (book's preferred backtest start)")
# endregion
