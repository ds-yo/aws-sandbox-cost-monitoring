#!/usr/bin/env python3
"""その月の予測結果を .claude/memory/forecast-history.json に追記する（追記専用）。

過去エントリは書き換えない。次回以降の予測で「過去の予測 vs 実績」の補正に使う。

使い方:
    .venv/bin/python scripts/record_forecast.py --month 2026-09 [--supersede]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / ".claude" / "memory" / "forecast-history.json"


def summarize_measures(opt: dict | None) -> list[dict]:
    """次月以降に実施状況を確認できるよう、施策と対象リソース ID を残す。"""
    if not opt:
        return []
    return [
        {
            "id": m["id"],
            "title": m["title"],
            "estimated_monthly_saving_usd": m["estimated_monthly_saving_usd"],
            "start_month": m["start_month"],
            "usage_types": m["usage_types"],
            "target_resource_ids": [t["id"] for t in m["target_resources"]],
        }
        for m in opt["measures"]
    ]


def build_entry(cost_data: dict, forecast: dict, judgement: dict | None, opt: dict | None = None) -> dict:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "fiscal_year": cost_data["fiscal_year"],
        "target_month": cost_data["target_month"],
        "is_month_complete": cost_data["is_month_complete"],
        "actual": {
            "target_month_usd": round(cost_data["target_month_usd"], 2),
            "fy_to_date_usd": round(cost_data["fy_to_date_usd"], 2),
        },
        "forecast": {
            "total_usd": forecast["forecast_total_usd"],
            "low_usd": forecast["forecast_low_usd"],
            "high_usd": forecast["forecast_high_usd"],
            "current_month_remaining_usd": forecast["current_month_remaining_usd"],
            "remaining_months_usd": forecast["remaining_months_usd"],
            "method": forecast["method"],
            "confidence": forecast["confidence"],
        },
        "aws_forecast_reference_usd": cost_data["aws_forecast_reference"].get("mean_usd"),
        "budget_usd": judgement["budget_usd"] if judgement else None,
        "status": judgement["status"] if judgement else None,
        "after_measures": (
            {
                "forecast_total_usd": round(judgement["forecast_after_usd"], 2),
                "fy_savings_usd": round(judgement["fy_savings_usd"], 2),
                "status": judgement["status_after"],
                "suggested_budget_usd": judgement["suggested_budget_usd"],
            }
            if judgement and "status_after" in judgement
            else None
        ),
        "proposed_measures": summarize_measures(opt),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", required=True)
    parser.add_argument("--supersede", action="store_true", help="同じ対象月の記録があっても追記する（再見積もり時）")
    args = parser.parse_args()

    out_dir = ROOT / "out" / args.month
    cost_data = json.loads((out_dir / "cost_data.json").read_text())
    forecast = json.loads((out_dir / "forecast.json").read_text())
    judgement_path = out_dir / "judgement.json"
    judgement = json.loads(judgement_path.read_text()) if judgement_path.exists() else None
    opt_path = out_dir / "optimization.json"
    opt = json.loads(opt_path.read_text()) if opt_path.exists() else None

    history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else {"entries": []}
    if any(e["target_month"] == args.month for e in history["entries"]) and not args.supersede:
        print(f"{args.month} は記録済みです。再見積もりを記録する場合は --supersede", file=sys.stderr)
        return 1

    entry = build_entry(cost_data, forecast, judgement, opt)
    if args.supersede:
        entry["supersedes_previous"] = True
    history["entries"].append(entry)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n")
    print(f"記録しました: {HISTORY_PATH}（{len(history['entries'])} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
