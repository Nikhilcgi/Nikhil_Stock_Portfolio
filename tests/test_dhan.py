from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from portfolio_tracker.brokers.dhan import parse_transaction_report


class DhanTests(unittest.TestCase):
    def test_nested_csv_row_is_reparsed_and_preserved_as_activity(self):
        contents = "\n".join(
            [
                "Global Transaction Report 01-04-2025 31-03-2026",
                "",
                "Date,Scrip Name,Exchange,Bill No.,Buy Qty.,Buy Value,Sell Qty.,Sell Value,Brokerage,GST,STT,SEBI Fees,Stamp Duty,Txn. Charges,Oth. Charges,Gross Amount",
                '"28-05-2025,""Example Ltd"",""NSE"",""B1"",""10"",""1000"",""0"",""0"",""1"",""0"",""0"",""0"",""0"",""0"",""0"",""-1001"""',
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dhan.csv"
            path.write_text(contents, encoding="utf-8")
            parsed = parse_transaction_report(path, "dhan-test")

        self.assertEqual(len(parsed.activities), 1)
        self.assertEqual(len(parsed.tradebook.trades), 1)
        self.assertEqual(parsed.activities.iloc[0]["source_validation_status"], "OK")
        self.assertEqual(parsed.tradebook.trades.iloc[0]["transaction_granularity"], "DAILY_SECURITY_AGGREGATE")


if __name__ == "__main__":
    unittest.main()
