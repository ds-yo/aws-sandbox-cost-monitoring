#!/usr/bin/env python3
"""Cost Explorer から月次レポート・年度予測に必要なデータを取得し JSON に保存する。

出力: out/<YYYY-MM>/cost_data.json
API 呼び出しは GetCostAndUsage ×2（月次サービス別・当月日次）＋ GetCostForecast ×1。

使い方:
    .venv/bin/python scripts/fetch_costs.py [--month YYYY-MM] [--force]
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3

from fiscal import (
    add_months,
    default_target_month,
    elapsed_months,
    fiscal_months,
    fiscal_year_label,
    fiscal_year_of,
    fiscal_year_range,
    month_key,
    parse_month,
)

ROOT = Path(__file__).resolve().parent.parent
METRIC = "UnblendedCost"
HISTORY_MONTHS = 12  # 対象月より前に遡る月数（前年同月まで）
TOP_N = 10


def ce_client():
    profile = os.environ.get("AWS_PROFILE", "sandbox-mfa")
    session = boto3.Session(profile_name=profile)
    return session.client("ce", region_name="us-east-1")


def _paginate(ce, **kwargs) -> list[dict]:
    results: list[dict] = []
    while True:
        resp = ce.get_cost_and_usage(**kwargs)
        results.extend(resp["ResultsByTime"])
        token = resp.get("NextPageToken")
        if not token:
            return results
        kwargs["NextPageToken"] = token


def fetch_monthly_by_service(ce, start: date, end: date) -> list[dict]:
    raw = _paginate(
        ce,
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=[METRIC],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    # ページングで同じ月が分割されることがあるので月単位でマージする
    merged: dict[str, dict] = {}
    for period in raw:
        month = period["TimePeriod"]["Start"][:7]
        entry = merged.setdefault(month, {"month": month, "estimated": period.get("Estimated", False), "services": {}})
        for g in period.get("Groups", []):
            amount = float(g["Metrics"][METRIC]["Amount"])
            name = g["Keys"][0]
            entry["services"][name] = entry["services"].get(name, 0.0) + amount
    for entry in merged.values():
        entry["total_usd"] = sum(entry["services"].values())
    return [merged[k] for k in sorted(merged)]


def fetch_daily_total(ce, start: date, end: date) -> list[dict]:
    raw = _paginate(
        ce,
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="DAILY",
        Metrics=[METRIC],
    )
    return [
        {"date": p["TimePeriod"]["Start"], "amount_usd": float(p["Total"][METRIC]["Amount"])}
        for p in raw
    ]


def fetch_aws_forecast(ce, start: date, end: date) -> dict:
    """AWS 自身の予測（参考値）。データ不足等で失敗しても処理は継続する。"""
    if start >= end:
        return {"available": False, "reason": "年度末を過ぎているため予測対象期間なし"}
    try:
        resp = ce.get_cost_forecast(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            PredictionIntervalLevel=80,
        )
    except Exception as e:  # noqa: BLE001 - 参考値なので失敗理由を残して継続
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}
    return {
        "available": True,
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "mean_usd": float(resp["Total"]["Amount"]),
        "by_month": [
            {
                "month": r["TimePeriod"]["Start"][:7],
                "mean_usd": float(r["MeanValue"]),
                "low_usd": float(r["PredictionIntervalLowerBound"]),
                "high_usd": float(r["PredictionIntervalUpperBound"]),
            }
            for r in resp["ForecastResultsByTime"]
        ],
    }


def build_summary(target: date, today: date, monthly: list[dict], daily: list[dict], aws_forecast: dict) -> dict:
    """取得データから集計値を作る（純粋関数）。"""
    fy = fiscal_year_of(target)
    fy_month_keys = fiscal_months(fy)
    by_month = {m["month"]: m for m in monthly}
    target_key = month_key(target)
    prev_key = month_key(add_months(target, -1))
    yoy_key = month_key(add_months(target, -12))

    fy_to_date = [by_month[k] for k in fy_month_keys if k <= target_key and k in by_month]
    target_entry = by_month.get(target_key, {"services": {}, "total_usd": 0.0})
    prev_entry = by_month.get(prev_key, {"services": {}, "total_usd": 0.0})

    top = sorted(target_entry["services"].items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    next_month = add_months(target, 1)
    is_complete = today >= next_month
    data_through = min(today, next_month) - timedelta(days=1)

    return {
        "fiscal_year": fiscal_year_label(fy),
        "fiscal_year_months": fy_month_keys,
        "target_month": target_key,
        "is_month_complete": is_complete,
        "data_through": data_through.isoformat(),
        "elapsed_months": elapsed_months(target),
        "remaining_months": [k for k in fy_month_keys if k > target_key],
        "target_month_usd": target_entry["total_usd"],
        "prev_month_usd": prev_entry["total_usd"],
        "same_month_last_year_usd": by_month.get(yoy_key, {}).get("total_usd"),
        "fy_to_date_usd": sum(m["total_usd"] for m in fy_to_date),
        "fy_to_date_by_month": [{"month": m["month"], "total_usd": m["total_usd"]} for m in fy_to_date],
        "top_services_target_month": [
            {"service": name, "amount_usd": amt, "prev_month_usd": prev_entry["services"].get(name, 0.0)}
            for name, amt in top
        ],
        "monthly_history": monthly,
        "target_month_daily": daily,
        "aws_forecast_reference": aws_forecast,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", help="対象月 YYYY-MM（省略時: 月初5日以内なら前月、それ以外は当月）")
    parser.add_argument("--force", action="store_true", help="取得済みでも再取得する（CE API 課金に注意）")
    args = parser.parse_args()

    today = date.today()
    target = parse_month(args.month) if args.month else default_target_month(today)
    out_path = ROOT / "out" / month_key(target) / "cost_data.json"
    if out_path.exists() and not args.force:
        print(f"取得済みのため再利用します: {out_path}（再取得は --force）")
        return 0

    if target >= today:
        print(f"対象月 {month_key(target)} のデータはまだありません（本日 {today}）", file=sys.stderr)
        return 1

    _, fy_end = fiscal_year_range(fiscal_year_of(target))
    end = min(add_months(target, 1), today)

    ce = ce_client()
    monthly = fetch_monthly_by_service(ce, add_months(target, -HISTORY_MONTHS), end)
    daily = fetch_daily_total(ce, target, end)
    aws_forecast = fetch_aws_forecast(ce, today, fy_end)

    summary = build_summary(target, today, monthly, daily, aws_forecast)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"保存しました: {out_path}")
    print(
        f"{summary['fiscal_year']} {summary['target_month']}: 当月 ${summary['target_month_usd']:,.2f} / "
        f"年度累計 ${summary['fy_to_date_usd']:,.2f}（{summary['elapsed_months']}/12ヶ月, "
        f"{'確定' if summary['is_month_complete'] else '速報'}）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
