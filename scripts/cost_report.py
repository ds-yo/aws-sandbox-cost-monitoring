#!/usr/bin/env python3
"""月別AWS利用額をターミナルに表示する確認スクリプト。"""

import boto3
from datetime import date, timedelta


PROFILE = "sandbox-mfa"
MONTHS = 3  # 直近何ヶ月分を表示するか


def get_month_range(months: int) -> tuple[str, str]:
    """直近 n ヶ月の開始日と終了日を返す（YYYY-MM-DD形式）。"""
    today = date.today()
    end = today.replace(day=1)
    start = end
    for _ in range(months):
        start = (start - timedelta(days=1)).replace(day=1)
    return start.isoformat(), end.isoformat()


def fetch_costs(start: str, end: str) -> list[dict]:
    session = boto3.Session(profile_name=PROFILE, region_name="us-east-1")
    ce = session.client("ce")

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    return response["ResultsByTime"]


def display(results: list[dict]) -> None:
    for period in results:
        month = period["TimePeriod"]["Start"][:7]
        groups = period["Groups"]
        total = sum(float(g["Metrics"]["UnblendedCost"]["Amount"]) for g in groups)

        print(f"\n{'='*40}")
        print(f"  {month}  合計: ${total:.2f}")
        print(f"{'='*40}")

        sorted_groups = sorted(
            groups,
            key=lambda g: float(g["Metrics"]["UnblendedCost"]["Amount"]),
            reverse=True,
        )
        for g in sorted_groups:
            amount = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if amount < 0.01:
                continue
            service = g["Keys"][0]
            print(f"  {service:<45} ${amount:>8.2f}")


def main() -> None:
    start, end = get_month_range(MONTHS)
    print(f"取得期間: {start} 〜 {end}")
    results = fetch_costs(start, end)
    display(results)


if __name__ == "__main__":
    main()
