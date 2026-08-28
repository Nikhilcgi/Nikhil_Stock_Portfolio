from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from portfolio_tracker import db
from portfolio_tracker.brokers import angelone, dhan, groww, upstox, zerodha


def _count(frame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame:
        return {}
    return {str(key): int(value) for key, value in frame[column].value_counts().sort_index().items()}


def _json_print(payload) -> None:
    print(json.dumps(payload, default=str, indent=2, sort_keys=True))


def audit_zerodha(args) -> None:
    tradebook = zerodha.parse_tradebook(args.tradebook, args.account_key)
    agts = zerodha.parse_agts(args.agts, args.account_key) if args.agts else None
    holdings = zerodha.parse_holdings(args.holdings, args.account_key) if args.holdings else None
    issues = zerodha.reconcile_tradebook_to_agts(tradebook, agts, args.account_key) if agts else []
    payload = {
        "broker": "ZERODHA",
        "tradebook": {
            "rows": len(tradebook.trades),
            "period": tradebook.period,
            "actual_min_date": min(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "actual_max_date": max(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "sides": _count(tradebook.trades, "transaction_type"),
            "exchanges": _count(tradebook.trades, "exchange"),
            "distinct_symbols": int(tradebook.trades["symbol"].nunique()),
            "unresolved_isin_rows": int(tradebook.trades["isin"].isna().sum()),
        },
        "annual_statement": None
        if agts is None
        else {
            "security_rows": len(agts.security_aggregates),
            "charge_rows": len(agts.charges),
            "total_period_charges": sum(agts.charges["amount"], Decimal("0")),
        },
        "holdings": None
        if holdings is None
        else {
            "rows": len(holdings.holdings),
            "as_of": holdings.period.as_of,
            "summary": holdings.summary,
        },
        "reconciliation_issues": [issue.__dict__ for issue in issues],
    }
    _json_print(payload)


def audit_upstox(args) -> None:
    tradebook = upstox.parse_tradebook(args.tradebook, args.account_key)
    holdings = upstox.parse_holdings(args.holdings, args.account_key) if args.holdings else None
    payload = {
        "broker": "UPSTOX",
        "tradebook": {
            "rows": len(tradebook.trades),
            "period": tradebook.period,
            "actual_min_date": min(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "actual_max_date": max(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "sides": _count(tradebook.trades, "transaction_type"),
            "exchanges": _count(tradebook.trades, "exchange"),
            "distinct_raw_securities": int(tradebook.trades["raw_security_name"].nunique()),
            "unresolved_security_rows": int((tradebook.trades["security_resolution_status"] != "RESOLVED").sum()),
            "amount_validation_failures": int((tradebook.trades["source_validation_status"] != "OK").sum()),
        },
        "holdings": None
        if holdings is None
        else {
            "rows": len(holdings.holdings),
            "as_of": holdings.period.as_of,
            "summary": holdings.summary,
            "quantity_component_mismatches": int((holdings.holdings["quantity_component_difference"] != 0).sum()),
        },
    }
    _json_print(payload)


def audit_groww(args) -> None:
    tradebook = groww.parse_tradebook(args.tradebook, args.account_key)
    holdings = groww.parse_holdings(args.holdings, args.account_key) if args.holdings else None
    payload = {
        "broker": "GROWW",
        "tradebook": {
            "rows": len(tradebook.trades),
            "period": tradebook.period,
            "actual_min_date": min(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "actual_max_date": max(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "sides": _count(tradebook.trades, "transaction_type"),
            "exchanges": _count(tradebook.trades, "exchange"),
            "distinct_isins": int(tradebook.trades["isin"].nunique()),
            "unresolved_isin_rows": int(tradebook.trades["isin"].isna().sum()),
        },
        "holdings": None
        if holdings is None
        else {
            "rows": len(holdings.holdings),
            "as_of": holdings.period.as_of,
            "summary": holdings.summary,
        },
    }
    _json_print(payload)


def audit_angelone(args) -> None:
    tradebook = angelone.parse_tradebook(args.tradebook, args.account_key)
    charges = angelone.parse_charge_summary(args.tradebook, args.account_key)
    line_charge_columns = [
        "brokerage",
        "gst",
        "stt",
        "sebi_fees",
        "stamp_duty",
        "exchange_charges",
        "ipft_charges",
        "other_charges",
    ]
    line_charge_total = sum(
        (sum(tradebook.trades[column], Decimal("0")) for column in line_charge_columns),
        Decimal("0"),
    )
    trade_category_total = sum(
        charges.charges.loc[charges.charges["account_head"] == "TRADE", "amount"],
        Decimal("0"),
    )
    trade_summary_total = charges.summary["total_trade_charges"]
    custody = angelone.parse_dp_statement(args.dp_statement, args.account_key) if args.dp_statement else None
    payload = {
        "broker": "ANGEL_ONE",
        "tradebook": {
            "rows": len(tradebook.trades),
            "period": tradebook.period,
            "actual_min_date": min(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "actual_max_date": max(tradebook.trades["trade_date"]) if not tradebook.trades.empty else None,
            "sides": _count(tradebook.trades, "transaction_type"),
            "exchanges": _count(tradebook.trades, "exchange"),
            "products": _count(tradebook.trades, "activity_classification"),
            "distinct_orders": int(tradebook.trades["broker_order_id"].nunique()),
            "distinct_trade_ids": int(tradebook.trades["broker_trade_id"].nunique()),
            "distinct_raw_securities": int(tradebook.trades["raw_security_name"].nunique()),
            "unresolved_security_rows": int((tradebook.trades["security_resolution_status"] != "RESOLVED").sum()),
            "line_charge_total": line_charge_total,
            "reported_trade_category_total": trade_category_total,
            "reported_trade_charge_total": trade_summary_total,
            "charge_rounding_difference": trade_summary_total - line_charge_total,
        },
        "charge_summary": {
            "trade": trade_summary_total,
            "non_trade": charges.summary["total_non_trade_charges"],
            "total": charges.summary["total_charges"],
            "source_total_trade_count": charges.summary["source_total_trade_count"],
        },
        "custody": None
        if custody is None
        else {
            "movement_rows": len(custody.movements),
            "observed_period": custody.period,
            "movement_types": _count(custody.movements, "movement_type"),
            "corporate_action_candidates": int(custody.movements["is_corporate_action_candidate"].sum()),
            "closing_holdings": len(custody.holdings.holdings),
            "closing_summary": custody.holdings.summary,
            "position_reconciliation_mismatches": int(
                (custody.reconciliations["reconciliation_status"] != "OK").sum()
            ),
        },
    }
    _json_print(payload)


def audit_dhan(args) -> None:
    report = dhan.parse_transaction_report(args.transaction_report, args.account_key)
    holdings = dhan.parse_holdings(args.holdings, args.account_key) if args.holdings else None
    payload = {
        "broker": "DHAN",
        "transaction_report": {
            "activity_rows": len(report.activities),
            "derived_trade_rows": len(report.tradebook.trades),
            "period": report.period,
            "actual_min_date": min(report.activities["activity_date"]) if not report.activities.empty else None,
            "actual_max_date": max(report.activities["activity_date"]) if not report.activities.empty else None,
            "classifications": _count(report.activities, "activity_classification"),
            "validation": _count(report.activities, "source_validation_status"),
            "exchanges": _count(report.activities, "exchange"),
            "distinct_raw_securities": int(report.activities["raw_security_name"].nunique()),
        },
        "holdings": None
        if holdings is None
        else {
            "rows": len(holdings.holdings),
            "as_of": holdings.period.as_of,
            "summary": holdings.summary,
            "unpriced_rows": int((holdings.holdings["valuation_status"] != "COMPLETE").sum()),
        },
    }
    _json_print(payload)


def init_db(args) -> None:
    db.init_database(args.database)
    _json_print({"database": str(Path(args.database).resolve()), "status": "initialized"})


def import_zerodha(args) -> None:
    db.init_database(args.database)
    with db.connect(args.database) as connection:
        result = {"tradebook": db.import_tradebook(connection, zerodha.parse_tradebook(args.tradebook, args.account_key))}
        if args.agts:
            result["agts"] = db.import_agts(connection, zerodha.parse_agts(args.agts, args.account_key))
        if args.holdings:
            result["holdings"] = db.import_holdings(connection, zerodha.parse_holdings(args.holdings, args.account_key))
    _json_print(result)


def import_upstox(args) -> None:
    db.init_database(args.database)
    with db.connect(args.database) as connection:
        result = {"tradebook": db.import_tradebook(connection, upstox.parse_tradebook(args.tradebook, args.account_key))}
        if args.holdings:
            result["holdings"] = db.import_holdings(connection, upstox.parse_holdings(args.holdings, args.account_key))
    _json_print(result)


def import_groww(args) -> None:
    db.init_database(args.database)
    with db.connect(args.database) as connection:
        result = {"tradebook": db.import_tradebook(connection, groww.parse_tradebook(args.tradebook, args.account_key))}
        if args.holdings:
            result["holdings"] = db.import_holdings(connection, groww.parse_holdings(args.holdings, args.account_key))
    _json_print(result)


def import_angelone(args) -> None:
    db.init_database(args.database)
    with db.connect(args.database) as connection:
        result = {
            "tradebook": db.import_tradebook(
                connection,
                angelone.parse_tradebook(args.tradebook, args.account_key),
            ),
            "charges": db.import_agts(
                connection,
                angelone.parse_charge_summary(args.tradebook, args.account_key),
            ),
        }
        if args.dp_statement:
            result["custody"] = db.import_custody_statement(
                connection,
                angelone.parse_dp_statement(args.dp_statement, args.account_key),
            )
    _json_print(result)


def import_dhan(args) -> None:
    db.init_database(args.database)
    with db.connect(args.database) as connection:
        result = {
            "transaction_report": db.import_activity_report(
                connection,
                dhan.parse_transaction_report(args.transaction_report, args.account_key),
            )
        }
        if args.holdings:
            result["holdings"] = db.import_holdings(
                connection,
                dhan.parse_holdings(args.holdings, args.account_key),
            )
    _json_print(result)


def _add_report_args(parser, *, include_agts: bool) -> None:
    parser.add_argument("--tradebook", required=True)
    parser.add_argument("--holdings")
    if include_agts:
        parser.add_argument("--agts")
    parser.add_argument("--account-key", required=True, help="Non-sensitive local account label, for example zerodha-main")


def main() -> None:
    parser = argparse.ArgumentParser(prog="portfolio-tracker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create or update the local DuckDB schema")
    init_parser.add_argument("--database", required=True)
    init_parser.set_defaults(func=init_db)

    z_audit = subparsers.add_parser("audit-zerodha", help="Read-only Zerodha package audit")
    _add_report_args(z_audit, include_agts=True)
    z_audit.set_defaults(func=audit_zerodha)

    u_audit = subparsers.add_parser("audit-upstox", help="Read-only Upstox package audit")
    _add_report_args(u_audit, include_agts=False)
    u_audit.set_defaults(func=audit_upstox)

    g_audit = subparsers.add_parser("audit-groww", help="Read-only Groww package audit")
    _add_report_args(g_audit, include_agts=False)
    g_audit.set_defaults(func=audit_groww)

    a_audit = subparsers.add_parser("audit-angelone", help="Read-only Angel One package audit")
    a_audit.add_argument("--tradebook", required=True)
    a_audit.add_argument("--dp-statement")
    a_audit.add_argument("--account-key", required=True)
    a_audit.set_defaults(func=audit_angelone)

    d_audit = subparsers.add_parser("audit-dhan", help="Read-only Dhan package audit")
    d_audit.add_argument("--transaction-report", required=True)
    d_audit.add_argument("--holdings")
    d_audit.add_argument("--account-key", required=True)
    d_audit.set_defaults(func=audit_dhan)

    z_import = subparsers.add_parser("import-zerodha", help="Import a Zerodha package into DuckDB")
    _add_report_args(z_import, include_agts=True)
    z_import.add_argument("--database", required=True)
    z_import.set_defaults(func=import_zerodha)

    u_import = subparsers.add_parser("import-upstox", help="Import an Upstox package into DuckDB")
    _add_report_args(u_import, include_agts=False)
    u_import.add_argument("--database", required=True)
    u_import.set_defaults(func=import_upstox)

    g_import = subparsers.add_parser("import-groww", help="Import a Groww package into DuckDB")
    _add_report_args(g_import, include_agts=False)
    g_import.add_argument("--database", required=True)
    g_import.set_defaults(func=import_groww)

    a_import = subparsers.add_parser("import-angelone", help="Import an Angel One package into DuckDB")
    a_import.add_argument("--tradebook", required=True)
    a_import.add_argument("--dp-statement")
    a_import.add_argument("--account-key", required=True)
    a_import.add_argument("--database", required=True)
    a_import.set_defaults(func=import_angelone)

    d_import = subparsers.add_parser("import-dhan", help="Import a Dhan package into DuckDB")
    d_import.add_argument("--transaction-report", required=True)
    d_import.add_argument("--holdings")
    d_import.add_argument("--account-key", required=True)
    d_import.add_argument("--database", required=True)
    d_import.set_defaults(func=import_dhan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
