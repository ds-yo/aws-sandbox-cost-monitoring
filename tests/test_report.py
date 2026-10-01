"""集計・予測検証・予算判定・Slack メッセージ組み立てのテスト。"""

import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_costs import build_summary  # noqa: E402
from slack_report import STATUS_OK, STATUS_OVER, STATUS_WARN, build_message, judge, suggest_budget  # noqa: E402
from validate_forecast import validate  # noqa: E402


def monthly(month: str, services: dict[str, float]) -> dict:
    return {"month": month, "estimated": False, "services": services, "total_usd": sum(services.values())}


def make_cost_data(today: date = date(2026, 10, 1)) -> dict:
    history = [monthly(f"2026-{m:02d}", {"Amazon EC2": 100.0, "Amazon S3": 10.0}) for m in range(4, 10)]
    history.insert(0, monthly("2026-03", {"Amazon EC2": 999.0}))  # 前年度（年度累計に含めない）
    return build_summary(date(2026, 9, 1), today, history, [], {"available": False, "reason": "test"})


def make_forecast(cost_data: dict, monthly_usd: float = 110.0) -> dict:
    remaining = {m: monthly_usd for m in cost_data["remaining_months"]}
    total = cost_data["fy_to_date_usd"] + sum(remaining.values())
    return {
        "fiscal_year": cost_data["fiscal_year"],
        "target_month": cost_data["target_month"],
        "forecast_total_usd": total,
        "forecast_low_usd": total * 0.9 if total * 0.9 >= cost_data["fy_to_date_usd"] else cost_data["fy_to_date_usd"],
        "forecast_high_usd": total * 1.1,
        "current_month_remaining_usd": 0.0,
        "remaining_months_usd": remaining,
        "method": "直近3ヶ月平均",
        "rationale": ["直近3ヶ月の平均 $110/月 で推移"],
        "assumptions": ["新規案件なし"],
        "confidence": "medium",
    }


def make_breakdown() -> dict:
    return {
        "target_month": "2026-09",
        "usage_by_service": [
            {"service": "Amazon EC2", "usage_type": "APN1-NatGateway-Hours", "amount_usd": 90.0, "prev_month_usd": 80.0},
            {"service": "Amazon S3", "usage_type": "APN1-TimedStorage-ByteHrs", "amount_usd": 10.0, "prev_month_usd": 10.0},
        ],
        "region_by_service": [],
    }


def make_optimization(saving: float = 50.0, start: str = "2026-11", **extra) -> dict:
    return {
        "fiscal_year": "FY2026",
        "target_month": "2026-09",
        "cost_drivers": [
            {"title": "NAT Gateway", "usage_types": ["APN1-NatGateway-Hours"], "resource_count": 2, "finding": "稼働 EC2 なし"}
        ],
        "measures": [
            {
                "id": "M1",
                "title": "未使用 NAT Gateway の削除",
                "service": "Amazon EC2",
                "usage_types": ["APN1-NatGateway-Hours"],
                "target_resources": [
                    {"id": "nat-1", "region": "ap-northeast-1", "owner_hint": "alice"},
                    {"id": "nat-2", "region": "ap-northeast-1", "owner_hint": "bob"},
                ],
                "action": "削除",
                "estimated_monthly_saving_usd": saving,
                "saving_basis": "$90 ÷ 2台 ≒ $45/台",
                "start_month": start,
                "effort": "low",
                "risk": "low",
                "decision_by": "各 VPC のオーナー",
                **extra,
            }
        ],
        "summary": "NAT Gateway の削除で月 $50 削減",
    }


def budget_conf(budget: float) -> dict:
    return {
        "fiscal_years": {"FY2026": {"budget_usd": budget}},
        "tax_rate": 0.1,
        "revision": {"buffer_ratio": 0.1, "round_to_usd": 100, "ringi_form_url": "https://example.com/ringi", "mentions": ["<@U000>"]},
    }


class SummaryTest(unittest.TestCase):
    def test_fy_to_date_excludes_previous_fiscal_year(self):
        cd = make_cost_data()
        self.assertEqual(cd["fiscal_year"], "FY2026")
        self.assertAlmostEqual(cd["fy_to_date_usd"], 660.0)
        self.assertEqual(cd["elapsed_months"], 6)
        self.assertEqual(cd["remaining_months"][0], "2026-10")
        self.assertEqual(len(cd["remaining_months"]), 6)
        self.assertTrue(cd["is_month_complete"])
        self.assertEqual(cd["data_through"], "2026-09-30")

    def test_partial_month(self):
        cd = make_cost_data(today=date(2026, 9, 30))
        self.assertFalse(cd["is_month_complete"])
        self.assertEqual(cd["data_through"], "2026-09-29")


