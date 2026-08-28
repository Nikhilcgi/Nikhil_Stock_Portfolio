from __future__ import annotations

import re
from collections import Counter
from datetime import date
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
from portfolio_tracker.models import (
    ParsedAgts,
    ParsedCustodyStatement,
    ParsedHoldings,
    ParsedTradebook,
    ReportPeriod,
)


BROKER = "ANGEL_ONE"
ZERO = Decimal("0")
DP_TABLE_HEADER = ["Date", "SCRIPT NAME", "DESCRIPTION", "DEBIT", "CREDIT", "BALANCE", "AMOUNT"]
DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def _trade_period(raw: pd.DataFrame) -> ReportPeriod:
    try:
        start = to_date(raw.iloc[6, 0])
        end = to_date(raw.iloc[6, 1])
        return ReportPeriod(start=start, end=end)
    except (IndexError, TypeError, ValueError):
        return ReportPeriod()


def parse_tradebook(path: str | Path, account_key: str) -> ParsedTradebook:
    raw = read_raw_report(path, sheet_name="TradesAndCharges")
    table, header_row = extract_table(
        raw,
        required_headers=[
            "scrip_contract",
            "buy_sell",
            "buy_price",
            "sell_price",
            "quantity",
            "order_type",
            "segment",
            "exchange",
            "order_id",
            "trade_id",
            "date",
        ],
        primary_column="scrip_contract",
    )
    table = table.loc[
        table["buy_sell"].map(lambda value: (clean_text(value) or "").upper() in {"BUY", "SELL"})
    ].reset_index(drop=True)
    source_sha = sha256_file(path)
    source_file = Path(path).name
    records: list[dict[str, Any]] = []

    for _, row in table.iterrows():
        side = (clean_text(row.get("buy_sell")) or "").upper()
        price = to_decimal(row.get("buy_price") if side == "BUY" else row.get("sell_price"))
        inactive_price = to_decimal(row.get("sell_price") if side == "BUY" else row.get("buy_price"))
        quantity = to_decimal(row.get("quantity"), ZERO) or ZERO
        trade_date = to_date(row.get("date"))
        exchange = (clean_text(row.get("exchange")) or "").upper()
        trade_id = clean_identifier(row.get("trade_id"))
        order_id = clean_identifier(row.get("order_id"))
        product = (clean_text(row.get("order_type")) or "UNKNOWN").upper()
        if price is None or price <= ZERO or quantity <= ZERO:
            validation = "INVALID_ACTIVE_PRICE_OR_QUANTITY"
            normalized_price = price or ZERO
        elif inactive_price not in {None, ZERO, Decimal("1")}:
            validation = "UNEXPECTED_INACTIVE_PRICE"
            normalized_price = price
        else:
            validation = "OK"
            normalized_price = price

        gross = quantity * normalized_price
        charges = {
            "brokerage": to_decimal(row.get("brokerage"), ZERO) or ZERO,
            "gst": to_decimal(row.get("gst"), ZERO) or ZERO,
            "stt": to_decimal(row.get("stt"), ZERO) or ZERO,
            "sebi_tax": to_decimal(row.get("sebi_tax"), ZERO) or ZERO,
            "exchange_charges": to_decimal(row.get("exchange_turnover_charges"), ZERO) or ZERO,
            "stamp_duty": to_decimal(row.get("stamp_duty"), ZERO) or ZERO,
            "other_charges": (to_decimal(row.get("other_charges"), ZERO) or ZERO)
            + (to_decimal(row.get("ipft_charges"), ZERO) or ZERO),
        }
        total_charges = sum(charges.values(), ZERO)
        net_amount = -(gross + total_charges) if side == "BUY" else gross - total_charges
        trade_uid = stable_hash([BROKER, account_key, trade_date, exchange, "EQ", trade_id])
        record = {
            "trade_uid": trade_uid,
            "broker": BROKER,
            "account_key": account_key,
            "trade_date": trade_date,
            "executed_at": None,
            "exchange_timezone": "Asia/Kolkata",
            "exchange": exchange,
            "segment": "EQ",
            "series": None,
            "transaction_type": side,
            "transaction_granularity": "EXECUTION_FILL",
            "activity_classification": product,
            "tax_lot_quality": "EXACT_FILL" if product == "DELIVERY" else "NON_DELIVERY",
            "symbol": None,
            "raw_security_name": clean_text(row.get("scrip_contract")),
            "isin": None,
            "raw_isin": None,
            "instrument_type": "EQUITY",
            "quantity": quantity,
            "price": normalized_price,
            "gross_amount": gross,
            "calculated_gross_amount": gross,
            "gross_amount_difference": ZERO,
            "brokerage": charges["brokerage"],
            "stt": charges["stt"],
            "sebi_fees": charges["sebi_tax"],
            "stamp_duty": charges["stamp_duty"],
            "exchange_charges": charges["exchange_charges"],
            "gst": charges["gst"],
            "ipft_charges": to_decimal(row.get("ipft_charges"), ZERO) or ZERO,
            "other_charges": to_decimal(row.get("other_charges"), ZERO) or ZERO,
            "net_amount": net_amount,
            "is_auction": False,
            "broker_trade_id": trade_id,
            "broker_order_id": order_id,
            "security_resolution_status": "UNRESOLVED",
            "source_validation_status": validation,
            "source_file": source_file,
            "source_row_number": int(row["source_row_number"]),
            "source_sha256": source_sha,
        }
        record["row_hash"] = stable_hash(record.values())
        records.append(record)

    trades = pd.DataFrame.from_records(records)
    if not trades.empty and trades.duplicated("trade_uid").any():
        raise ValueError("Duplicate normalized Angel One trade keys detected")
    declared = _trade_period(raw)
    period = ReportPeriod(
        start=declared.start or (min(trades["trade_date"]) if not trades.empty else None),
        end=declared.end or (max(trades["trade_date"]) if not trades.empty else None),
    )
    return ParsedTradebook(trades=trades, period=period, header_row=header_row, source_sha256=source_sha)


