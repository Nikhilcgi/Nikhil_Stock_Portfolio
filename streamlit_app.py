from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from portfolio_tracker.analytics.growth import make_growth_figure


st.set_page_config(page_title="Indian Portfolio Tracker", page_icon="📈", layout="wide")
st.title("Indian Portfolio Tracker")

database_path = Path(st.sidebar.text_input("DuckDB file", "data/portfolio.duckdb"))
if not database_path.exists():
    st.info("Initialize the database and import broker reports to begin. No sample financial data is displayed.")
    st.stop()

connection = duckdb.connect(str(database_path), read_only=True)
scopes = [row[0] for row in connection.execute("SELECT DISTINCT performance_scope FROM portfolio_daily ORDER BY 1").fetchall()]
if not scopes:
    st.warning(
        "Broker reports have not yet been replayed into daily valuations. Complete transaction history, corporate actions, and prices are required."
    )
    st.stop()

scope = st.sidebar.selectbox("Performance scope", scopes)
portfolio_ids = [
    row[0]
    for row in connection.execute(
        "SELECT DISTINCT portfolio_id FROM portfolio_daily WHERE performance_scope = ? ORDER BY 1", [scope]
    ).fetchall()
]
portfolio_id = st.sidebar.selectbox("Portfolio", portfolio_ids)

daily = connection.execute(
    """
    SELECT * EXCLUDE (calculation_run_id)
    FROM portfolio_daily
    WHERE portfolio_id = ? AND performance_scope = ?
    QUALIFY calculation_run_id = first_value(calculation_run_id) OVER (
        PARTITION BY portfolio_id, performance_scope
        ORDER BY valuation_date DESC, calculation_run_id DESC
    )
    ORDER BY valuation_date
    """,
    [portfolio_id, scope],
).df()

if daily.empty:
    st.warning("No daily portfolio rows are available for this selection.")
    st.stop()

latest = daily.iloc[-1]
card_columns = st.columns(4)
card_columns[0].metric("Portfolio value", f"₹{float(latest['total_value']):,.0f}")
card_columns[1].metric("Net cash invested", f"₹{float(latest['cumulative_net_investment']):,.0f}")
card_columns[2].metric("Total gain", f"₹{float(latest['total_gain']):,.0f}")
card_columns[3].metric("TWR since start", f"{float(latest['twr_index'] / 100 - 1):.1%}")

scope_message = (
    "Account scope: deposits, withdrawals, cash, securities, and receivables are included."
    if scope == "ACCOUNT"
    else "Securities-sleeve scope: investment flows are trade-derived estimates, not verified bank contributions."
)
st.caption(scope_message)

daily["valuation_date"] = pd.to_datetime(daily["valuation_date"]).dt.date
st.plotly_chart(make_growth_figure(daily), use_container_width=True)

quality = daily.iloc[-1]
if str(quality.get("valuation_status", "")).upper() not in {"OK", "COMPLETE"}:
    st.error(f"Latest valuation status: {quality['valuation_status']}")
if int(quality.get("missing_price_count", 0) or 0) > 0:
    st.warning(f"Missing prices: {int(quality['missing_price_count'])}")
if int(quality.get("carried_price_count", 0) or 0) > 0:
    st.info(f"Carried-forward prices: {int(quality['carried_price_count'])}")

with st.expander("Daily audit table"):
    st.dataframe(daily.sort_values("valuation_date", ascending=False), use_container_width=True, hide_index=True)

