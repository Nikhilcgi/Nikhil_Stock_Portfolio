from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from portfolio_tracker.analytics.corporate_actions import (
    Lot,
    TransformationLeg,
    apply_bonus,
    apply_identity_change,
    apply_split,
    apply_transformation,
    create_dividend_event,
    create_rights_subscription_lot,
)


class CorporateActionTests(unittest.TestCase):
    def setUp(self):
        self.lot = Lot(
            lot_uid="lot-1",
            account_key="demat-1",
            instrument_id="old-isin",
            quantity=Decimal("10"),
            tax_basis=Decimal("1000"),
            performance_basis=Decimal("1000"),
            tax_holding_start_date=date(2024, 1, 1),
            fifo_entry_date=date(2024, 1, 2),
            fifo_sequence=1,
        )

    def test_split_preserves_basis_and_fifo(self):
        result = apply_split([self.lot], event_uid="split-1", ratio_numerator=5, ratio_denominator=1, to_instrument_id="new-isin")
        self.assertEqual(result[0].quantity, Decimal("50"))
        self.assertEqual(result[0].tax_basis, Decimal("1000"))
        self.assertEqual(result[0].tax_unit_cost, Decimal("20"))
        self.assertEqual(result[0].fifo_entry_date, self.lot.fifo_entry_date)

    def test_bonus_creates_zero_cost_new_lot(self):
        result = apply_bonus(
            [self.lot],
            event_uid="bonus-1",
            ratio_numerator=1,
            ratio_denominator=2,
            allotment_date=date(2025, 6, 1),
        )
        self.assertEqual(len(result), 2)
        bonus = result[-1]
        self.assertEqual(bonus.quantity, Decimal("5"))
        self.assertEqual(bonus.tax_basis, Decimal("0"))
        self.assertEqual(bonus.tax_holding_start_date, date(2025, 6, 1))

    def test_identity_change_preserves_economics(self):
        changed = apply_identity_change([self.lot], event_uid="rename-1", to_instrument_id="renamed-isin")[0]
        self.assertEqual(changed.instrument_id, "renamed-isin")
        self.assertEqual(changed.quantity, self.lot.quantity)
        self.assertEqual(changed.tax_basis, self.lot.tax_basis)

    def test_demerger_transformation_conserves_bases(self):
        legs = [
            TransformationLeg("retained", 1, 1, Decimal("0.7"), Decimal("0.7")),
            TransformationLeg("resulting", 1, 2, Decimal("0.3"), Decimal("0.3")),
        ]
        children = apply_transformation([self.lot], event_uid="demerger-1", effective_date=date(2025, 1, 1), legs=legs)
        self.assertEqual(sum((lot.tax_basis for lot in children), Decimal("0")), self.lot.tax_basis)
        self.assertEqual(children[1].quantity, Decimal("5"))

    def test_rights_and_dividend_cash_are_separate_from_original_lots(self):
        rights = create_rights_subscription_lot(
            event_uid="rights-1",
            account_key="demat-1",
            instrument_id="rights-share",
            quantity=Decimal("4"),
            subscription_price=Decimal("75"),
            acquired_entitlement_cost=Decimal("20"),
            allotment_date=date(2025, 7, 1),
            fifo_sequence=2,
        )
        self.assertEqual(rights.tax_basis, Decimal("320"))
        dividend = create_dividend_event(
            event_uid="dividend-1",
            account_key="demat-1",
            instrument_id="old-isin",
            ex_date=date(2025, 8, 1),
            payment_date=date(2025, 8, 20),
            eligible_quantity=Decimal("10"),
            gross_per_share=Decimal("2"),
            tds_amount=Decimal("2"),
        )
        self.assertEqual(dividend.gross_amount, Decimal("20"))
        self.assertEqual(dividend.net_amount, Decimal("18"))


if __name__ == "__main__":
    unittest.main()