def parse_charge_summary(path: str | Path, account_key: str) -> ParsedAgts:
    raw = read_raw_report(path, sheet_name="TradesAndCharges")
    period = _trade_period(raw)
    source_sha = sha256_file(path)
    source_file = Path(path).name
    rows = {
        16: ("TRADE", "BROKERAGE"),
        17: ("TRADE", "GST"),
        18: ("TRADE", "SEBI_TAX"),
        19: ("TRADE", "STT"),
        20: ("TRADE", "EXCHANGE_TURNOVER"),
        21: ("TRADE", "STAMP_DUTY"),
        22: ("TRADE", "OTHER"),
        23: ("TRADE", "IPFT"),
        26: ("NON_TRADE", "DP_CHARGES"),
        27: ("NON_TRADE", "INTEREST"),
        28: ("NON_TRADE", "ACCOUNT_MAINTENANCE"),
        29: ("NON_TRADE", "PLEDGE"),
        30: ("NON_TRADE", "CALL_AND_TRADE"),
        31: ("NON_TRADE", "MARGIN_SHORTFALL_PENALTY"),
    }
    records: list[dict[str, Any]] = []
    for source_row, (account_head, normalized_type) in rows.items():
        amount = to_decimal(raw.iloc[source_row - 1, 1], ZERO) or ZERO
        records.append(
            {
                "charge_uid": stable_hash([BROKER, account_key, period.start, period.end, account_head, normalized_type]),
                "broker": BROKER,
                "account_key": account_key,
                "period_start": period.start,
                "period_end": period.end,
                "account_head": account_head,
                "normalized_charge_type": normalized_type,
                "amount": amount,
                "source_file": source_file,
                "source_row_number": source_row,
                "source_sha256": source_sha,
            }
        )
    return ParsedAgts(
        charges=pd.DataFrame.from_records(records),
        security_aggregates=pd.DataFrame(),
        period=period,
        header_row=15,
        source_sha256=source_sha,
        summary={
            "source_total_trade_count": to_decimal(raw.iloc[9, 1], ZERO) or ZERO,
            "total_charges": to_decimal(raw.iloc[10, 1], ZERO) or ZERO,
            "total_trade_charges": to_decimal(raw.iloc[11, 1], ZERO) or ZERO,
            "total_non_trade_charges": to_decimal(raw.iloc[12, 1], ZERO) or ZERO,
        },
    )


