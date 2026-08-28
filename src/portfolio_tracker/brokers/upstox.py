from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio_tracker.brokers.common import (
    clean_identifier,
    clean_text,
    extract_table,
    read_raw_report,
    sha256_file,
    stable_hash,
    to_date,
    to_decimal,
    valid_isin,
)
from portfolio_tracker.models import ParsedHoldings, ParsedTradebook, ReportPeriod


BROKER = "UPSTOX"


def _is_excel_date(value: Any) -> bool:
    return isinstance(value, (date, datetime, int, float)) and not isinstance(value, bool) and pd.notna(value)


def _value_after_label(raw: pd.DataFrame, label: str) -> Any | None:
    for _, row in raw.iterrows():
        values = row.tolist()
        for index, value in enumerate(values):
            if clean_text(value) == label:
                return next((candidate for candidate in values[index + 1 :] if clean_text(candidate) is not None), None)
    return None


def _declared_trade_period(raw: pd.DataFrame) -> ReportPeriod:
    value = clean_text(_value_after_label(raw, "Report Time Period")) or ""
    tokens = re.findall(r"\b\d{2}-\d{2}-\d{4}\b", value)
    if len(tokens) == 2:
        return ReportPeriod(start=to_date(tokens[0]), end=to_date(tokens[1]))
    return ReportPeriod()


def _execution_timestamp(trade_date: date, raw_time: Any) -> datetime | None:
    if raw_time is None or (isinstance(raw_time, float) and pd.isna(raw_time)):
        return None
    if isinstance(raw_time, datetime):
        return datetime.combine(trade_date, raw_time.time())
    if isinstance(raw_time, time):
        return datetime.combine(trade_date, raw_time)
    parsed = pd.to_datetime(str(raw_time).strip(), format="mixed", errors="raise")
    return datetime.combine(trade_date, parsed.time())


