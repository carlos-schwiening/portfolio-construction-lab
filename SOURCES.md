# Sources

Where every number in this repository comes from, and what each source can and
cannot support. The README says what the dashboard does and what came out; this
file says where the inputs came from, so any figure can be traced back without
reading the code.

Each source has the same fields, so you can skim to the one you need.

One thing to establish first, because it decides how to read everything else:
**this project computes its own numbers from real price history.** It takes the
*idea* of allocation archetypes from a book; it does not reproduce that book's
figures, which are proprietary and were produced with tools this project does
not have.

---

## 1. Financial Modeling Prep — dividend-adjusted daily prices

**What for.** Every metric in the dashboard. Volatility, drawdown, historical
VaR and CVaR, loss probability, rolling statistics, the correlation regime chart
and the Monte Carlo simulation all run off one daily return series per proxy.

**Endpoint.** `/stable/historical-price-eod/dividend-adjusted?symbol={TICKER}`
Pulled once by `data/db_pull_v1.py` (30-year request window) into
`data/portfolio_data.db`.

**See it yourself.** The endpoint needs an API key, so there is no browser link.
What is checkable without one: any single date's adjusted close against a public
total-return chart for the same ETF. A series that disagrees on spot checks is
disqualified; agreement on a few dates is not proof of the whole history.

**Covers.** Ten ETF proxies, 55,692 daily observations. Per-proxy coverage as
stored:

| Proxy | Bucket | From | Trading days |
|---|---|---|---|
| SPY | US Stocks | 1996-07-01 | 7,546 |
| EFA | Non-US Developed | 2001-08-17 | 6,251 |
| TLT | Long Treasury | 2002-07-26 | 6,019 |
| EEM | EM Stocks | 2003-04-11 | 5,840 |
| AGG | Core Bonds | 2003-09-26 | 5,724 |
| TIP | TIPS | 2003-12-05 | 5,675 |
| HYG | High Yield | 2007-04-11 | 4,835 |
| BIL | Cash | 2007-05-30 | 4,801 |
| EMB | EM Bond | 2007-12-19 | 4,659 |
| QAI | Alternatives | 2009-03-25 | 4,342 |

**Cost.** Paid API. The endpoint caps a single response at 5,000 rows and
**truncates silently** beyond that rather than paging or erroring — which is why
the workspace client fetches long histories in dated chunks. Several series
above exceed that cap, so this is not a hypothetical.

**Limits that matter.**
- **Dividend-adjusted, not raw closes** — and for this project that is not a
  detail. Most of a bond ETF's return arrives as distributions, so an unadjusted
  series would understate the bond sleeves badly and make the conservative
  archetypes look far worse than they were.
- **ETF proxies are not asset classes.** Each one carries its own fees, tracking
  error and liquidity. They are a defensible stand-in, not the thing itself.
- Vendor data. It must not be committed, which is why `portfolio_data.db` is
  gitignored and the repository ships the code that rebuilds it, not the data.

---

## 2. The backtest window — derived, not chosen

**What for.** Every archetype is evaluated over one common window so the
comparison is like-for-like.

**How it is set.** At runtime, from the data itself: the latest inception date
across the proxies actually in use. It is **not** hardcoded, so adding or
removing a proxy moves it automatically.

**See it yourself.** The table above is the whole derivation. Among the nine
proxies used, `EMB` starts last, on **2007-12-19** — and that is the window
start the dashboard reports.

**Limits that matter.**
- **QAI is deliberately excluded, and this is why.** Its history begins
  2009-03-25 — within days of the March 2009 market bottom. Including it would
  drag the common window to start at the most favourable possible moment for
  equities, flattering every archetype. The Alternatives sleeve is therefore
  left out of v1 and the remaining bucket weights are renormalised.
- The window still starts in **December 2007**, at the onset of the financial
  crisis. That is unavoidable given the youngest bond proxies, and it cuts the
  other way: the results include a severe bear market near the start. Worth
  knowing before reading any drawdown figure.
- Roughly 18.5 years of daily data is one macro regime and change. It is not a
  sample large enough to settle questions about long-run asset-class behaviour.

---

## 3. `data/portfolio_data.db` — the local store

**What for.** Everything downstream reads from here, not from the API. One pull,
then every dashboard run is offline and reproducible.

**Where.** `data/portfolio_data.db`, one table `prices(symbol, date, adj_close)`.

**See it yourself.** It is a plain SQLite file — any SQLite viewer opens it, and
the VS Code extension in this workspace shows it directly. The rebuild script is
`data/db_pull_v1.py`.

**Cost.** None, once pulled.

**Limits that matter.** Gitignored, so a clone starts empty and needs an FMP key
to rebuild. A snapshot rather than a live feed: the stored history ends
2026-06-29, and nothing refreshes it automatically.

---

## 4. S. Page, *Beyond Diversification* (2021), chapter 17

**What for.** The **concept** only: the idea of a small set of allocation
archetypes from conservative to growth, defined at asset-class and bucket level.

**See it yourself.** The book. Chapter 17, "Sample Portfolios".

**Limits that matter — read this one before comparing anything.**
The book's own figures come from proprietary Barra risk models and capital
market assumptions. **None of them are reproduced here.** Every number in this
repository is computed independently from the ETF price history above, so the
results will not match the book's and are not meant to. The archetypes'
structure is the borrowed part; the numbers are this project's own.

---

## 5. The forward-looking simulation — history, not a forecast

**What it is.** A **block bootstrap**: it draws six-month blocks of consecutive
*observed* monthly portfolio returns, with replacement, and chains them until the
chosen horizon is covered. There is no assumed distribution anywhere — no normal
returns, no expected-return vector, no capital market assumptions.

**Why blocks rather than single months.** Drawing individual months would shuffle
the history and destroy the two properties that matter most for a risk figure:
returns cluster (bad months arrive next to other bad months) and the tails are
fatter than a normal distribution allows. Six-month blocks keep both.

**The one forward-looking lever, and it is off by default.**
`annual_return_haircut` subtracts a fixed annual amount, pro-rata per month, from
every drawn return before compounding. It defaults to **0.0** — the headline
simulation applies nothing. The dashboard's sensitivity tab runs a second
simulation at **2 %** alongside the baseline, so the question *"what if forward
returns are two points lower than the sample period delivered?"* is answered
explicitly rather than assumed away.

That is the honest shape of it: the baseline claims no view on future returns,
and where a view is applied it is visible, named and shown next to the version
without it.

**Limits that matter.** The simulation cannot produce anything the historical
window did not contain. A crisis unlike anything in 2007–2026 is outside its
reach — and the haircut lever shifts the level of the outcomes, not their shape.
Neither is a substitute for the possibility that the future is structurally
different from an 18-year sample.

---

## What this file does not yet do

`credit-risk-validation` has a `verify` command that recomputes every published
figure from its source and reports a mismatch as a finding. This project does
not have one, and the README carries a table of computed risk metrics per
archetype.

Those figures were correct when written. Nothing checks that they still are —
and in the sibling repository a published test count was wrong for months for
exactly that reason.
