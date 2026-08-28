from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby
from typing import Iterable

from portfolio_tracker.brokers.common import stable_hash


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class Lot:
    lot_uid: str
    account_key: str
    instrument_id: str
    quantity: Decimal
    tax_basis: Decimal
    performance_basis: Decimal
    tax_holding_start_date: date
    fifo_entry_date: date
    fifo_sequence: int
    parent_lot_uid: str | None = None
    source_event_uid: str | None = None

    def __post_init__(self) -> None:
        if self.quantity < ZERO:
            raise ValueError("Lot quantity cannot be negative")
        if self.tax_basis < ZERO or self.performance_basis < ZERO:
            raise ValueError("Lot basis cannot be negative")

    @property
    def tax_unit_cost(self) -> Decimal | None:
        return self.tax_basis / self.quantity if self.quantity else None

    @property
    def performance_unit_cost(self) -> Decimal | None:
        return self.performance_basis / self.quantity if self.quantity else None


@dataclass(frozen=True)
class TransformationLeg:
    to_instrument_id: str
    ratio_numerator: int
    ratio_denominator: int
    tax_basis_weight: Decimal
    performance_basis_weight: Decimal
    carry_holding_period: bool = True

    def __post_init__(self) -> None:
        if self.ratio_numerator < 0 or self.ratio_denominator <= 0:
            raise ValueError("Transformation ratios must be non-negative with a positive denominator")
        if not ZERO <= self.tax_basis_weight <= ONE:
            raise ValueError("Tax basis weight must be between zero and one")
        if not ZERO <= self.performance_basis_weight <= ONE:
            raise ValueError("Performance basis weight must be between zero and one")


@dataclass(frozen=True)
class DividendEvent:
    event_uid: str
    account_key: str
    instrument_id: str
    ex_date: date
    payment_date: date | None
    eligible_quantity: Decimal
    gross_per_share: Decimal
    gross_amount: Decimal
    tds_amount: Decimal
    net_amount: Decimal


def apply_split(
    lots: Iterable[Lot],
    *,
    event_uid: str,
    ratio_numerator: int,
    ratio_denominator: int,
    to_instrument_id: str | None = None,
) -> list[Lot]:
    """Apply an exact split/consolidation ratio without custody rounding.

    Economic entitlements retain fractional quantities here. A later account-level
    custody settlement must apply the scheme's rounding rule once and record any
    cash-in-lieu; it must not floor every source lot independently.
    """

    if ratio_numerator <= 0 or ratio_denominator <= 0:
        raise ValueError("Split ratio values must be positive")
    ratio = Decimal(ratio_numerator) / Decimal(ratio_denominator)
    source_lots = list(lots)
    transformed: list[Lot] = []
    for lot in source_lots:
        instrument_id = to_instrument_id or lot.instrument_id
        transformed.append(
            Lot(
                lot_uid=stable_hash([lot.lot_uid, event_uid, instrument_id, "SPLIT"]),
                account_key=lot.account_key,
                instrument_id=instrument_id,
                quantity=lot.quantity * ratio,
                tax_basis=lot.tax_basis,
                performance_basis=lot.performance_basis,
                tax_holding_start_date=lot.tax_holding_start_date,
                fifo_entry_date=lot.fifo_entry_date,
                fifo_sequence=lot.fifo_sequence,
                parent_lot_uid=lot.lot_uid,
                source_event_uid=event_uid,
            )
        )
    _assert_basis_conserved(source_lots, transformed)
    return transformed


def apply_bonus(
    lots: Iterable[Lot],
    *,
    event_uid: str,
    ratio_numerator: int,
    ratio_denominator: int,
    allotment_date: date,
    to_instrument_id: str | None = None,
) -> list[Lot]:
    """Return original lots plus one zero-cost bonus lot per account/instrument."""

    if ratio_numerator <= 0 or ratio_denominator <= 0:
        raise ValueError("Bonus ratio values must be positive")
    source_lots = sorted(list(lots), key=lambda lot: (lot.account_key, lot.instrument_id, lot.fifo_sequence))
    result = list(source_lots)
    ratio = Decimal(ratio_numerator) / Decimal(ratio_denominator)
    for (account_key, instrument_id), grouped in groupby(source_lots, key=lambda lot: (lot.account_key, lot.instrument_id)):
        eligible = list(grouped)
        quantity = sum((lot.quantity for lot in eligible), ZERO) * ratio
        if quantity == ZERO:
            continue
        result.append(
            Lot(
                lot_uid=stable_hash([event_uid, account_key, instrument_id, "BONUS"]),
                account_key=account_key,
                instrument_id=to_instrument_id or instrument_id,
                quantity=quantity,
                tax_basis=ZERO,
                performance_basis=ZERO,
                tax_holding_start_date=allotment_date,
                fifo_entry_date=allotment_date,
                fifo_sequence=max(lot.fifo_sequence for lot in eligible) + 1,
                parent_lot_uid=None,
                source_event_uid=event_uid,
            )
        )
    return result


