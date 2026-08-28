from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio_tracker.brokers.common import stable_hash
from portfolio_tracker.models import (
    ParsedActivityReport,
    ParsedAgts,
    ParsedCustodyStatement,
    ParsedHoldings,
    ParsedTradebook,
)


def _duckdb():
    try:
        import duckdb
    except ModuleNotFoundError as exc:
        raise RuntimeError("DuckDB is not installed. Run `python -m pip install -e .` in the project environment.") from exc
    return duckdb


def connect(database_path: str | Path):
    database = Path(database_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    return _duckdb().connect(str(database))


def init_database(database_path: str | Path, schema_path: str | Path | None = None) -> None:
    schema = Path(schema_path) if schema_path else Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
    with connect(database_path) as connection:
        connection.execute(schema.read_text(encoding="utf-8"))


def register_account(connection, account_key: str, broker: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO accounts (account_key, broker) VALUES (?, ?)",
        [account_key, broker],
    )


def import_tradebook(connection, parsed: ParsedTradebook, report_kind: str = "TRADEBOOK") -> dict[str, int]:
    if parsed.trades.empty:
        return {"received": 0, "inserted": 0}
    first = parsed.trades.iloc[0]
    register_account(connection, first["account_key"], first["broker"])
    inserted = _insert_frame(connection, "trades", parsed.trades)
    _record_batch(
        connection,
        broker=first["broker"],
        account_key=first["account_key"],
        report_kind=report_kind,
        source_file=first["source_file"],
        source_sha256=parsed.source_sha256,
        report_start=parsed.period.start,
        report_end=parsed.period.end,
        as_of_date=parsed.period.as_of,
        header_row=parsed.header_row,
        row_count=len(parsed.trades),
    )
    return {"received": len(parsed.trades), "inserted": inserted}


def import_agts(connection, parsed: ParsedAgts) -> dict[str, int]:
    frames = [frame for frame in [parsed.charges, parsed.security_aggregates] if not frame.empty]
    if not frames:
        return {"charges_inserted": 0, "aggregates_inserted": 0}
    first = frames[0].iloc[0]
    register_account(connection, first["account_key"], first["broker"])
    charge_count = _insert_frame(connection, "broker_period_charges", parsed.charges)
    aggregate_count = _insert_frame(connection, "broker_security_aggregates", parsed.security_aggregates)
    _record_batch(
        connection,
        broker=first["broker"],
        account_key=first["account_key"],
        report_kind="ANNUAL_GLOBAL_TRANSACTION_STATEMENT",
        source_file=first["source_file"],
        source_sha256=parsed.source_sha256,
        report_start=parsed.period.start,
        report_end=parsed.period.end,
        as_of_date=None,
        header_row=parsed.header_row,
        row_count=len(parsed.security_aggregates),
    )
    return {"charges_inserted": charge_count, "aggregates_inserted": aggregate_count}


def import_holdings(connection, parsed: ParsedHoldings) -> dict[str, int]:
    if parsed.holdings.empty:
        return {"received": 0, "inserted": 0}
    first = parsed.holdings.iloc[0]
    register_account(connection, first["account_key"], first["broker"])
    summary_json = json.dumps(parsed.summary, default=str, separators=(",", ":"))
    connection.execute(
        """
        INSERT OR IGNORE INTO broker_holding_snapshots
        (snapshot_uid, broker, account_key, as_of_date, summary_json, source_file, source_sha256)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            first["snapshot_uid"],
            first["broker"],
            first["account_key"],
            parsed.period.as_of,
            summary_json,
            first["source_file"],
            parsed.source_sha256,
        ],
    )
    inserted = _insert_frame(connection, "broker_holding_rows", parsed.holdings)
    _record_batch(
        connection,
        broker=first["broker"],
        account_key=first["account_key"],
        report_kind="HOLDINGS_SNAPSHOT",
        source_file=first["source_file"],
        source_sha256=parsed.source_sha256,
        report_start=None,
        report_end=None,
        as_of_date=parsed.period.as_of,
        header_row=parsed.header_row,
        row_count=len(parsed.holdings),
    )
    return {"received": len(parsed.holdings), "inserted": inserted}


def import_activity_report(connection, parsed: ParsedActivityReport) -> dict[str, Any]:
    if parsed.activities.empty:
        return {"activities_received": 0, "activities_inserted": 0, "derived_trades": {"received": 0, "inserted": 0}}
    first = parsed.activities.iloc[0]
    register_account(connection, first["account_key"], first["broker"])
    activity_count = _insert_frame(connection, "broker_activity_aggregates", parsed.activities)
    _record_batch(
        connection,
        broker=first["broker"],
        account_key=first["account_key"],
        report_kind="GLOBAL_TRANSACTION_REPORT",
        source_file=first["source_file"],
        source_sha256=parsed.source_sha256,
        report_start=parsed.period.start,
        report_end=parsed.period.end,
        as_of_date=None,
        header_row=parsed.header_row,
        row_count=len(parsed.activities),
    )
    derived = import_tradebook(connection, parsed.tradebook, report_kind="GLOBAL_TRANSACTION_DERIVED_TRADES")
    return {
        "activities_received": len(parsed.activities),
        "activities_inserted": activity_count,
        "derived_trades": derived,
    }


def import_custody_statement(connection, parsed: ParsedCustodyStatement) -> dict[str, Any]:
    if parsed.movements.empty:
        return {"movements_received": 0, "movements_inserted": 0, "reconciliations_inserted": 0}
    first = parsed.movements.iloc[0]
    register_account(connection, first["account_key"], first["broker"])
    movement_count = _insert_frame(connection, "custody_movements", parsed.movements)
    reconciliation_count = _insert_frame(
        connection,
        "custody_position_reconciliations",
        parsed.reconciliations,
    )
    holdings_result = import_holdings(connection, parsed.holdings)
    _record_batch(
        connection,
        broker=first["broker"],
        account_key=first["account_key"],
        report_kind="DP_TRANSACTION_STATEMENT",
        source_file=first["source_file"],
        source_sha256=parsed.source_sha256,
        report_start=parsed.period.start,
        report_end=parsed.period.end,
        as_of_date=parsed.period.as_of,
        header_row=0,
        row_count=len(parsed.movements),
    )
    return {
        "movements_received": len(parsed.movements),
        "movements_inserted": movement_count,
        "reconciliations_inserted": reconciliation_count,
        "holdings": holdings_result,
    }


def _record_batch(
    connection,
    *,
    broker: str,
    account_key: str,
    report_kind: str,
    source_file: str,
    source_sha256: str,
    report_start,
    report_end,
    as_of_date,
    header_row: int,
    row_count: int,
) -> None:
    batch_uid = stable_hash([broker, account_key, report_kind, source_sha256])
    connection.execute(
        """
        INSERT OR IGNORE INTO import_batches
        (batch_uid, broker, account_key, report_kind, source_file, source_sha256,
         report_start, report_end, as_of_date, header_row, imported_row_count, import_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IMPORTED')
        """,
        [
            batch_uid,
            broker,
            account_key,
            report_kind,
            source_file,
            source_sha256,
            report_start,
            report_end,
            as_of_date,
            header_row,
            row_count,
        ],
    )


def _insert_frame(connection, table_name: str, frame: pd.DataFrame) -> int:
    allowed_tables = {
        "trades",
        "broker_period_charges",
        "broker_security_aggregates",
        "broker_activity_aggregates",
        "broker_holding_rows",
        "custody_movements",
        "custody_position_reconciliations",
    }
    if table_name not in allowed_tables:
        raise ValueError(f"Unsupported import table: {table_name}")
    if frame.empty:
        return 0

    table_columns = [row[0] for row in connection.execute(f"DESCRIBE {table_name}").fetchall()]
    columns = [column for column in frame.columns if column in table_columns]
    incoming = frame[columns].copy()
    before = connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
    connection.register("incoming_frame", incoming)
    try:
        quoted = ", ".join(f'"{column}"' for column in columns)
        connection.execute(f"INSERT OR IGNORE INTO {table_name} ({quoted}) SELECT {quoted} FROM incoming_frame")
    finally:
        connection.unregister("incoming_frame")
    after = connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
    return int(after - before)