class ValidateForecastTest(unittest.TestCase):
    def test_valid(self):
        cd = make_cost_data()
        self.assertEqual(validate(make_forecast(cd), cd), [])

    def test_total_mismatch(self):
        cd = make_cost_data()
        fc = make_forecast(cd)
        fc["forecast_total_usd"] += 50
        fc["forecast_high_usd"] += 50
        self.assertTrue(any("forecast_total_usd" in e for e in validate(fc, cd)))

    def test_low_below_ytd(self):
        cd = make_cost_data()
        fc = make_forecast(cd)
        fc["forecast_low_usd"] = 100.0
        self.assertTrue(any("年度累計実績" in e for e in validate(fc, cd)))

    def test_missing_month_and_no_number_in_rationale(self):
        cd = make_cost_data()
        fc = make_forecast(cd)
        fc["remaining_months_usd"].pop("2027-03")
        fc["rationale"] = ["増加傾向"]
        errors = validate(fc, cd)
        self.assertTrue(any("remaining_months_usd" in e for e in errors))
        self.assertTrue(any("数値" in e for e in errors))


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.cd = make_cost_data()
        self.fc = make_forecast(self.cd)  # total 1320, high 1452

    def test_ok(self):
        self.assertEqual(judge(self.cd, self.fc, budget_conf(2000)).status, STATUS_OK)

    def test_warn(self):
        j = judge(self.cd, self.fc, budget_conf(1400))
        self.assertEqual(j.status, STATUS_WARN)
        self.assertIsNone(j.suggested_budget_usd)

    def test_over_without_measures(self):
        j = judge(self.cd, self.fc, budget_conf(1000))
        self.assertEqual(j.status, STATUS_OVER)
        self.assertEqual(j.status_after, STATUS_OVER)
        self.assertAlmostEqual(j.diff_usd, 320.0)
        self.assertAlmostEqual(j.required_monthly_avg_usd, (1000 - 660) / 6)
        self.assertEqual(j.suggested_budget_usd, 1500)  # max(1452, 1452) → 1500

    def test_measures_bring_within_budget(self):
        # 11月〜3月の5ヶ月 × $50 × 1.1 = $275 削減 → 1320 - 275 = 1045（予算 1100 以内）、high 1177 > 1100 → 注意
        j = judge(self.cd, self.fc, budget_conf(1100), make_optimization())
        self.assertEqual(j.status, STATUS_OVER)
        self.assertAlmostEqual(j.fy_savings_usd, 275.0)
        self.assertAlmostEqual(j.forecast_after_usd, 1045.0)
        self.assertEqual(j.status_after, STATUS_WARN)
        self.assertIsNone(j.suggested_budget_usd)

    def test_measures_not_enough_suggests_reduced_budget(self):
        j = judge(self.cd, self.fc, budget_conf(900), make_optimization())
        self.assertEqual(j.status_after, STATUS_OVER)
        # 施策後 mid 1045 / high 1177 → max(1177, 1149.5) → 1200
        self.assertEqual(j.suggested_budget_usd, 1200)

    def test_budget_in_jpy(self):
        conf = budget_conf(0)
        conf["fiscal_years"]["FY2026"] = {"budget_jpy": 300000, "fx_jpy_per_usd": 150}
        self.assertEqual(judge(self.cd, self.fc, conf).budget_usd, 2000)

    def test_unset_budget_raises(self):
        with self.assertRaises(ValueError):
            judge(self.cd, self.fc, budget_conf(0))

    def test_suggest_budget_rounds_up(self):
        self.assertEqual(suggest_budget(900, 1001, 0.1, 100), 1100)


class BuildMessageTest(unittest.TestCase):
    def setUp(self):
        self.cd = make_cost_data()
        self.fc = make_forecast(self.cd)

    def render(self, budget: float, opt: dict | None = None, ringi_draft: str | None = None) -> str:
        conf = budget_conf(budget)
        j = judge(self.cd, self.fc, conf, opt)
        payload = build_message(self.cd, self.fc, j, conf, opt, make_breakdown() if opt else None, ringi_draft)
        return json.dumps(payload, ensure_ascii=False)

    def test_over_after_measures_has_drivers_measures_and_ringi(self):
        text = self.render(900, make_optimization(), ringi_draft="件名: テスト")
        self.assertIn("コスト消費元", text)
        self.assertIn("$90.00/月", text)  # 消費元の金額は breakdown から計算
        self.assertIn("[M1] 未使用 NAT Gateway の削除", text)
        self.assertIn("alice、bob", text)
        self.assertIn("施策実施後の年度着地予測", text)
        self.assertIn("残る不足分の修正稟議", text)
        self.assertIn("https://example.com/ringi", text)
        self.assertIn("件名: テスト", text)

    def test_measures_sufficient_asks_for_decision_not_ringi(self):
        text = self.render(1100, make_optimization())
        self.assertIn("施策の実施判断をお願いします", text)
        self.assertNotIn("修正稟議", text)

    def test_ok_message_has_no_optimization_or_ringi(self):
        text = self.render(5000, make_optimization())
        self.assertNotIn("修正稟議", text)
        self.assertNotIn("改善策", text)
        self.assertIn("年度着地予測", text)


if __name__ == "__main__":
    unittest.main()