def apply_identity_change(lots: Iterable[Lot], *, event_uid: str, to_instrument_id: str) -> list[Lot]:
    """Change symbol/ISIN identity without changing quantity, basis, or FIFO rank."""

    return [
        Lot(
            lot_uid=stable_hash([lot.lot_uid, event_uid, to_instrument_id, "IDENTITY_CHANGE"]),
            account_key=lot.account_key,
            instrument_id=to_instrument_id,
            quantity=lot.quantity,
            tax_basis=lot.tax_basis,
            performance_basis=lot.performance_basis,
            tax_holding_start_date=lot.tax_holding_start_date,
            fifo_entry_date=lot.fifo_entry_date,
            fifo_sequence=lot.fifo_sequence,
            parent_lot_uid=lot.lot_uid,
            source_event_uid=event_uid,
        )
        for lot in lots
    ]


def apply_transformation(
    lots: Iterable[Lot],
    *,
    event_uid: str,
    effective_date: date,
    legs: Iterable[TransformationLeg],
) -> list[Lot]:
    """Apply a confirmed merger/demerger transformation with explicit cost weights."""

    source_lots = list(lots)
    output_legs = list(legs)
    if not output_legs:
        raise ValueError("At least one transformation leg is required")
    if sum((leg.tax_basis_weight for leg in output_legs), ZERO) != ONE:
        raise ValueError("Tax basis weights must sum exactly to one")
    if sum((leg.performance_basis_weight for leg in output_legs), ZERO) != ONE:
        raise ValueError("Performance basis weights must sum exactly to one")

    children: list[Lot] = []
    for parent in source_lots:
        for position, leg in enumerate(output_legs, start=1):
            quantity = parent.quantity * Decimal(leg.ratio_numerator) / Decimal(leg.ratio_denominator)
            holding_date = parent.tax_holding_start_date if leg.carry_holding_period else effective_date
            fifo_date = parent.fifo_entry_date if leg.carry_holding_period else effective_date
            children.append(
                Lot(
                    lot_uid=stable_hash([parent.lot_uid, event_uid, position, leg.to_instrument_id]),
                    account_key=parent.account_key,
                    instrument_id=leg.to_instrument_id,
                    quantity=quantity,
                    tax_basis=parent.tax_basis * leg.tax_basis_weight,
                    performance_basis=parent.performance_basis * leg.performance_basis_weight,
                    tax_holding_start_date=holding_date,
                    fifo_entry_date=fifo_date,
                    fifo_sequence=parent.fifo_sequence,
                    parent_lot_uid=parent.lot_uid,
                    source_event_uid=event_uid,
                )
            )
    _assert_basis_conserved(source_lots, children)
    return children


def create_rights_subscription_lot(
    *,
    event_uid: str,
    account_key: str,
    instrument_id: str,
    quantity: Decimal,
    subscription_price: Decimal,
    allotment_date: date,
    fifo_sequence: int,
    acquired_entitlement_cost: Decimal = ZERO,
    attributable_fees: Decimal = ZERO,
) -> Lot:
    if quantity <= ZERO or subscription_price < ZERO:
        raise ValueError("Rights quantity must be positive and subscription price non-negative")
    total_cost = quantity * subscription_price + acquired_entitlement_cost + attributable_fees
    return Lot(
        lot_uid=stable_hash([event_uid, account_key, instrument_id, "RIGHTS_SUBSCRIPTION"]),
        account_key=account_key,
        instrument_id=instrument_id,
        quantity=quantity,
        tax_basis=total_cost,
        performance_basis=total_cost,
        tax_holding_start_date=allotment_date,
        fifo_entry_date=allotment_date,
        fifo_sequence=fifo_sequence,
        source_event_uid=event_uid,
    )


def create_dividend_event(
    *,
    event_uid: str,
    account_key: str,
    instrument_id: str,
    ex_date: date,
    payment_date: date | None,
    eligible_quantity: Decimal,
    gross_per_share: Decimal,
    tds_amount: Decimal = ZERO,
) -> DividendEvent:
    gross = eligible_quantity * gross_per_share
    if eligible_quantity < ZERO or gross_per_share < ZERO or not ZERO <= tds_amount <= gross:
        raise ValueError("Invalid dividend quantity, rate, or TDS")
    return DividendEvent(
        event_uid=event_uid,
        account_key=account_key,
        instrument_id=instrument_id,
        ex_date=ex_date,
        payment_date=payment_date,
        eligible_quantity=eligible_quantity,
        gross_per_share=gross_per_share,
        gross_amount=gross,
        tds_amount=tds_amount,
        net_amount=gross - tds_amount,
    )


def _assert_basis_conserved(source: list[Lot], result: list[Lot]) -> None:
    if not source:
        return
    source_tax = sum((lot.tax_basis for lot in source), ZERO)
    result_tax = sum((lot.tax_basis for lot in result), ZERO)
    source_performance = sum((lot.performance_basis for lot in source), ZERO)
    result_performance = sum((lot.performance_basis for lot in result), ZERO)
    if source_tax != result_tax or source_performance != result_performance:
        raise AssertionError("Corporate action failed basis-conservation invariant")
