#!/usr/bin/env python3
"""LLM が作成した forecast.json を cost_data.json と突き合わせて検証する。

PostToolUse フックからも呼ばれる。エラーがあれば終了コード 1 で内容を stderr に出す。

使い方:
    .venv/bin/python scripts/validate_forecast.py out/2026-09/forecast.json
"""

import json
import sys
from pathlib import Path

REQUIRED = {
    "fiscal_year": str,
    "target_month": str,
    "forecast_total_usd": (int, float),
    "forecast_low_usd": (int, float),
    "forecast_high_usd": (int, float),
    "current_month_remaining_usd": (int, float),
    "remaining_months_usd": dict,
    "method": str,
    "rationale": list,
    "assumptions": list,
    "confidence": str,
}
CONFIDENCE = {"high", "medium", "low"}
TOLERANCE_USD = 1.0  # 合計の突き合わせ誤差許容


def validate(forecast: dict, cost_data: dict) -> list[str]:
    errors: list[str] = []
    for key, typ in REQUIRED.items():
        if key not in forecast:
            errors.append(f"必須キー {key} がありません")
        elif not isinstance(forecast[key], typ) or isinstance(forecast[key], bool):
            errors.append(f"{key} の型が不正です")
    if errors:
        return errors

    if forecast["fiscal_year"] != cost_data["fiscal_year"]:
        errors.append(f"fiscal_year が cost_data と不一致: {forecast['fiscal_year']} != {cost_data['fiscal_year']}")
    if forecast["target_month"] != cost_data["target_month"]:
        errors.append(f"target_month が cost_data と不一致: {forecast['target_month']} != {cost_data['target_month']}")
    if forecast["confidence"] not in CONFIDENCE:
        errors.append(f"confidence は {sorted(CONFIDENCE)} のいずれか")

    low, mid, high = forecast["forecast_low_usd"], forecast["forecast_total_usd"], forecast["forecast_high_usd"]
    if not low <= mid <= high:
        errors.append(f"low <= forecast <= high を満たしていません: {low} / {mid} / {high}")

    ytd = cost_data["fy_to_date_usd"]
    if low < ytd - TOLERANCE_USD:
        errors.append(f"予測下限 {low:.2f} が年度累計実績 {ytd:.2f} を下回っています")

    expected_months = set(cost_data["remaining_months"])
    given_months = set(forecast["remaining_months_usd"])
    if given_months != expected_months:
        errors.append(
            f"remaining_months_usd の月が不一致: 不足 {sorted(expected_months - given_months)} / "
            f"余分 {sorted(given_months - expected_months)}"
        )
    elif any(not isinstance(v, (int, float)) or v < 0 for v in forecast["remaining_months_usd"].values()):
        errors.append("remaining_months_usd の値は 0 以上の数値")
    else:
        remaining = sum(forecast["remaining_months_usd"].values())
        current_rest = forecast["current_month_remaining_usd"]
        if cost_data["is_month_complete"] and abs(current_rest) > TOLERANCE_USD:
            errors.append("当月は確定済みなので current_month_remaining_usd は 0")
        if current_rest < 0:
            errors.append("current_month_remaining_usd は 0 以上")
        expected = ytd + current_rest + remaining
        if abs(mid - expected) > TOLERANCE_USD:
            errors.append(
                f"forecast_total_usd ({mid:.2f}) != 年度累計 ({ytd:.2f}) + 当月残り ({current_rest:.2f})"
                f" + 残り月合計 ({remaining:.2f}) = {expected:.2f}"
            )

    rationale = forecast["rationale"]
    if not 1 <= len(rationale) <= 3 or not all(isinstance(r, str) and r.strip() for r in rationale):
        errors.append("rationale は 1〜3 個の空でない文字列")
    elif not any(any(c.isdigit() for c in r) for r in rationale):
        errors.append("rationale に具体的な数値が含まれていません")

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    forecast_path = Path(sys.argv[1])
    cost_path = forecast_path.with_name("cost_data.json")
    try:
        forecast = json.loads(forecast_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"forecast.json を読めません: {e}", file=sys.stderr)
        return 1
    if not cost_path.exists():
        print(f"{cost_path} がありません。先に scripts/fetch_costs.py を実行してください", file=sys.stderr)
        return 1
    errors = validate(forecast, json.loads(cost_path.read_text()))
    if errors:
        print("forecast.json の検証エラー:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK: {forecast_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
