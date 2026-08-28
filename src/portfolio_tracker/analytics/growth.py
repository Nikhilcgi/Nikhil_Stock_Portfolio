from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Sequence

import pandas as pd


ZERO = Decimal("0")


@dataclass(frozen=True)
class XirrResult:
    rate: float | None
    status: str
    roots: tuple[float, ...] = ()


def _money(value) -> Decimal:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def build_growth_series(daily: pd.DataFrame, performance_scope: str) -> pd.DataFrame:
    """Build auditable value, investment, gain, TWR, and drawdown columns.

    Required columns are `valuation_date` and `total_value`. Contributions and
    withdrawals are positive magnitudes. Trades are internal movements in ACCOUNT
    scope and must not be supplied as contributions or withdrawals.
    """

    required = {"valuation_date", "total_value"}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"Missing growth-series columns: {sorted(missing)}")
    frame = daily.copy()
    frame["valuation_date"] = pd.to_datetime(frame["valuation_date"]).dt.date
    frame = frame.sort_values("valuation_date").reset_index(drop=True)

    for column in [
        "total_value",
        "contribution_day",
        "withdrawal_day",
        "open_cost_basis",
        "income_day",
        "fees_day",
    ]:
        if column not in frame:
            frame[column] = ZERO
        frame[column] = frame[column].map(_money)
    if "valuation_status" not in frame:
        frame["valuation_status"] = "COMPLETE"

    cumulative_contributions = ZERO
    cumulative_withdrawals = ZERO
    cumulative_income = ZERO
    cumulative_fees = ZERO
    prior_value = ZERO
    prior_index = Decimal("100")
    running_high = Decimal("100")
    output_rows: list[dict] = []

    for position, row in frame.iterrows():
        end_value = row["total_value"]
        contribution = row["contribution_day"]
        withdrawal = row["withdrawal_day"]
        cumulative_contributions += contribution
        cumulative_withdrawals += withdrawal
        cumulative_income += row["income_day"]
        cumulative_fees += row["fees_day"]
        net_investment = cumulative_contributions - cumulative_withdrawals
        gain_day = end_value - prior_value - contribution + withdrawal
        total_gain = end_value - net_investment

        denominator = prior_value + contribution
        status_ok = str(row["valuation_status"]).upper() in {"OK", "COMPLETE"}
        if position == 0 and contribution == ZERO:
            daily_return = ZERO
        elif denominator > ZERO and status_ok:
            daily_return = (end_value + withdrawal) / denominator - Decimal("1")
        else:
            daily_return = None

        if daily_return is not None:
            current_index = prior_index * (Decimal("1") + daily_return)
            running_high = max(running_high, current_index)
            drawdown = current_index / running_high - Decimal("1") if running_high else ZERO
            prior_index = current_index
        else:
            current_index = prior_index
            drawdown = None

        output = row.to_dict()
        output.update(
            {
                "performance_scope": performance_scope,
                "begin_value": prior_value,
                "net_external_flow_day": contribution - withdrawal,
                "cumulative_contributions": cumulative_contributions,
                "cumulative_withdrawals": cumulative_withdrawals,
                "cumulative_net_investment": net_investment,
                "rupee_gain_day": gain_day,
                "total_gain": total_gain,
                "cumulative_income": cumulative_income,
                "cumulative_fees": cumulative_fees,
                "daily_return": daily_return,
                "twr_index": current_index,
                "drawdown": drawdown,
            }
        )
        output_rows.append(output)
        prior_value = end_value

    return pd.DataFrame.from_records(output_rows)


def monthly_returns(growth: pd.DataFrame) -> pd.DataFrame:
    if growth.empty:
        return pd.DataFrame(columns=["month", "monthly_twr", "end_value", "net_external_flow"])
    frame = growth.copy()
    frame["month"] = pd.to_datetime(frame["valuation_date"]).dt.to_period("M").astype(str)

    rows: list[dict] = []
    for month, group in frame.groupby("month", sort=True):
        valid_returns = [value for value in group["daily_return"] if value is not None and not pd.isna(value)]
        chained = Decimal("1")
        for value in valid_returns:
            chained *= Decimal("1") + _money(value)
        rows.append(
            {
                "month": month,
                "actual_valuation_date": group.iloc[-1]["valuation_date"],
                "end_value": group.iloc[-1]["total_value"],
                "contributions": sum(group["contribution_day"], ZERO),
                "withdrawals": sum(group["withdrawal_day"], ZERO),
                "net_external_flow": sum(group["net_external_flow_day"], ZERO),
                "monthly_twr": chained - Decimal("1") if valid_returns else None,
                "completeness": "COMPLETE" if group["daily_return"].notna().all() else "INCOMPLETE",
            }
        )
    return pd.DataFrame.from_records(rows)


