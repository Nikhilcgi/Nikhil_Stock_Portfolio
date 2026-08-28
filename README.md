# Indian Portfolio Tracker

A local-first, auditable portfolio tracker for Indian securities held across Zerodha, Upstox, Groww, Angel One, and Dhan. The tracker is designed to use free/open-source components and keep the user's source reports on the local machine.

## Status

All five supplied broker formats now have read-only audit parsers and normalized import adapters:

| Broker | Transactions | Holdings/custody | Important limitation |
|---|---|---|---|
| Zerodha | Execution fills from CSV or XLSX; annual security and charge aggregates | Holdings XLSX | Supplied trades cover one financial year and end before the holdings snapshot |
| Upstox | Trade-number rows with quantity, price, and gross amount | Holdings XLSX with ISIN | Trade rows have no ISIN, exchange symbol, order ID, or charges |
| Groww | Executed order aggregates with symbol and ISIN | Holdings XLSX | Orders have no fill ID or fee breakdown; supplied history starts in April 2026 |
| Angel One | 987 execution fills with per-fill charges; separate account-level charge summary | DP PDF parsed into 478 custody movements and 30 positive closing positions | Trade names need ISIN resolution; opening lots and transfer-ins need historical basis |
| Dhan | 71 daily/bill aggregates, preserved as settlement activities plus 74 provisional BUY/SELL children | Equivalent XLSX and CSV holdings snapshots | Not execution-level; mixed-side rows and charges cannot support exact FIFO |

The supplied files were used only for validation. They are not copied into this project, and client/account identifiers are not displayed by the audit commands.

Fourteen synthetic unit tests pass. The real-file validation also confirms:

- Zerodha's CSV and XLSX contain the same 695 fill identities; the XLSX prices are displayed at lower precision, so deduplication uses broker trade identity rather than row-value equality.
- Upstox's 441 rows reconcile `amount = quantity × price`.
- Groww's 17 holding rows reconcile internally; its report-level invested total differs from the row total by ₹23.19, which remains an explicit warning.
- Angel One's DP opening balance plus quantity-affecting movements reconciles 69 of 70 security blocks; one 17-unit source-statement difference remains for review.
- Dhan's XLSX and CSV holdings are equivalent. One holding is unpriced, and one settlement activity has quantity with zero trade value; neither is silently treated as worthless or as a corporate action.

## Architecture

The DuckDB schema in `sql/schema.sql` keeps these layers separate:

- broker execution fills, order aggregates, and daily settlement aggregates;
- broker charge summaries;
- holdings snapshots and DP custody movements;
- effective-dated instrument and ISIN aliases;
- sourced corporate-action events and transformation legs;
- cash flows, prices, daily positions, and portfolio performance;
- reconciliation exceptions and reproducible calculation runs.

Broker reports are evidence with different meanings. A tradebook row is not interchangeable with a custody movement, holdings snapshot, deposit, dividend, or corporate action.

## Corporate actions

Corporate actions are immutable, sourced events with revisions and review status. Only `CONFIRMED` events may alter lots.

- **Split/consolidation:** change lot quantity by the confirmed ratio while preserving total basis, acquisition date, and FIFO order. Fractional entitlements are settled separately.
- **Bonus:** retain original lots and add a new zero-basis lot on the confirmed allotment date.
- **Dividend:** recognize gross income/receivable from the confirmed entitlement, then record net cash and any withholding separately on actual payment. Quantity and ordinary lot basis do not change.
- **Rights:** record entitlement, renunciation/sale, subscription payment, and allotted shares as separate events. Subscribed shares become a new lot at actual attributable cost.
- **Symbol/ISIN change:** update effective-dated identity without changing quantity or economics.
- **Merger/demerger:** create explicit output legs using official ratios and a confirmed basis-allocation rule. The engine refuses to guess a missing allocation.

The Angel One DP statement demonstrates why this layer is necessary: settlement credits, early-pay-in staging, inter-depository transfers, withheld releases, and generic `AUTO CA` credits have different meanings. The four generic corporate-action credits remain candidates with unknown subtype until matched to authoritative issuer/exchange terms.

FIFO and basis are maintained per demat account, not combined across brokers. The implementation primitives are in `src/portfolio_tracker/analytics/corporate_actions.py`.

## Portfolio-growth graph

The dashboard scaffold and calculation functions distinguish three lines that should never be conflated:

1. portfolio market value;
2. cumulative net cash invested (deposits minus withdrawals);
3. open-lot cost basis.

It also supports total gain, daily and cumulative time-weighted return, drawdown, monthly returns, XIRR, and a normalized total-return benchmark series.

The preferred **ACCOUNT** scope includes securities, cash, and receivables; buys and sells are internal movements, while deposits and withdrawals are external flows. If fund ledgers are unavailable, the tracker can produce a **SECURITIES_SLEEVE** fallback based on net trade cash deployed, but it must be labelled as an estimate rather than true capital contributed.

The chart cannot yet be populated accurately from the supplied partial-period reports alone. It requires complete transaction/custody history, daily prices, confirmed corporate actions, and preferably broker fund ledgers.

## Install and run

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
portfolio-tracker init-db --database data/portfolio.duckdb
streamlit run streamlit_app.py
```

Dependencies are open source: DuckDB, pandas, openpyxl, pdfplumber, Plotly, and Streamlit.

Example read-only audits:

```bash
portfolio-tracker audit-zerodha --tradebook tradebook.xlsx --agts agts.xlsx --holdings holdings.xlsx --account-key zerodha-main
portfolio-tracker audit-upstox --tradebook trades.xlsx --holdings holdings.xlsx --account-key upstox-main
portfolio-tracker audit-groww --tradebook trades.xlsx --holdings holdings.xlsx --account-key groww-main
portfolio-tracker audit-angelone --tradebook trades.xlsx --dp-statement dp-statement.pdf --account-key angel-main
portfolio-tracker audit-dhan --transaction-report global-transactions.csv --holdings holdings.xlsx --account-key dhan-main
```

Replace `audit-` with `import-` and add `--database data/portfolio.duckdb` to import an audited package.

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Inputs still required for an accurate since-inception portfolio

For each broker, export reports from account opening through the current date, including periods with no current holdings:

1. detailed equity tradebooks or contract-note execution lines;
2. funds/account ledgers containing deposits, withdrawals, fees, interest, and cash adjustments;
3. DP transaction statements or a consolidated CDSL/NSDL CAS for opening stock, transfers, and corporate-action credits;
4. dividend and tax-withholding reports where available;
5. current holdings snapshots for reconciliation.

Specific gaps in the supplied sample set:

- Zerodha needs all earlier years and transactions after 2026-03-31.
- Upstox needs earlier history, post-2026-03-31 history, charges, and an instrument/ISIN mapping for its trade names.
- Groww needs history before 2026-04-01 and its charge/cash ledger.
- Angel One needs trades before 2026-03-02, DP history before 2026-01-01, and the funds ledger.
- Dhan needs the detailed tradebook/contract notes, DP transaction statement, funds ledger, and the April–August 2026 activity gap.

An official daily NSE/BSE instrument master and price history can be added after the full broker history is available. Until then, unresolved names and missing basis remain visible rather than being guessed.
# Nikhil_Stock_Portfolio