def classify_dp_description(description: str) -> str:
    normalized = " ".join(description.upper().split())
    if normalized.startswith("NSCCL-CR"):
        return "NSCCL_SETTLEMENT_CREDIT"
    if normalized.startswith("EP-CR"):
        return "EARLY_PAYIN_CREDIT"
    if normalized.startswith("EP-DR"):
        return "EARLY_PAYIN_DEBIT"
    if normalized.startswith("INTDEP-CR"):
        return "INTERDEPOSITORY_CREDIT"
    if normalized.startswith("INTDEP-DR"):
        return "INTERDEPOSITORY_DEBIT"
    if normalized.startswith("AUTO CA"):
        return "AUTO_CORPORATE_ACTION_CREDIT"
    if normalized.startswith("WITHHELD RELEASE"):
        return "WITHHELD_RELEASE_CREDIT"
    if "UNPLEDGE" in normalized:
        return "UNPLEDGE"
    if "PLEDGE" in normalized:
        return "PLEDGE"
    if "BONUS" in normalized:
        return "BONUS"
    if "SPLIT" in normalized:
        return "SPLIT_OR_CONSOLIDATION"
    if "DEMERG" in normalized:
        return "DEMERGER"
    if "MERGER" in normalized or "AMALGAM" in normalized:
        return "MERGER_OR_AMALGAMATION"
    if "RIGHT" in normalized:
        return "RIGHTS"
    if "BUYBACK" in normalized:
        return "BUYBACK"
    return "OTHER"


def _is_corporate_action_candidate(movement_type: str) -> bool:
    return movement_type in {
        "AUTO_CORPORATE_ACTION_CREDIT",
        "BONUS",
        "SPLIT_OR_CONSOLIDATION",
        "DEMERGER",
        "MERGER_OR_AMALGAMATION",
        "RIGHTS",
        "BUYBACK",
    }


