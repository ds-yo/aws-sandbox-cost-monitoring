#!/usr/bin/env python3
"""コスト消費元の内訳（サービス×使用タイプ、リージョン×サービス、リソース別）を取得する。

予算超過・注意判定時のコスト分析（.claude/rules/cost-optimization.md）に使う。
出力: out/<YYYY-MM>/cost_breakdown.json
API 呼び出し: GetCostAndUsage ×2 ＋ GetCostAndUsageWithResources ×1（未有効化ならスキップ）。

使い方:
    .venv/bin/python scripts/fetch_breakdown.py --month 2026-09 [--force]
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fetch_costs import METRIC, ce_client
from fiscal import add_months, month_key, parse_month

ROOT = Path(__file__).resolve().parent.parent
MIN_USD = 0.5  # これ未満の明細は捨てる
RESOURCE_LOOKBACK_DAYS = 14  # リソース単位データは直近14日のみ提供される
RESOURCE_TOP_SERVICES = 8


def _group_two(ce, start: date, end: date, dim1: str, dim2: str) -> dict[str, list[dict]]:
    """2軸 GroupBy の月次結果を {month: [{k1, k2, amount_usd}]} で返す。"""
    kwargs = {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": "MONTHLY",
        "Metrics": [METRIC],
        "GroupBy": [{"Type": "DIMENSION", "Key": dim1}, {"Type": "DIMENSION", "Key": dim2}],
    }
    out: dict[str, list[dict]] = {}
    while True:
        resp = ce.get_cost_and_usage(**kwargs)
        for period in resp["ResultsByTime"]:
            rows = out.setdefault(period["TimePeriod"]["Start"][:7], [])
            for g in period.get("Groups", []):
                amount = float(g["Metrics"][METRIC]["Amount"])
                rows.append({dim1.lower(): g["Keys"][0], dim2.lower(): g["Keys"][1], "amount_usd": amount})
        if not resp.get("NextPageToken"):
            return out
        kwargs["NextPageToken"] = resp["NextPageToken"]


def summarize_usage(rows_by_month: dict[str, list[dict]], target: str, prev: str) -> list[dict]:
    """サービス×使用タイプを当月降順に並べ、前月値を付ける（純粋関数）。"""
    prev_map = {(r["service"], r["usage_type"]): r["amount_usd"] for r in rows_by_month.get(prev, [])}
    rows = [
        {**r, "prev_month_usd": prev_map.get((r["service"], r["usage_type"]), 0.0)}
        for r in rows_by_month.get(target, [])
        if abs(r["amount_usd"]) >= MIN_USD
    ]
    return sorted(rows, key=lambda r: r["amount_usd"], reverse=True)


def fetch_resources(ce, services: list[str], today: date) -> dict:
    """リソース ID 単位のコスト（直近14日）。Cost Explorer の設定で有効化されていなければスキップ。"""
    start = today - timedelta(days=RESOURCE_LOOKBACK_DAYS - 1)
    kwargs = {
        "TimePeriod": {"Start": start.isoformat(), "End": today.isoformat()},
        "Granularity": "DAILY",
        "Metrics": [METRIC],
        "Filter": {"Dimensions": {"Key": "SERVICE", "Values": services}},
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
    }
    totals: dict[tuple[str, str], float] = {}
    try:
        while True:
            resp = ce.get_cost_and_usage_with_resources(**kwargs)
            for period in resp["ResultsByTime"]:
                for g in period.get("Groups", []):
                    key = (g["Keys"][0], g["Keys"][1])
                    totals[key] = totals.get(key, 0.0) + float(g["Metrics"][METRIC]["Amount"])
            if not resp.get("NextPageToken"):
                break
            kwargs["NextPageToken"] = resp["NextPageToken"]
    except Exception as e:  # noqa: BLE001 - 未有効化（DataUnavailable 等）でも分析は継続する
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}
    days = RESOURCE_LOOKBACK_DAYS
    rows = [
        {"service": s, "resource_id": r, "period_usd": v, "monthly_estimate_usd": v / days * 30}
        for (s, r), v in totals.items()
        if v >= MIN_USD
    ]
    return {
        "available": True,
        "period_start": start.isoformat(),
        "period_end_exclusive": today.isoformat(),
        "resources": sorted(rows, key=lambda r: r["period_usd"], reverse=True),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", required=True, help="対象月 YYYY-MM")
    parser.add_argument("--force", action="store_true", help="取得済みでも再取得する（CE API 課金に注意）")
    args = parser.parse_args()

    target = parse_month(args.month)
    out_path = ROOT / "out" / args.month / "cost_breakdown.json"
    if out_path.exists() and not args.force:
        print(f"取得済みのため再利用します: {out_path}（再取得は --force）")
        return 0

    today = date.today()
    prev = add_months(target, -1)
    end = min(add_months(target, 1), today)
    ce = ce_client()

    usage = _group_two(ce, prev, end, "SERVICE", "USAGE_TYPE")
    region = _group_two(ce, target, end, "REGION", "SERVICE")
    usage_rows = summarize_usage(usage, month_key(target), month_key(prev))

    top_services: list[str] = []
    for r in usage_rows:
        if r["service"] not in top_services and r["service"] != "Tax":
            top_services.append(r["service"])
    resources = fetch_resources(ce, top_services[:RESOURCE_TOP_SERVICES], today)

    region_rows = sorted(
        (r for r in region.get(month_key(target), []) if r["amount_usd"] >= MIN_USD),
        key=lambda r: r["amount_usd"],
        reverse=True,
    )
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_month": args.month,
        "usage_by_service": usage_rows,
        "region_by_service": region_rows,
        "resources_last_14_days": resources,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"保存しました: {out_path}")
    print(f"使用タイプ明細 {len(usage_rows)} 件 / リージョン明細 {len(region_rows)} 件 / "
          f"リソース別: {'取得' if resources['available'] else '未取得（' + resources['reason'][:80] + '）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
