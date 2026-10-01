"""scripts/optimization.py のテスト。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimization import driver_amounts, effective_months, fy_savings, validate  # noqa: E402
from test_report import make_breakdown, make_cost_data, make_optimization  # noqa: E402

REMAINING = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]


class ComputeTest(unittest.TestCase):
    def test_effective_months(self):
        self.assertEqual(effective_months("2026-10", REMAINING), 6)
        self.assertEqual(effective_months("2026-11", REMAINING), 5)
        self.assertEqual(effective_months("2027-03", REMAINING), 1)

    def test_fy_savings_includes_tax(self):
        self.assertAlmostEqual(fy_savings(make_optimization(saving=100, start="2027-01"), REMAINING, 0.1), 330.0)

    def test_driver_amounts_come_from_breakdown(self):
        drivers = driver_amounts(make_optimization(), make_breakdown())
        self.assertEqual(drivers[0]["monthly_usd"], 90.0)


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.cd = make_cost_data()
        self.bd = make_breakdown()

    def test_valid(self):
        self.assertEqual(validate(make_optimization(), self.cd, self.bd), [])

    def test_unknown_usage_type(self):
        opt = make_optimization()
        opt["measures"][0]["usage_types"] = ["APN1-Unknown"]
        self.assertTrue(any("無い使用タイプ" in e for e in validate(opt, self.cd, self.bd)))

    def test_saving_exceeding_actual_requires_ramp_up(self):
        self.assertTrue(any("ramp_up" in e for e in validate(make_optimization(saving=200), self.cd, self.bd)))
        self.assertEqual(validate(make_optimization(saving=200, ramp_up=True), self.cd, self.bd), [])

    def test_start_month_must_be_remaining(self):
        self.assertTrue(any("start_month" in e for e in validate(make_optimization(start="2026-09"), self.cd, self.bd)))

    def test_target_resources_required(self):
        opt = make_optimization()
        opt["measures"][0]["target_resources"] = []
        self.assertTrue(any("target_resources" in e for e in validate(opt, self.cd, self.bd)))

    def test_saving_basis_needs_number(self):
        opt = make_optimization()
        opt["measures"][0]["saving_basis"] = "だいたい半分"
        self.assertTrue(any("saving_basis" in e for e in validate(opt, self.cd, self.bd)))


if __name__ == "__main__":
    unittest.main()
