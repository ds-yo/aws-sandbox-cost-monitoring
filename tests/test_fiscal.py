"""scripts/fiscal.py のテスト。"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fiscal import (  # noqa: E402
    add_months,
    default_target_month,
    elapsed_months,
    fiscal_months,
    fiscal_year_of,
    fiscal_year_range,
)


class FiscalYearTest(unittest.TestCase):
    def test_fiscal_year_of_boundaries(self):
        self.assertEqual(fiscal_year_of(date(2026, 4, 1)), 2026)
        self.assertEqual(fiscal_year_of(date(2026, 3, 31)), 2025)
        self.assertEqual(fiscal_year_of(date(2027, 1, 15)), 2026)
        self.assertEqual(fiscal_year_of(date(2026, 12, 31)), 2026)

    def test_fiscal_year_range_end_is_exclusive(self):
        self.assertEqual(fiscal_year_range(2026), (date(2026, 4, 1), date(2027, 4, 1)))

    def test_fiscal_months(self):
        months = fiscal_months(2026)
        self.assertEqual(len(months), 12)
        self.assertEqual(months[0], "2026-04")
        self.assertEqual(months[8], "2026-12")
        self.assertEqual(months[-1], "2027-03")

    def test_elapsed_months(self):
        self.assertEqual(elapsed_months(date(2026, 4, 1)), 1)
        self.assertEqual(elapsed_months(date(2026, 9, 1)), 6)
        self.assertEqual(elapsed_months(date(2027, 3, 1)), 12)

    def test_add_months_across_year(self):
        self.assertEqual(add_months(date(2026, 11, 1), 3), date(2027, 2, 1))
        self.assertEqual(add_months(date(2026, 1, 1), -1), date(2025, 12, 1))

    def test_default_target_month(self):
        self.assertEqual(default_target_month(date(2026, 10, 1)), date(2026, 9, 1))
        self.assertEqual(default_target_month(date(2026, 10, 5)), date(2026, 9, 1))
        self.assertEqual(default_target_month(date(2026, 10, 31)), date(2026, 10, 1))
        self.assertEqual(default_target_month(date(2027, 1, 2)), date(2026, 12, 1))


if __name__ == "__main__":
    unittest.main()
