#!/usr/bin/env python3
"""LLM が作成した optimization.json（コスト消費元と改善策）の検証と、施策効果の決定的な計算。

- validate(): スキーマ・cost_breakdown.json との整合性チェック（PostToolUse フックからも呼ばれる）
- driver_amounts(): コスト消費元の金額を cost_breakdown.json から計算（LLM の数値は使わない）
- fy_savings(): 施策の年度内削減額 = Σ 月額削減 × 実施月〜年度末の月数 × (1 + 税率)

使い方:
    .venv/bin/python scripts/optimization.py out/2026-09/optimization.json
"""

import json
import sys
from pathlib import Path

LEVELS = {"low", "medium", "high"}
PREV_STATUS = {"done", "partial", "not_done", "unknown"}
RAMP_UP_TOLERANCE = 1.1  # 当月実績を超える削減額は ramp_up（当月途中から発生したコスト）の場合のみ許可


def usage_cost(breakdown: dict, usage_types: list[str]) -> float:
    rows = breakdown["usage_by_service"]
    return sum(r["amount_usd"] for r in rows if r["usage_type"] in usage_types)


def driver_amounts(opt: dict, breakdown: dict) -> list[dict]:
    """cost_drivers に当月実績額を付けて降順に返す（純粋関数）。"""
    rows = [{**d, "monthly_usd": usage_cost(breakdown, d["usage_types"])} for d in opt["cost_drivers"]]
    return sorted(rows, key=lambda d: d["monthly_usd"], reverse=True)


def effective_months(start_month: str, remaining_months: list[str]) -> int:
    return sum(1 for m in remaining_months if m >= start_month)


def fy_savings(opt: dict, remaining_months: list[str], tax_rate: float) -> float:
    return sum(
        m["estimated_monthly_saving_usd"] * effective_months(m["start_month"], remaining_months) * (1 + tax_rate)
        for m in opt["measures"]
    )


def validate(opt: dict, cost_data: dict, breakdown: dict) -> list[str]:
    errors: list[str] = []
    for key, typ in {"fiscal_year": str, "target_month": str, "cost_drivers": list, "measures": list, "summary": str}.items():
        if not isinstance(opt.get(key), typ):
            errors.append(f"{key} がない、または型が不正です")
    if errors:
        return errors
    if opt["fiscal_year"] != cost_data["fiscal_year"] or opt["target_month"] != cost_data["target_month"]:
        errors.append("fiscal_year / target_month が cost_data.json と不一致")

    known = {r["usage_type"] for r in breakdown["usage_by_service"]}

    for i, d in enumerate(opt["cost_drivers"]):
        label = f"cost_drivers[{i}]"
        if not d.get("title") or not d.get("finding"):
            errors.append(f"{label}: title と finding は必須")
        if unknown := [u for u in d.get("usage_types", []) if u not in known]:
            errors.append(f"{label}: cost_breakdown.json に無い使用タイプ {unknown}")
        if not d.get("usage_types"):
            errors.append(f"{label}: usage_types は必須")

    ids = [m.get("id") for m in opt["measures"]]
    if len(ids) != len(set(ids)):
        errors.append("measures の id が重複しています")
    remaining = cost_data["remaining_months"]
    for m in opt["measures"]:
        label = f"measures[{m.get('id')}]"
        for key in ("id", "title", "action", "saving_basis", "decision_by"):
            if not isinstance(m.get(key), str) or not m[key].strip():
                errors.append(f"{label}: {key} は必須の文字列")
        saving = m.get("estimated_monthly_saving_usd")
        if not isinstance(saving, (int, float)) or isinstance(saving, bool) or saving <= 0:
            errors.append(f"{label}: estimated_monthly_saving_usd は正の数値")
            continue
        if m.get("start_month") not in remaining:
            errors.append(f"{label}: start_month は年度内の残り月 {remaining[0] if remaining else '-'}〜 のいずれか")
        for key in ("effort", "risk"):
            if m.get(key) not in LEVELS:
                errors.append(f"{label}: {key} は {sorted(LEVELS)} のいずれか")
        if not any(c.isdigit() for c in m.get("saving_basis", "")):
            errors.append(f"{label}: saving_basis に計算根拠の数値がありません")
        targets = m.get("target_resources")
        if not isinstance(targets, list) or not targets or not all(isinstance(t, dict) and t.get("id") for t in targets):
            errors.append(f"{label}: target_resources に対象リソース（id 必須）を1件以上")
        usage_types = m.get("usage_types") or []
        if not usage_types:
            errors.append(f"{label}: usage_types は必須")
        elif unknown := [u for u in usage_types if u not in known]:
            errors.append(f"{label}: cost_breakdown.json に無い使用タイプ {unknown}")
        else:
            actual = usage_cost(breakdown, usage_types)
            if saving > actual * RAMP_UP_TOLERANCE and not m.get("ramp_up"):
                errors.append(
                    f"{label}: 削減額 ${saving:.2f} が対象使用タイプの当月実績 ${actual:.2f} を超えています"
                    "（当月途中に発生したコストなら ramp_up: true と根拠を記載）"
                )

    for p in opt.get("previous_measures_status", []):
        if p.get("status") not in PREV_STATUS:
            errors.append(f"previous_measures_status[{p.get('id')}]: status は {sorted(PREV_STATUS)} のいずれか")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        opt = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"optimization.json を読めません: {e}", file=sys.stderr)
        return 1
    try:
        cost_data = json.loads(path.with_name("cost_data.json").read_text())
        breakdown = json.loads(path.with_name("cost_breakdown.json").read_text())
    except OSError as e:
        print(f"{e.filename} がありません。先に fetch_costs.py / fetch_breakdown.py を実行してください", file=sys.stderr)
        return 1
    errors = validate(opt, cost_data, breakdown)
    if errors:
        print("optimization.json の検証エラー:\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
