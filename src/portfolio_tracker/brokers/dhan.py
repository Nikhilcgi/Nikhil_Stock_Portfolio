from __future__ import annotations

import csv
import re
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
    snake_case,
    stable_hash,
    to_date,
    to_decimal,
    valid_isin,
)
from portfolio_tracker.models import ParsedActivityReport, ParsedHoldings, ParsedTradebook, ReportPeriod


BROKER = "DHAN"
ZERO = Decimal("0")


def _repair_wrapped_csv_line(line: str) -> list[str]:
    text = line.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].replace('""', '"')
    return next(csv.reader([text]))


def _read_malformed_csv_table(path: str | Path, required_headers: set[str]) -> tuple[pd.DataFrame, int, list[str]]:
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    header_index = None
    headers: list[str] = []
    for index, line in enumerate(lines):
        parsed = _repair_wrapped_csv_line(line) if line.strip() else []
        canonical = [snake_case(value) for value in parsed]
        if required_headers.issubset(set(canonical)):
            header_index = index
            headers = canonical
            break
    if header_index is None:
        raise ValueError(f"Could not find Dhan CSV headers: {sorted(required_headers)}")

    rows: list[dict[str, Any]] = []
    for source_index, line in enumerate(lines[header_index + 1 :], start=header_index + 2):
        if not line.strip():
            if rows:
                break
            continue
        values = _repair_wrapped_csv_line(line)
        if len(values) != len(headers):
            break
        row = dict(zip(headers, values))
        row["source_row_number"] = source_index
        rows.append(row)
    return pd.DataFrame.from_records(rows), header_index + 1, lines


def _period_from_lines(lines: list[str]) -> ReportPeriod:
    tokens = re.findall(r"\b\d{2}-\d{2}-\d{4}\b", "\n".join(lines[:8]))
    if len(tokens) >= 2:
        return ReportPeriod(start=to_date(tokens[0]), end=to_date(tokens[1]))
    if tokens:
        return ReportPeriod(as_of=to_date(tokens[0]))
    return ReportPeriod()