def parse_tradebook(path: str | Path, account_key: str) -> ParsedTradebook:
    raw = read_raw_report(path, sheet_name="TRADE")
    table, header_row = extract_table(
        raw,
        required_headers=["date", "company", "amount", "exchange", "segment", "trade_num", "side", "quantity", "price"],
        primary_column="date",
        primary_validator=_is_excel_date,
    )
    source_sha = sha256_file(path)
    source_file = Path(path).name
    records: list[dict[str, Any]] = []

    for _, row in table.iterrows():
        trade_date = to_date(row["date"])
        exchange = (clean_text(row.get("exchange")) or "").upper()
        segment = (clean_text(row.get("segment")) or "").upper()
        broker_trade_id = clean_identifier(row.get("trade_num"))
        quantity = to_decimal(row.get("quantity"), Decimal("0")) or Decimal("0")
        price = to_decimal(row.get("price"), Decimal("0")) or Decimal("0")
        reported_amount = to_decimal(row.get("amount"), Decimal("0")) or Decimal("0")
        calculated_amount = quantity * price
        difference = reported_amount - calculated_amount
        side = (clean_text(row.get("side")) or "").upper()
        trade_uid = stable_hash([BROKER, account_key, trade_date, exchange, segment, broker_trade_id])
        expiry_value = row.get("expiry")
        expiry_date = to_date(expiry_value) if clean_text(expiry_value) is not None else None
        record = {
            "trade_uid": trade_uid,
            "broker": BROKER,
            "account_key": account_key,
            "trade_date": trade_date,
            "executed_at": _execution_timestamp(trade_date, row.get("trade_time")),
            "exchange_timezone": "Asia/Kolkata",
            "exchange": exchange,
            "segment": segment,
            "series": None,
            "transaction_type": side,
            "transaction_granularity": "EXECUTION_FILL",
            "tax_lot_quality": "EXACT_FILL_NO_FEES",
            "symbol": None,
            "raw_security_name": clean_text(row.get("company")),
            "isin": None,
            "raw_isin": None,
            "broker_security_code": clean_identifier(row.get("scrip_code")),
            "instrument_type": clean_text(row.get("instrument_type")),
            "strike_price": to_decimal(row.get("strike_price")),
            "expiry_date": expiry_date,
            "quantity": quantity,
            "price": price,
            "gross_amount": reported_amount,
            "calculated_gross_amount": calculated_amount,
            "gross_amount_difference": difference,
            "brokerage": None,
            "stt": None,
            "stamp_duty": None,
            "exchange_charges": None,
            "gst": None,
            "other_charges": None,
            "net_amount": None,
            "is_auction": False,
            "broker_trade_id": broker_trade_id,
            "broker_order_id": None,
            "security_resolution_status": "UNRESOLVED",
            "source_validation_status": "OK" if abs(difference) <= Decimal("0.02") else "AMOUNT_MISMATCH",
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        record["row_hash"] = stable_hash(record.values())
        records.append(record)

    trades = pd.DataFrame.from_records(records)
    if trades.duplicated("trade_uid").any():
        raise ValueError("Duplicate normalized Upstox trade keys detected")
    declared = _declared_trade_period(raw)
    period = ReportPeriod(
        start=declared.start or (min(trades["trade_date"]) if not trades.empty else None),
        end=declared.end or (max(trades["trade_date"]) if not trades.empty else None),
    )
    return ParsedTradebook(trades=trades, period=period, header_row=header_row, source_sha256=source_sha)


def parse_holdings(path: str | Path, account_key: str) -> ParsedHoldings:
    raw = read_raw_report(path, sheet_name="HOLDING")
    table, header_row = extract_table(
        raw,
        required_headers=["isin", "scrip_name", "current_qty", "free_qty", "pledge_qty", "rate", "valuation"],
        primary_column="isin",
        primary_validator=valid_isin,
    )
    as_of_raw = _value_after_label(raw, "Report Date Till")
    as_of = to_date(as_of_raw) if as_of_raw is not None else None
    source_sha = sha256_file(path)
    source_file = Path(path).name
    snapshot_uid = stable_hash([BROKER, account_key, as_of, source_sha])
    records: list[dict[str, Any]] = []

    for _, row in table.iterrows():
        current = to_decimal(row.get("current_qty"), Decimal("0")) or Decimal("0")
        free = to_decimal(row.get("free_qty"), Decimal("0")) or Decimal("0")
        frozen = to_decimal(row.get("freeze_qty"), Decimal("0")) or Decimal("0")
        locked = to_decimal(row.get("locked_qty"), Decimal("0")) or Decimal("0")
        pledged = to_decimal(row.get("pledge_qty"), Decimal("0")) or Decimal("0")
        remat = to_decimal(row.get("remat_qty"), Decimal("0")) or Decimal("0")
        component_total = free + frozen + locked + pledged + remat
        rate = to_decimal(row.get("rate"))
        valuation = to_decimal(row.get("valuation"))
        record = {
            "holding_row_uid": stable_hash([snapshot_uid, clean_text(row.get("isin"))]),
            "snapshot_uid": snapshot_uid,
            "broker": BROKER,
            "account_key": account_key,
            "as_of_date": as_of,
            "symbol": None,
            "raw_security_name": clean_text(row.get("scrip_name")),
            "isin": clean_text(row.get("isin")),
            "sector_raw": None,
            "quantity_current": current,
            "quantity_available": free,
            "quantity_frozen": frozen,
            "quantity_locked": locked,
            "quantity_pledged": pledged,
            "quantity_remat": remat,
            "reconciliation_quantity": current,
            "quantity_component_difference": current - component_total,
            "average_price": None,
            "previous_close": rate,
            "current_value": valuation,
            "unrealized_pnl": None,
            "unrealized_pnl_ratio": None,
            "valuation_status": "COMPLETE" if rate is not None else "MISSING_PRICE",
            "value_date": to_date(row.get("value_date")),
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        records.append(record)

    holdings = pd.DataFrame.from_records(records)
    summary = {
        "present_value": sum((value for value in holdings["current_value"] if value is not None), Decimal("0"))
        if not holdings.empty
        else Decimal("0")
    }
    return ParsedHoldings(
        holdings=holdings,
        summary=summary,
        period=ReportPeriod(as_of=as_of),
        header_row=header_row,
        source_sha256=source_sha,
    )
