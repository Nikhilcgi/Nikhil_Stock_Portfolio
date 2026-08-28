from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from portfolio_tracker.models import ReportPeriod


def snake_case(value: Any) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())).strip("_")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(parts: Iterable[Any]) -> str:
    payload = json.dumps([_json_value(part) for part in parts], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def read_raw_report(path: str | Path, sheet_name: str | int | None = 0) -> pd.DataFrame:
    input_path = Path(path)
    if input_path.suffix.lower() == ".csv":
        return pd.read_csv(input_path, header=None, dtype=str, keep_default_na=False)
    return pd.read_excel(input_path, sheet_name=sheet_name, header=None, dtype=object)


def extract_table(
    raw: pd.DataFrame,
    required_headers: Iterable[str],
    primary_column: str,
    primary_validator: Callable[[Any], bool] | None = None,
) -> tuple[pd.DataFrame, int]:
    required = {snake_case(header) for header in required_headers}
    header_index: int | None = None
    for index, row in raw.iterrows():
        headers = {snake_case(value) for value in row.tolist() if snake_case(value)}
        if required.issubset(headers):
            header_index = int(index)
            break
    if header_index is None:
        raise ValueError(f"Could not find required headers: {sorted(required)}")

    columns: list[str] = []
    used: dict[str, int] = {}
    for position, value in enumerate(raw.iloc[header_index].tolist()):
        base = snake_case(value) or f"unnamed_{position}"
        used[base] = used.get(base, 0) + 1
        columns.append(base if used[base] == 1 else f"{base}_{used[base]}")

    table = raw.iloc[header_index + 1 :].copy()
    table.columns = columns
    table["source_row_number"] = table.index + 1
    if primary_column not in table.columns:
        raise ValueError(f"Primary column {primary_column!r} not found")

    if primary_validator is None:
        mask = table[primary_column].map(lambda value: clean_text(value) is not None)
    else:
        mask = table[primary_column].map(primary_validator)
    return table.loc[mask].reset_index(drop=True), header_index + 1


def clean_text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text if text else None


def clean_identifier(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text[:-2] if re.fullmatch(r"\d+\.0", text) else (text or None)


def to_decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    text = str(value).replace(",", "").strip()
    if not text:
        return default
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[ T])", text):
        return date.fromisoformat(text[:10])
    if re.match(r"^\d{2}-\d{2}-\d{4}(?:$|[ T])", text):
        return datetime.strptime(text[:10], "%d-%m-%Y").date()
    parsed = pd.to_datetime(text, dayfirst=True, errors="raise")
    return parsed.date()


def to_datetime(value: Any) -> datetime | None:
    if clean_text(value) is None:
        return None
    if isinstance(value, datetime):
        return value
    parsed = pd.to_datetime(str(value).strip(), dayfirst=False, errors="raise")
    return parsed.to_pydatetime()


def find_report_period(raw: pd.DataFrame) -> ReportPeriod:
    texts = [str(value) for value in raw.to_numpy().ravel() if clean_text(value)]
    joined = "\n".join(texts)
    date_tokens = re.findall(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})\b", joined)
    parsed: list[date] = []
    for token in date_tokens:
        try:
            parsed.append(to_date(token))
        except (TypeError, ValueError):
            continue
    if len(parsed) >= 2:
        return ReportPeriod(start=parsed[0], end=parsed[1])
    if parsed:
        return ReportPeriod(as_of=parsed[0])
    return ReportPeriod()


def valid_isin(value: Any) -> bool:
    return bool(re.fullmatch(r"IN[A-Z0-9]{10}", clean_text(value) or ""))