def xirr(cash_flows: Sequence[tuple[date | datetime, Decimal | float | int]]) -> XirrResult:
    """Solve XIRR while refusing no-root and multiple-root cases."""

    by_day: dict[date, float] = {}
    for raw_date, raw_amount in cash_flows:
        flow_date = raw_date.date() if isinstance(raw_date, datetime) else raw_date
        by_day[flow_date] = by_day.get(flow_date, 0.0) + float(raw_amount)
    points = sorted((flow_date, amount) for flow_date, amount in by_day.items() if abs(amount) > 1e-12)
    if len(points) < 2 or not any(amount < 0 for _, amount in points) or not any(amount > 0 for _, amount in points):
        return XirrResult(rate=None, status="NO_SIGN_CHANGE")

    origin = points[0][0]

    def npv(rate: float) -> float:
        if rate <= -1:
            return math.nan
        return sum(amount / ((1 + rate) ** ((flow_date - origin).days / 365.2425)) for flow_date, amount in points)

    transformed_grid = [-13.8 + index * (23.0 / 500) for index in range(501)]
    rate_grid = [math.exp(value) - 1 for value in transformed_grid]
    brackets: list[tuple[float, float]] = []
    prior_rate = rate_grid[0]
    prior_value = npv(prior_rate)
    exact_roots: list[float] = []
    for rate in rate_grid[1:]:
        value = npv(rate)
        if math.isfinite(prior_value) and abs(prior_value) < 1e-10:
            exact_roots.append(prior_rate)
        if math.isfinite(prior_value) and math.isfinite(value) and prior_value * value < 0:
            brackets.append((prior_rate, rate))
        prior_rate, prior_value = rate, value

    roots = exact_roots + [_bisect(npv, lower, upper) for lower, upper in brackets]
    unique_roots: list[float] = []
    for root in sorted(roots):
        if not unique_roots or abs(root - unique_roots[-1]) > 1e-7:
            unique_roots.append(root)
    if not unique_roots:
        return XirrResult(rate=None, status="NO_ROOT")
    if len(unique_roots) > 1:
        return XirrResult(rate=None, status="AMBIGUOUS", roots=tuple(unique_roots))
    return XirrResult(rate=unique_roots[0], status="OK", roots=(unique_roots[0],))


def _bisect(function, lower: float, upper: float, tolerance: float = 1e-12, iterations: int = 250) -> float:
    lower_value = function(lower)
    for _ in range(iterations):
        midpoint = (lower + upper) / 2
        midpoint_value = function(midpoint)
        if abs(midpoint_value) < tolerance or abs(upper - lower) < tolerance:
            return midpoint
        if lower_value * midpoint_value <= 0:
            upper = midpoint
        else:
            lower = midpoint
            lower_value = midpoint_value
    return (lower + upper) / 2


def make_growth_figure(growth: pd.DataFrame, benchmark_columns: Iterable[str] = ()):
    """Create the Streamlit-ready Plotly growth and return view."""

    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ModuleNotFoundError as exc:
        raise RuntimeError("Plotly is not installed. Run `python -m pip install -e .`.") from exc

    if growth.empty:
        raise ValueError("Cannot chart an empty growth series")
    dates = growth["valuation_date"]
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.58, 0.16, 0.26],
    )
    figure.add_trace(go.Scatter(x=dates, y=growth["total_value"], name="Portfolio value", mode="lines", line={"width": 2.5}), row=1, col=1)
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=growth["cumulative_net_investment"],
            name="Net cash invested",
            mode="lines",
            line={"dash": "dash", "width": 2},
        ),
        row=1,
        col=1,
    )
    if "open_cost_basis" in growth:
        figure.add_trace(
            go.Scatter(x=dates, y=growth["open_cost_basis"], name="Open-lot cost", mode="lines", line={"dash": "dot"}),
            row=1,
            col=1,
        )
    figure.add_trace(go.Bar(x=dates, y=growth["contribution_day"], name="Contribution", marker_color="#2563EB"), row=2, col=1)
    figure.add_trace(go.Bar(x=dates, y=[-_money(value) for value in growth["withdrawal_day"]], name="Withdrawal", marker_color="#F97316"), row=2, col=1)
    figure.add_trace(go.Scatter(x=dates, y=growth["twr_index"], name="Portfolio TWR (100)", mode="lines", line={"width": 2.5}), row=3, col=1)
    for column in benchmark_columns:
        if column in growth:
            figure.add_trace(go.Scatter(x=dates, y=growth[column], name=column, mode="lines"), row=3, col=1)

    scope = str(growth.iloc[-1].get("performance_scope", "UNKNOWN"))
    figure.update_layout(
        title=f"Portfolio growth · {scope} scope",
        hovermode="x unified",
        barmode="relative",
        legend={"orientation": "h", "y": 1.04},
        margin={"l": 55, "r": 25, "t": 75, "b": 45},
    )
    figure.update_yaxes(title_text="Value (₹)", row=1, col=1)
    figure.update_yaxes(title_text="Flows (₹)", row=2, col=1)
    figure.update_yaxes(title_text="Index", row=3, col=1)
    return figure