def parse_transaction_report(path: str | Path, account_key: str) -> ParsedActivityReport:
    required = {
        "date",
        "scrip_name",
        "exchange",
        "bill_no",
        "buy_qty",
        "buy_value",
        "sell_qty",
        "sell_value",
        "gross_amount",
    }
    table, header_row, lines = _read_malformed_csv_table(path, required)
    period = _period_from_lines(lines)
    source_sha = sha256_file(path)
    source_file = Path(path).name
    activity_records: list[dict[str, Any]] = []
    trade_records: list[dict[str, Any]] = []

    for _, row in table.iterrows():
        activity_date = to_date(row["date"])
        exchange = (clean_text(row.get("exchange")) or "").upper()
        bill_number = clean_identifier(row.get("bill_no"))
        security_name = clean_text(row.get("scrip_name")) or ""
        buy_quantity = to_decimal(row.get("buy_qty"), ZERO) or ZERO
        buy_value = to_decimal(row.get("buy_value"), ZERO) or ZERO
        sell_quantity = to_decimal(row.get("sell_qty"), ZERO) or ZERO
        sell_value = to_decimal(row.get("sell_value"), ZERO) or ZERO
        brokerage = to_decimal(row.get("brokerage"), ZERO) or ZERO
        gst = to_decimal(row.get("gst"), ZERO) or ZERO
        stt = to_decimal(row.get("stt"), ZERO) or ZERO
        sebi = to_decimal(row.get("sebi_fees"), ZERO) or ZERO
        stamp = to_decimal(row.get("stamp_duty"), ZERO) or ZERO
        transaction_charges = to_decimal(row.get("txn_charges"), ZERO) or ZERO
        other_charges = to_decimal(row.get("oth_charges"), ZERO) or ZERO
        reported_net = to_decimal(row.get("gross_amount"), ZERO) or ZERO
        charges = brokerage + gst + stt + sebi + stamp + transaction_charges + other_charges
        calculated_net = sell_value - buy_value - charges
        difference = reported_net - calculated_net

        if buy_quantity > ZERO and sell_quantity > ZERO:
            classification = "INTRADAY_OR_MIXED_DAILY_AGGREGATE" if buy_quantity == sell_quantity else "MIXED_BUY_SELL_DAILY_AGGREGATE"
        elif buy_quantity > ZERO:
            classification = "BUY_DAILY_AGGREGATE"
        else:
            classification = "SELL_DAILY_AGGREGATE"
        if (buy_quantity > ZERO and buy_value == ZERO) or (sell_quantity > ZERO and sell_value == ZERO):
            validation = "ZERO_VALUE_WITH_QUANTITY"
        elif abs(difference) > Decimal("0.05"):
            validation = "NET_AMOUNT_MISMATCH"
        else:
            validation = "OK"

        activity_uid = stable_hash([BROKER, account_key, activity_date, exchange, bill_number, security_name])
        activity = {
            "activity_uid": activity_uid,
            "broker": BROKER,
            "account_key": account_key,
            "activity_date": activity_date,
            "exchange": exchange,
            "segment": "EQ",
            "broker_bill_number": bill_number,
            "symbol": None,
            "isin": None,
            "raw_security_name": security_name,
            "buy_quantity": buy_quantity,
            "buy_value": buy_value,
            "sell_quantity": sell_quantity,
            "sell_value": sell_value,
            "brokerage": brokerage,
            "gst": gst,
            "stt": stt,
            "sebi_fees": sebi,
            "stamp_duty": stamp,
            "exchange_charges": transaction_charges,
            "other_charges": other_charges,
            "reported_net_amount": reported_net,
            "calculated_net_amount": calculated_net,
            "net_amount_difference": difference,
            "activity_classification": classification,
            "source_validation_status": validation,
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        activity["row_hash"] = stable_hash(activity.values())
        activity_records.append(activity)

        for side, quantity, value in [("BUY", buy_quantity, buy_value), ("SELL", sell_quantity, sell_value)]:
            if quantity <= ZERO:
                continue
            trade_uid = stable_hash([activity_uid, side])
            trade = {
                "trade_uid": trade_uid,
                "broker": BROKER,
                "account_key": account_key,
                "trade_date": activity_date,
                "executed_at": None,
                "exchange_timezone": "Asia/Kolkata",
                "exchange": exchange,
                "segment": "EQ",
                "series": None,
                "transaction_type": side,
                "transaction_granularity": "DAILY_SECURITY_AGGREGATE",
                "activity_classification": classification,
                "tax_lot_quality": "PROVISIONAL_DAILY_AGGREGATE",
                "symbol": None,
                "raw_security_name": security_name,
                "isin": None,
                "raw_isin": None,
                "instrument_type": "EQUITY",
                "quantity": quantity,
                "price": value / quantity if quantity else ZERO,
                "gross_amount": value,
                "calculated_gross_amount": value,
                "gross_amount_difference": ZERO,
                "brokerage": None,
                "stt": None,
                "stamp_duty": None,
                "exchange_charges": None,
                "gst": None,
                "other_charges": None,
                "net_amount": None,
                "is_auction": False,
                "broker_trade_id": f"{bill_number}:{activity_uid[:12]}:{side}",
                "broker_order_id": None,
                "source_activity_uid": activity_uid,
                "security_resolution_status": "UNRESOLVED",
                "source_validation_status": validation,
                "source_file": source_file,
                "source_row_number": int(row["source_row_number"]),
                "source_sha256": source_sha,
            }
            trade["row_hash"] = stable_hash(trade.values())
            trade_records.append(trade)

    activities = pd.DataFrame.from_records(activity_records)
    trades = pd.DataFrame.from_records(trade_records)
    if not activities.empty and activities.duplicated("activity_uid").any():
        raise ValueError("Duplicate normalized Dhan activity keys detected")
    if not trades.empty and trades.duplicated("trade_uid").any():
        raise ValueError("Duplicate derived Dhan trade keys detected")
    parsed_tradebook = ParsedTradebook(
        trades=trades,
        period=period,
        header_row=header_row,
        source_sha256=source_sha,
    )
    return ParsedActivityReport(
        activities=activities,
        tradebook=parsed_tradebook,
        period=period,
        header_row=header_row,
        source_sha256=source_sha,
    )


def parse_holdings(path: str | Path, account_key: str) -> ParsedHoldings:
    input_path = Path(path)
    if input_path.suffix.lower() == ".csv":
        table, header_row, lines = _read_malformed_csv_table(
            path,
            {"scrip_name", "isin_code", "free_holding", "locked_in", "closing_price", "valuation"},
        )
        period = _period_from_lines(lines)
        raw = None
    else:
        raw = read_raw_report(path, sheet_name="Dhan_Demat_Holding")
        table, header_row = extract_table(
            raw,
            required_headers=["scrip_name", "isin_code", "free_holding", "locked_in", "closing_price", "valuation"],
            primary_column="isin_code",
            primary_validator=valid_isin,
        )
        period = _period_from_lines([str(value) for value in raw.to_numpy().ravel() if clean_text(value)])

    as_of = period.as_of or period.end or period.start
    source_sha = sha256_file(path)
    source_file = input_path.name
    snapshot_uid = stable_hash([BROKER, account_key, as_of, source_sha])
    records: list[dict[str, Any]] = []
    for _, row in table.iterrows():
        free = to_decimal(row.get("free_holding"), ZERO) or ZERO
        locked = to_decimal(row.get("locked_in"), ZERO) or ZERO
        safe_keep = to_decimal(row.get("safe_keep"), ZERO) or ZERO
        mtf = to_decimal(row.get("mtf_pledge"), ZERO) or ZERO
        margin = to_decimal(row.get("margin_pledge"), ZERO) or ZERO
        cusa = to_decimal(row.get("cusa_pledge"), ZERO) or ZERO
        total_quantity = free + locked + safe_keep + mtf + margin + cusa
        price = to_decimal(row.get("closing_price"))
        value = to_decimal(row.get("valuation"))
        valuation_status = "MISSING_PRICE" if total_quantity > ZERO and (price is None or price == ZERO) else "COMPLETE"
        record = {
            "holding_row_uid": stable_hash([snapshot_uid, clean_text(row.get("isin_code"))]),
            "snapshot_uid": snapshot_uid,
            "broker": BROKER,
            "account_key": account_key,
            "as_of_date": as_of,
            "symbol": None,
            "raw_security_name": clean_text(row.get("scrip_name")),
            "isin": clean_text(row.get("isin_code")),
            "sector_raw": None,
            "quantity_current": total_quantity,
            "quantity_available": free,
            "quantity_locked_in": locked,
            "quantity_safe_keep": safe_keep,
            "quantity_mtf_pledge": mtf,
            "quantity_margin_pledge": margin,
            "quantity_cusa_pledge": cusa,
            "reconciliation_quantity": total_quantity,
            "average_price": None,
            "previous_close": price,
            "current_value": value,
            "unrealized_pnl": None,
            "unrealized_pnl_ratio": None,
            "valuation_status": valuation_status,
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        records.append(record)

    holdings = pd.DataFrame.from_records(records)
    summary = {
        "present_value": sum((value for value in holdings["current_value"] if value is not None), ZERO) if not holdings.empty else ZERO,
        "security_count": Decimal(len(holdings)),
    }
    return ParsedHoldings(
        holdings=holdings,
        summary=summary,
        period=ReportPeriod(as_of=as_of),
        header_row=header_row,
        source_sha256=source_sha,
    )

