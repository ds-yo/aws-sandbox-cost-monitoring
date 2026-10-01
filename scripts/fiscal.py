"""年度（4月開始・3月終了）計算ユーティリティ。

年度の呼称は開始年を使う（FY2026 = 2026-04-01 〜 2027-03-31）。
"""

from datetime import date, timedelta

FY_START_MONTH = 4


def fiscal_year_of(d: date) -> int:
    """日付が属する年度（開始年）を返す。"""
    return d.year if d.month >= FY_START_MONTH else d.year - 1


def fiscal_year_label(fy: int) -> str:
    return f"FY{fy}"


def fiscal_year_range(fy: int) -> tuple[date, date]:
    """年度の開始日と終了日（排他的 = 翌年度の開始日）を返す。"""
    return date(fy, FY_START_MONTH, 1), date(fy + 1, FY_START_MONTH, 1)


def add_months(d: date, months: int) -> date:
    """月初日に months ヶ月を加算した月初日を返す。"""
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def month_start(d: date) -> date:
    return d.replace(day=1)


def parse_month(s: str) -> date:
    """'YYYY-MM' を月初日に変換する。"""
    year, month = s.split("-")
    return date(int(year), int(month), 1)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def fiscal_months(fy: int) -> list[str]:
    """年度の12ヶ月を 'YYYY-MM' のリストで返す。"""
    start, _ = fiscal_year_range(fy)
    return [month_key(add_months(start, i)) for i in range(12)]


def elapsed_months(target_month: date) -> int:
    """年度開始から対象月までの経過月数（対象月を含む）。"""
    fy_start, _ = fiscal_year_range(fiscal_year_of(target_month))
    return (target_month.year - fy_start.year) * 12 + target_month.month - fy_start.month + 1


def default_target_month(today: date, closing_grace_days: int = 5) -> date:
    """デフォルトの対象月。

    月初 closing_grace_days 日以内なら前月（締め後の確定レポート）、
    それ以外は当月（月末時点の速報レポート）を返す。
    """
    if today.day <= closing_grace_days:
        return month_start(month_start(today) - timedelta(days=1))
    return month_start(today)
