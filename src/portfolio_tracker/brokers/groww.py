from __future__ import annotations

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
    to_date,
    to_decimal,
    valid_isin,
)
from portfolio_tracker.models import ParsedHoldings, ParsedTradebook, ReportPeriod


BROKER = "GROWW"
PAISE = Decimal("0.01")


def _money(value) -> Decimal | None:
    parsed = to_decimal(value)
    return parsed.quantize(PAISE) if parsed is not None else None


def parse_tradebook(path: str | Path, account_key: str) -> ParsedTradebook:
    raw = read_raw_report(path, sheet_name="Sheet1")
    table, header_row = extract_table(
        raw,
        required_headers=[
            "stock_name",
            "symbol",
            "isin",
            "type",
            "quantity",
            "value",
            "exchange",
            "exchange_order_id",
            "execution_date_and_time",
            "order_status",
        ],
        primary_column="stock_name",
    )
    table = table.loc[table["order_status"].map(lambda value: (clean_text(value) or "").upper() == "EXECUTED")].reset_index(drop=True)
    source_sha = sha256_file(path)
    source_file = Path(path).name
    records: list[dict[str, Any]] = []

    for _, row in table.iterrows():
        executed_at = pd.to_datetime(str(row["execution_date_and_time"]), dayfirst=True, errors="raise").to_pydatetime()
        trade_date = executed_at.date()
        exchange = (clean_text(row.get("exchange")) or "").upper()
        order_id = clean_identifier(row.get("exchange_order_id"))
        quantity = to_decimal(row.get("quantity"), Decimal("0")) or Decimal("0")
        gross_amount = _money(row.get("value")) or Decimal("0")
        price = gross_amount / quantity if quantity else Decimal("0")
        raw_isin = clean_text(row.get("isin"))
        trade_uid = stable_hash([BROKER, account_key, trade_date, exchange, order_id])
        record = {
            "trade_uid": trade_uid,
            "broker": BROKER,
            "account_key": account_key,
            "trade_date": trade_date,
            "executed_at": executed_at,
            "exchange_timezone": "Asia/Kolkata",
            "exchange": exchange,
            "segment": "EQ",
            "series": None,
            "transaction_type": (clean_text(row.get("type")) or "").upper(),
            "transaction_granularity": "ORDER_AGGREGATE",
            "tax_lot_quality": "ORDER_AGGREGATE_NO_FEES",
            "symbol": (clean_text(row.get("symbol")) or "").upper(),
            "raw_security_name": clean_text(row.get("stock_name")),
            "isin": raw_isin if valid_isin(raw_isin) else None,
            "raw_isin": raw_isin,
            "instrument_type": "EQUITY",
            "quantity": quantity,
            "price": price,
            "gross_amount": gross_amount,
            "calculated_gross_amount": quantity * price,
            "gross_amount_difference": Decimal("0"),
            "brokerage": None,
            "stt": None,
            "stamp_duty": None,
            "exchange_charges": None,
            "gst": None,
            "other_charges": None,
            "net_amount": None,
            "is_auction": False,
            "broker_trade_id": order_id,
            "broker_order_id": order_id,
            "security_resolution_status": "RESOLVED" if valid_isin(raw_isin) else "UNRESOLVED",
            "source_validation_status": "OK",
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        record["row_hash"] = stable_hash(record.values())
        records.append(record)

    trades = pd.DataFrame.from_records(records)
    if not trades.empty and trades.duplicated("trade_uid").any():
        raise ValueError("Duplicate normalized Groww order keys detected")
    declared = find_report_period(raw)
    period = ReportPeriod(
        start=declared.start or (min(trades["trade_date"]) if not trades.empty else None),
        end=declared.end or (max(trades["trade_date"]) if not trades.empty else None),
    )
    return ParsedTradebook(trades=trades, period=period, header_row=header_row, source_sha256=source_sha)


def parse_holdings(path: str | Path, account_key: str) -> ParsedHoldings:
    raw = read_raw_report(path, sheet_name="Sheet1")
    table, header_row = extract_table(
        raw,
        required_headers=["stock_name", "isin", "quantity", "average_buy_price", "buy_value", "closing_price", "closing_value", "unrealised_p_l"],
        primary_column="isin",
        primary_validator=valid_isin,
    )
    declared = find_report_period(raw)
    as_of = declared.as_of or declared.end or declared.start
    source_sha = sha256_file(path)
    source_file = Path(path).name
    snapshot_uid = stable_hash([BROKER, account_key, as_of, source_sha])

    summary_labels = {
        "Invested Value": "invested_value",
        "Closing Value": "present_value",
        "Unrealised P&L": "unrealized_pnl",
    }
    summary: dict[str, Decimal] = {}
    for _, raw_row in raw.iterrows():
        values = raw_row.tolist()
        for label, key in summary_labels.items():
            if label in values:
                position = values.index(label)
                for candidate in values[position + 1 :]:
                    try:
                        amount = _money(candidate)
                    except ValueError:
                        continue
                    if amount is not None:
                        summary[key] = amount
                        break

    records: list[dict[str, Any]] = []
    for _, row in table.iterrows():
        quantity = to_decimal(row.get("quantity"), Decimal("0")) or Decimal("0")
        record = {
            "holding_row_uid": stable_hash([snapshot_uid, clean_text(row.get("isin"))]),
            "snapshot_uid": snapshot_uid,
            "broker": BROKER,
            "account_key": account_key,
            "as_of_date": as_of,
            "symbol": None,
            "raw_security_name": clean_text(row.get("stock_name")),
            "isin": clean_text(row.get("isin")),
            "sector_raw": None,
            "quantity_current": quantity,
            "quantity_available": quantity,
            "reconciliation_quantity": quantity,
            "average_price": to_decimal(row.get("average_buy_price")),
            "reported_invested_value": _money(row.get("buy_value")),
            "previous_close": to_decimal(row.get("closing_price")),
            "current_value": _money(row.get("closing_value")),
            "unrealized_pnl": _money(row.get("unrealised_p_l")),
            "unrealized_pnl_ratio": None,
            "valuation_status": "COMPLETE" if to_decimal(row.get("closing_price")) is not None else "MISSING_PRICE",
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
