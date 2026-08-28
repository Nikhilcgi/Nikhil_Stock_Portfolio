from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

import pandas as pd

from portfolio_tracker.analytics.growth import build_growth_series, monthly_returns, xirr


class GrowthTests(unittest.TestCase):
    def test_flows_do_not_create_false_return_spikes(self):
        source = pd.DataFrame(
            [
                {"valuation_date": "2026-01-01", "total_value": 1000, "contribution_day": 1000, "withdrawal_day": 0},
                {"valuation_date": "2026-01-02", "total_value": 1650, "contribution_day": 500, "withdrawal_day": 0},
                {"valuation_date": "2026-01-03", "total_value": 1450, "contribution_day": 0, "withdrawal_day": 200},
            ]
        )
        result = build_growth_series(source, "ACCOUNT")
        self.assertEqual(result.iloc[0]["daily_return"], Decimal("0"))
        self.assertEqual(result.iloc[1]["daily_return"], Decimal("0.1"))
        self.assertEqual(result.iloc[2]["daily_return"], Decimal("0"))
        self.assertEqual(result.iloc[-1]["cumulative_net_investment"], Decimal("1300"))
        self.assertEqual(result.iloc[-1]["total_gain"], Decimal("150"))
        self.assertEqual(result.iloc[-1]["twr_index"], Decimal("110.0"))

    def test_monthly_return_is_geometrically_chained(self):
        source = pd.DataFrame(
            [
                {"valuation_date": "2026-01-01", "total_value": 100, "contribution_day": 100},
                {"valuation_date": "2026-01-02", "total_value": 110},
                {"valuation_date": "2026-01-03", "total_value": 99},
            ]
        )
        result = monthly_returns(build_growth_series(source, "ACCOUNT"))
        self.assertEqual(result.iloc[0]["monthly_twr"], Decimal("-0.01"))

    def test_xirr_simple_case_is_about_ten_percent(self):
        result = xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), 110)])
        self.assertEqual(result.status, "OK")
        self.assertAlmostEqual(result.rate or 0, 0.10, places=3)

    def test_xirr_rejects_one_sided_cash_flows(self):
        result = xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), -10)])
        self.assertEqual(result.status, "NO_SIGN_CHANGE")
        self.assertIsNone(result.rate)


if __name__ == "__main__":
    unittest.main()
