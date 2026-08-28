from __future__ import annotations

import unittest
from datetime import date

from portfolio_tracker.brokers.common import to_date


class CommonParsingTests(unittest.TestCase):
    def test_iso_timestamp_is_not_day_month_swapped(self):
        self.assertEqual(to_date("2026-03-02 00:00:00.0"), date(2026, 3, 2))


if __name__ == "__main__":
    unittest.main()