def parse_dp_statement(path: str | Path, account_key: str) -> ParsedCustodyStatement:
    try:
        import pdfplumber
    except ModuleNotFoundError as exc:
        raise RuntimeError("pdfplumber is required to import Angel One DP statements") from exc

    source_sha = sha256_file(path)
    source_file = Path(path).name
    current_isin: str | None = None
    current_name: str | None = None
    security_names: dict[str, str] = {}
    opening: dict[str, Decimal] = {}
    closing: dict[str, tuple[Decimal, Decimal]] = {}
    movement_rows: list[dict[str, Any]] = []
    semantic_occurrences: Counter[tuple[Any, ...]] = Counter()

    with pdfplumber.open(path) as document:
        for page_number, page in enumerate(document.pages, start=1):
            for table_number, table in enumerate(page.extract_tables(), start=1):
                if not table or len(table[0]) != 7:
                    continue
                header = ["" if value is None else " ".join(str(value).split()) for value in table[0]]
                if header != DP_TABLE_HEADER:
                    continue
                for row_number, raw_row in enumerate(table[1:], start=2):
                    row = ["" if value is None else " ".join(str(value).split()) for value in raw_row]
                    first, second, description = row[:3]
                    if valid_isin(first):
                        current_isin = first
                        current_name = clean_text(second)
                        if current_name:
                            security_names[current_isin] = current_name
                        continue
                    if current_isin is None:
                        continue
                    if description == "OPENING BALANCE":
                        opening[current_isin] = to_decimal(row[5], ZERO) or ZERO
                        continue
                    if description == "CLOSING BALANCE":
                        closing[current_isin] = (
                            to_decimal(row[5], ZERO) or ZERO,
                            to_decimal(row[6], ZERO) or ZERO,
                        )
                        continue
                    if not DATE_RE.fullmatch(first):
                        continue

                    movement_date = to_date(first)
                    debit = to_decimal(row[3], ZERO) or ZERO
                    credit = to_decimal(row[4], ZERO) or ZERO
                    balance = to_decimal(row[5], ZERO) or ZERO
                    amount = to_decimal(row[6], ZERO) or ZERO
                    reference = clean_identifier(second)
                    movement_type = classify_dp_description(description)
                    affects_total_quantity = movement_type != "EARLY_PAYIN_CREDIT"
                    if movement_type == "EARLY_PAYIN_DEBIT":
                        quantity_delta = -debit
                    elif movement_type == "EARLY_PAYIN_CREDIT":
                        quantity_delta = ZERO
                    else:
                        quantity_delta = credit - debit
                    semantic_key = (
                        account_key,
                        movement_date,
                        current_isin,
                        reference,
                        description,
                        debit,
                        credit,
                        balance,
                        amount,
                    )
                    semantic_occurrences[semantic_key] += 1
                    occurrence = semantic_occurrences[semantic_key]
                    movement_uid = stable_hash([BROKER, *semantic_key, occurrence])
                    record = {
                        "movement_uid": movement_uid,
                        "broker": BROKER,
                        "account_key": account_key,
                        "movement_date": movement_date,
                        "isin": current_isin,
                        "raw_security_name": current_name or security_names.get(current_isin),
                        "source_reference": reference,
                        "description": description,
                        "movement_type": movement_type,
                        "debit_quantity": debit,
                        "credit_quantity": credit,
                        "quantity_delta": quantity_delta,
                        "affects_total_quantity": affects_total_quantity,
                        "balance_quantity": balance,
                        "reported_amount": amount,
                        "is_corporate_action_candidate": _is_corporate_action_candidate(movement_type),
                        "source_page": page_number,
                        "source_table": table_number,
                        "source_row_number": page_number * 1_000_000 + table_number * 1_000 + row_number,
                        "source_file": source_file,
                        "source_sha256": source_sha,
                    }
                    record["row_hash"] = stable_hash(record.values())
                    movement_rows.append(record)

    movements = pd.DataFrame.from_records(movement_rows)
    if movements.empty:
        raise ValueError("No custody movements were found in the Angel One DP statement")
    if movements.duplicated("movement_uid").any():
        raise ValueError("Duplicate normalized Angel One custody movement keys detected")

    observed_start: date = min(movements["movement_date"])
    observed_end: date = max(movements["movement_date"])
    period = ReportPeriod(start=observed_start, end=observed_end, as_of=observed_end)
    snapshot_uid = stable_hash([BROKER, account_key, observed_end, source_sha, "DP_CLOSING"])
    holding_records: list[dict[str, Any]] = []
    reconciliation_records: list[dict[str, Any]] = []
    quantity_deltas = (
        movements.loc[movements["affects_total_quantity"]]
        .groupby("isin")["quantity_delta"]
        .sum()
        .to_dict()
    )
    for isin, (quantity, value) in closing.items():
        opening_quantity = opening.get(isin, ZERO)
        calculated_quantity = opening_quantity + quantity_deltas.get(isin, ZERO)
        quantity_difference = quantity - calculated_quantity
        reconciliation_records.append(
            {
                "reconciliation_uid": stable_hash([snapshot_uid, isin, "CUSTODY_BALANCE"]),
                "broker": BROKER,
                "account_key": account_key,
                "as_of_date": observed_end,
                "isin": isin,
                "opening_quantity": opening_quantity,
                "movement_quantity_delta": quantity_deltas.get(isin, ZERO),
                "calculated_closing_quantity": calculated_quantity,
                "reported_closing_quantity": quantity,
                "quantity_difference": quantity_difference,
                "reconciliation_status": "OK" if quantity_difference == ZERO else "MISMATCH",
                "source_file": source_file,
                "source_sha256": source_sha,
            }
        )
        if quantity <= ZERO:
            continue
        price = value / quantity if value > ZERO else None
        holding_records.append(
            {
                "holding_row_uid": stable_hash([snapshot_uid, isin]),
                "snapshot_uid": snapshot_uid,
                "broker": BROKER,
                "account_key": account_key,
                "as_of_date": observed_end,
                "symbol": None,
                "raw_security_name": security_names.get(isin),
                "isin": isin,
                "sector_raw": None,
                "quantity_current": quantity,
                "quantity_available": quantity,
                "reconciliation_quantity": quantity,
                "quantity_component_difference": quantity_difference,
                "average_price": None,
                "previous_close": price,
                "current_value": value,
                "unrealized_pnl": None,
                "unrealized_pnl_ratio": None,
                "valuation_status": "COMPLETE" if value > ZERO else "MISSING_PRICE",
                "source_file": source_file,
                "source_row_number": 0,
                "source_sha256": source_sha,
            }
        )
    holdings_frame = pd.DataFrame.from_records(holding_records)
    holdings = ParsedHoldings(
        holdings=holdings_frame,
        summary={
            "present_value": sum((row["current_value"] for row in holding_records), ZERO),
            "security_count": Decimal(len(holding_records)),
        },
        period=ReportPeriod(as_of=observed_end),
        header_row=0,
        source_sha256=source_sha,
    )
    return ParsedCustodyStatement(
        movements=movements,
        holdings=holdings,
        reconciliations=pd.DataFrame.from_records(reconciliation_records),
        period=period,
        source_sha256=source_sha,
    )
