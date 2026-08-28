from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ReportPeriod:
    start: date | None = None
    end: date | None = None
    as_of: date | None = None


@dataclass
class ParsedTradebook:
    trades: pd.DataFrame
    period: ReportPeriod
    header_row: int
    source_sha256: str


@dataclass
class ParsedAgts:
    charges: pd.DataFrame
    security_aggregates: pd.DataFrame
    period: ReportPeriod
    header_row: int
    source_sha256: str
    summary: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class ParsedHoldings:
    holdings: pd.DataFrame
    summary: dict[str, Decimal]
    period: ReportPeriod
    header_row: int
    source_sha256: str


@dataclass
class ParsedActivityReport:
    activities: pd.DataFrame
    tradebook: ParsedTradebook
    period: ReportPeriod
    header_row: int
    source_sha256: str


@dataclass
class ParsedCustodyStatement:
    movements: pd.DataFrame
    holdings: ParsedHoldings
    reconciliations: pd.DataFrame
    period: ReportPeriod
    source_sha256: str


@dataclass(frozen=True)
class ReconciliationIssue:
    issue_type: str
    severity: str
    broker: str
    account_key: str
    symbol: str | None
    exchange: str | None
    details: dict[str, Any] = field(default_factory=dict)
