from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio_tracker.brokers.common import (
    clean_identifier,
    clean_text,
    extract_table,
    find_report_period,
    read_raw_report,
    sha256_file,
    stable_hash,
    to_bool,
    to_date,
    to_datetime,
    to_decimal,
    valid_isin,
)
from portfolio_tracker.models import ParsedAgts, ParsedHoldings, ParsedTradebook, ReconciliationIssue, ReportPeriod


BROKER = "ZERODHA"


def parse_tradebook(path: str | Path, account_key: str) -> ParsedTradebook:
    raw = read_raw_report(path, sheet_name="Equity")
    table, header_row = extract_table(
        raw,
        required_headers=["symbol", "trade_date", "exchange", "trade_type", "quantity", "price", "trade_id"],
        primary_column="symbol",
    )
    source_sha = sha256_file(path)
    source_file = Path(path).name
    records: list[dict[str, Any]] = []

    for _, row in table.iterrows():
        trade_date = to_date(row["trade_date"])
        exchange = (clean_text(row.get("exchange")) or "").upper()
        segment = (clean_text(row.get("segment")) or "").upper()
        broker_trade_id = clean_identifier(row.get("trade_id"))
        quantity = to_decimal(row.get("quantity"), Decimal("0")) or Decimal("0")
        price = to_decimal(row.get("price"), Decimal("0")) or Decimal("0")
        raw_isin = clean_text(row.get("isin"))
        side = (clean_text(row.get("trade_type")) or "").upper()
        identity = [BROKER, account_key, trade_date, exchange, segment, broker_trade_id]
        trade_uid = stable_hash(identity)
        record = {
            "trade_uid": trade_uid,
            "broker": BROKER,
            "account_key": account_key,
            "trade_date": trade_date,
            "executed_at": to_datetime(row.get("order_execution_time")),
            "exchange_timezone": "Asia/Kolkata",
            "exchange": exchange,
            "segment": segment,
            "series": (clean_text(row.get("series")) or "").upper() or None,
            "transaction_type": side,
            "transaction_granularity": "EXECUTION_FILL",
            "tax_lot_quality": "EXACT_FILL_NO_FEES",
            "symbol": (clean_text(row.get("symbol")) or "").upper(),
            "raw_security_name": None,
            "isin": raw_isin if valid_isin(raw_isin) else None,
            "raw_isin": raw_isin,
            "quantity": quantity,
            "price": price,
            "gross_amount": quantity * price,
            "calculated_gross_amount": quantity * price,
            "gross_amount_difference": Decimal("0"),
            "brokerage": None,
            "stt": None,
            "stamp_duty": None,
            "exchange_charges": None,
            "gst": None,
            "other_charges": None,
            "net_amount": None,
            "is_auction": to_bool(row.get("auction")),
            "broker_trade_id": broker_trade_id,
            "broker_order_id": clean_identifier(row.get("order_id")),
            "security_resolution_status": "RESOLVED" if valid_isin(raw_isin) else "UNRESOLVED",
            "source_validation_status": "OK",
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        record["row_hash"] = stable_hash(record.values())
        records.append(record)

    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        period = find_report_period(raw)
    else:
        declared = ReportPeriod() if Path(path).suffix.lower() == ".csv" else find_report_period(raw)
        period = ReportPeriod(
            start=declared.start or min(trades["trade_date"]),
            end=declared.end or max(trades["trade_date"]),
        )
    _assert_unique_trade_keys(trades)
    return ParsedTradebook(trades=trades, period=period, header_row=header_row, source_sha256=source_sha)


def parse_agts(path: str | Path, account_key: str) -> ParsedAgts:
    raw = read_raw_report(path, sheet_name="Equity")
    source_sha = sha256_file(path)
    source_file = Path(path).name
    period = find_report_period(raw)

    charge_table, _ = extract_table(
        raw,
        required_headers=["account_head", "amount"],
        primary_column="account_head",
    )
    charge_records: list[dict[str, Any]] = []
    for _, row in charge_table.iterrows():
        label = clean_text(row.get("account_head"))
        try:
            amount = to_decimal(row.get("amount"))
        except ValueError:
            break
        if label is None or amount is None:
            break
        record = {
            "charge_uid": stable_hash([BROKER, account_key, period.start, period.end, label, source_sha]),
            "broker": BROKER,
            "account_key": account_key,
            "period_start": period.start,
            "period_end": period.end,
            "account_head": label,
            "amount": amount,
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        charge_records.append(record)

    aggregate_table, header_row = extract_table(
        raw,
        required_headers=["symbol", "exchange", "segment", "buy_quantity", "buy_value", "sell_quantity", "sell_value"],
        primary_column="symbol",
    )
    aggregate_records: list[dict[str, Any]] = []
    for _, row in aggregate_table.iterrows():
        symbol = (clean_text(row.get("symbol")) or "").upper()
        exchange = (clean_text(row.get("exchange")) or "UNKNOWN").upper()
        segment = (clean_text(row.get("segment")) or "").upper()
        record = {
            "aggregate_uid": stable_hash([BROKER, account_key, period.start, period.end, symbol, exchange, segment]),
            "broker": BROKER,
            "account_key": account_key,
            "period_start": period.start,
            "period_end": period.end,
            "symbol": symbol,
            "exchange": exchange,
            "segment": segment,
            "buy_quantity": to_decimal(row.get("buy_quantity"), Decimal("0")) or Decimal("0"),
            "buy_value": to_decimal(row.get("buy_value"), Decimal("0")) or Decimal("0"),
            "sell_quantity": to_decimal(row.get("sell_quantity"), Decimal("0")) or Decimal("0"),
            "sell_value": to_decimal(row.get("sell_value"), Decimal("0")) or Decimal("0"),
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        aggregate_records.append(record)

    return ParsedAgts(
        charges=pd.DataFrame.from_records(charge_records),
        security_aggregates=pd.DataFrame.from_records(aggregate_records),
        period=period,
        header_row=header_row,
        source_sha256=source_sha,
    )


def parse_holdings(path: str | Path, account_key: str) -> ParsedHoldings:
    raw = read_raw_report(path, sheet_name="Equity")
    source_sha = sha256_file(path)
    source_file = Path(path).name
    declared = find_report_period(raw)
    as_of = declared.as_of or declared.end or declared.start
    table, header_row = extract_table(
        raw,
        required_headers=["symbol", "isin", "quantity_available", "average_price", "previous_closing_price"],
        primary_column="symbol",
    )

    summary: dict[str, Decimal] = {}
    summary_labels = {
        "Invested Value": "invested_value",
        "Present Value": "present_value",
        "Unrealized P&L": "unrealized_pnl",
        "Unrealized P&L Pct.": "unrealized_pnl_pct_points",
    }
    for _, row in raw.iterrows():
        values = row.tolist()
        for label, key in summary_labels.items():
            if label in values:
                position = values.index(label)
                amount = None
                for value in values[position + 1 :]:
                    try:
                        candidate = to_decimal(value)
                    except ValueError:
                        continue
                    if candidate is not None:
                        amount = candidate
                        break
                if amount is not None:
                    summary[key] = amount

    snapshot_uid = stable_hash([BROKER, account_key, as_of, source_sha])
    records: list[dict[str, Any]] = []
    for _, row in table.iterrows():
        available = to_decimal(row.get("quantity_available"), Decimal("0")) or Decimal("0")
        discrepant = to_decimal(row.get("quantity_discrepant"), Decimal("0")) or Decimal("0")
        pledged_margin = to_decimal(row.get("quantity_pledged_margin"), Decimal("0")) or Decimal("0")
        pledged_loan = to_decimal(row.get("quantity_pledged_loan"), Decimal("0")) or Decimal("0")
        total_quantity = available + discrepant + pledged_margin + pledged_loan
        average_price = to_decimal(row.get("average_price"))
        previous_close = to_decimal(row.get("previous_closing_price"))
        raw_pct = to_decimal(row.get("unrealized_p_l_pct"))
        record = {
            "holding_row_uid": stable_hash([snapshot_uid, clean_text(row.get("isin")), clean_text(row.get("symbol"))]),
            "snapshot_uid": snapshot_uid,
            "broker": BROKER,
            "account_key": account_key,
            "as_of_date": as_of,
            "symbol": (clean_text(row.get("symbol")) or "").upper(),
            "isin": clean_text(row.get("isin")),
            "sector_raw": clean_text(row.get("sector")),
            "quantity_available": available,
            "quantity_discrepant": discrepant,
            "quantity_long_term": to_decimal(row.get("quantity_long_term"), Decimal("0")) or Decimal("0"),
            "quantity_pledged_margin": pledged_margin,
            "quantity_pledged_loan": pledged_loan,
            "quantity_current": total_quantity,
            "reconciliation_quantity": total_quantity,
            "average_price": average_price,
            "reported_invested_value": total_quantity * average_price if average_price is not None else None,
            "previous_close": previous_close,
            "current_value": total_quantity * previous_close if previous_close is not None else None,
            "unrealized_pnl": to_decimal(row.get("unrealized_p_l")),
            "unrealized_pnl_ratio": (raw_pct / Decimal("100")) if raw_pct is not None else None,
            "valuation_status": "COMPLETE" if previous_close is not None else "MISSING_PRICE",
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        records.append(record)

    return ParsedHoldings(
        holdings=pd.DataFrame.from_records(records),
        summary=summary,
        period=ReportPeriod(as_of=as_of),
        header_row=header_row,
        source_sha256=source_sha,
    )


def reconcile_tradebook_to_agts(
    tradebook: ParsedTradebook,
    agts: ParsedAgts,
    account_key: str,
    value_tolerance: Decimal = Decimal("0.05"),
) -> list[ReconciliationIssue]:
    trade_totals: dict[tuple[str, str, str], dict[str, Decimal]] = defaultdict(
        lambda: {"buy_quantity": Decimal("0"), "buy_value": Decimal("0"), "sell_quantity": Decimal("0"), "sell_value": Decimal("0")}
    )
    for _, row in tradebook.trades.iterrows():
        key = (row["symbol"], row["exchange"], row["segment"])
        side = row["transaction_type"].lower()
        trade_totals[key][f"{side}_quantity"] += row["quantity"]
        trade_totals[key][f"{side}_value"] += row["gross_amount"]

    agts_totals: dict[tuple[str, str, str], dict[str, Decimal]] = {}
    for _, row in agts.security_aggregates.iterrows():
        key = (row["symbol"], row["exchange"], row["segment"])
        agts_totals[key] = {field: row[field] for field in ["buy_quantity", "buy_value", "sell_quantity", "sell_value"]}

    issues: list[ReconciliationIssue] = []
    empty = {"buy_quantity": Decimal("0"), "buy_value": Decimal("0"), "sell_quantity": Decimal("0"), "sell_value": Decimal("0")}
    for key in sorted(set(trade_totals) | set(agts_totals)):
        trade_values = trade_totals.get(key, empty)
        statement_values = agts_totals.get(key, empty)
        differences = {field: trade_values[field] - statement_values[field] for field in empty}
        mismatched = (
            differences["buy_quantity"] != 0
            or differences["sell_quantity"] != 0
            or abs(differences["buy_value"]) > value_tolerance
            or abs(differences["sell_value"]) > value_tolerance
        )
        if not mismatched:
            continue

        if trade_values["buy_quantity"] == 0 and statement_values["buy_quantity"] > 0:
            issue_type = "NON_TRADE_ACQUISITION_CANDIDATE"
            severity = "WARNING"
        elif trade_values["sell_quantity"] == 0 and statement_values["sell_quantity"] > 0:
            issue_type = "MISSING_DISPOSAL_CANDIDATE"
            severity = "ERROR"
        else:
            issue_type = "BROKER_AGGREGATE_MISMATCH"
            severity = "ERROR"
        issues.append(
            ReconciliationIssue(
                issue_type=issue_type,
                severity=severity,
                broker=BROKER,
                account_key=account_key,
                symbol=key[0],
                exchange=key[1],
                details={
                    "segment": key[2],
                    "tradebook": {field: str(value) for field, value in trade_values.items()},
                    "annual_statement": {field: str(value) for field, value in statement_values.items()},
                    "difference": {field: str(value) for field, value in differences.items()},
                },
            )
        )
    return issues


def _assert_unique_trade_keys(trades: pd.DataFrame) -> None:
    if trades.empty:
        return
    duplicates = trades[trades.duplicated("trade_uid", keep=False)]
    if not duplicates.empty:
        raise ValueError(f"Duplicate normalized Zerodha trade keys detected in {len(duplicates)} rows")
