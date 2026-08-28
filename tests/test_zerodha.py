from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from portfolio_tracker.brokers.zerodha import parse_tradebook


class ZerodhaTradebookTests(unittest.TestCase):
    def test_multiple_fills_under_one_order_remain_distinct(self):
        contents = "\n".join(
            [
                "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time",
                "EXAMPLE,INE000A01001,2026-01-02,NSE,EQ,EQ,buy,false,3,100.00,T1,O1,2026-01-02T10:00:00",
                "EXAMPLE,INE000A01001,2026-01-02,NSE,EQ,EQ,buy,false,2,100.05,T2,O1,2026-01-02T10:00:00",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tradebook.csv"
            path.write_text(contents, encoding="utf-8")
            report = parse_tradebook(path, "test-account")

        self.assertEqual(len(report.trades), 2)
        self.assertEqual(report.trades["trade_uid"].nunique(), 2)
        self.assertEqual(report.trades["broker_order_id"].nunique(), 1)
        self.assertEqual(str(report.trades.iloc[1]["gross_amount"]), "200.10")


if __name__ == "__main__":
    unittest.main()

