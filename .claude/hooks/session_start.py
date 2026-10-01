#!/usr/bin/env python3
"""SessionStart フック: 前回までのメモリ（progress.md・予測履歴・予算設定）を要約してコンテキストに注入する。

標準出力がセッションのコンテキストに追加される。
"""

import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))


def next_actions() -> str:
    path = ROOT / "progress.md"
    if not path.exists():
        return ""
    m = re.search(r"^## 次セッションの対応事項\n(.*?)(?=^## |\Z)", path.read_text(), re.S | re.M)
    return m.group(1).strip() if m else ""


def recent_forecasts(n: int = 3) -> list[str]:
    path = ROOT / ".claude" / "memory" / "forecast-history.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text()).get("entries", [])[-n:]
    return [
        f"- {e['target_month']}: 年度累計 ${e['actual']['fy_to_date_usd']:,.2f} / "
        f"予測 ${e['forecast']['total_usd']:,.2f}（{e['forecast']['low_usd']:,.0f}〜{e['forecast']['high_usd']:,.0f}）"
        f" / 予算 {e['budget_usd'] if e['budget_usd'] is not None else '-'} / 判定 {e['status']}"
        for e in entries
    ]


def budget_warnings() -> list[str]:
    path = ROOT / "config" / "budget.json"
    if not path.exists():
        return ["config/budget.json がありません"]
    conf = json.loads(path.read_text())
    warns = [
        f"{fy} の予算が未設定"
        for fy, c in conf.get("fiscal_years", {}).items()
        if not c.get("budget_usd") and not c.get("budget_jpy")
    ]
    if not conf.get("revision", {}).get("ringi_form_url"):
        warns.append("稟議フォーム URL（revision.ringi_form_url）が未設定")
    return warns


def main() -> None:
    lines = ["## aws-sandbox-cost-monitoring メモリ"]
    if actions := next_actions():
        lines += ["### 次セッションの対応事項（progress.md）", actions]
    if forecasts := recent_forecasts():
        lines += ["### 直近の予測履歴（forecast-history.json）", *forecasts]
    if warns := budget_warnings():
        lines += ["### 設定の注意", *[f"- {w}" for w in warns]]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
