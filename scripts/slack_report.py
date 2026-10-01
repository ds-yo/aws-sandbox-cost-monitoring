#!/usr/bin/env python3
"""cost_data.json・forecast.json・optimization.json・config/budget.json から Slack レポートを組み立てて投稿する。

予算判定（OK / 注意 / 超過見込み）と施策実施後の着地予測はここで決定的に計算する（LLM には判定させない）。
方針: 超過・注意時はまず「どこがコストを使っているか」と改善策を提示し、
改善策を実施しても残る不足分についてのみ修正稟議を依頼する。
既定は dry-run（標準出力にプレビュー）。--send を付けたときだけ Slack に投稿する。

使い方:
    .venv/bin/python scripts/slack_report.py --month 2026-09            # dry-run
    .venv/bin/python scripts/slack_report.py --month 2026-09 --send     # 投稿
"""

import argparse
import json
import math
import os
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from fiscal import elapsed_months, parse_month
from optimization import driver_amounts, effective_months, fy_savings
from optimization import validate as validate_optimization
from validate_forecast import validate as validate_forecast

ROOT = Path(__file__).resolve().parent.parent
BUDGET_PATH = ROOT / "config" / "budget.json"
SECTION_TEXT_LIMIT = 2900  # Slack section block の上限 3000 文字に余裕を持たせる
TOP_DRIVERS = 5
TOP_MEASURES = 6

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_OVER = "over"
STATUS_LABEL = {
    STATUS_OK: "✅ 予算内の見込み",
    STATUS_WARN: "⚠️ 注意（予測上限が予算超過）",
    STATUS_OVER: "🚨 予算超過見込み",
}
RISK_LABEL = {"low": "低", "medium": "中", "high": "高"}


@dataclass(frozen=True)
class Judgement:
    status: str
    budget_usd: float
    diff_usd: float  # 予測値 - 予算（正なら超過）
    consumption_ratio: float  # 年度累計 / 予算
    required_monthly_avg_usd: float  # 予算内に収めるための残り月の平均月額上限
    fy_savings_usd: float  # 改善策の年度内削減額（税込）
    forecast_after_usd: float
    high_after_usd: float
    status_after: str
    diff_after_usd: float
    suggested_budget_usd: float | None  # 改善策実施後もなお超過する場合のみ


def resolve_budget_usd(fy_conf: dict) -> float:
    if "budget_usd" in fy_conf:
        return float(fy_conf["budget_usd"])
    if "budget_jpy" in fy_conf and "fx_jpy_per_usd" in fy_conf:
        return float(fy_conf["budget_jpy"]) / float(fy_conf["fx_jpy_per_usd"])
    raise ValueError("budget_usd、または budget_jpy + fx_jpy_per_usd を設定してください")


def classify(mid: float, high: float, budget: float) -> str:
    if mid > budget:
        return STATUS_OVER
    if high > budget:
        return STATUS_WARN
    return STATUS_OK


def suggest_budget(mid: float, high: float, buffer_ratio: float, round_to: float) -> float:
    return math.ceil(max(high, mid * (1 + buffer_ratio)) / round_to) * round_to


def judge(cost_data: dict, forecast: dict, budget_conf: dict, opt: dict | None = None) -> Judgement:
    fy_conf = budget_conf["fiscal_years"].get(cost_data["fiscal_year"])
    if fy_conf is None:
        raise ValueError(f"config/budget.json に {cost_data['fiscal_year']} の予算がありません")
    budget = resolve_budget_usd(fy_conf)
    if budget <= 0:
        raise ValueError(f"{cost_data['fiscal_year']} の予算が未設定（0 以下）です")

    mid, high = forecast["forecast_total_usd"], forecast["forecast_high_usd"]
    remaining = cost_data["remaining_months"]
    savings = fy_savings(opt, remaining, budget_conf.get("tax_rate", 0.1)) if opt else 0.0
    mid_after, high_after = mid - savings, high - savings
    status_after = classify(mid_after, high_after, budget)

    left = budget - cost_data["fy_to_date_usd"] - forecast["current_month_remaining_usd"]
    revision = budget_conf.get("revision", {})
    return Judgement(
        status=classify(mid, high, budget),
        budget_usd=budget,
        diff_usd=mid - budget,
        consumption_ratio=cost_data["fy_to_date_usd"] / budget,
        required_monthly_avg_usd=left / len(remaining) if remaining else left,
        fy_savings_usd=savings,
        forecast_after_usd=mid_after,
        high_after_usd=high_after,
        status_after=status_after,
        diff_after_usd=mid_after - budget,
        suggested_budget_usd=(
            suggest_budget(mid_after, high_after, revision.get("buffer_ratio", 0.1), revision.get("round_to_usd", 100))
            if status_after == STATUS_OVER
            else None
        ),
    )


def _usd(v: float) -> str:
    return f"{'-' if v < 0 else ''}${abs(v):,.2f}"


def _signed_usd(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _pct_change(cur: float, prev: float) -> str:
    if prev <= 0:
        return "前月比 -"
    return f"前月比 {(cur - prev) / prev * 100:+.1f}%"


def _section(text: str) -> dict:
    if len(text) > SECTION_TEXT_LIMIT:
        text = text[: SECTION_TEXT_LIMIT - 1] + "…"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _owners(measure: dict, limit: int = 5) -> str:
    hints = list(dict.fromkeys(t.get("owner_hint") for t in measure["target_resources"] if t.get("owner_hint")))
    if not hints:
        return ""
    return "、".join(hints[:limit]) + (f" ほか{len(hints) - limit}名" if len(hints) > limit else "")


def optimization_blocks(cost_data: dict, opt: dict, breakdown: dict, j: Judgement, remaining: list[str]) -> list[dict]:
    """コスト消費元・改善策・施策実施後の着地予測（純粋関数）。"""
    blocks: list[dict] = [{"type": "divider"}]

    drivers = driver_amounts(opt, breakdown)[:TOP_DRIVERS]
    lines = [f"• *{d['title']}* {_usd(d['monthly_usd'])}/月 — {_short(d['finding'], 90)}" for d in drivers]
    blocks.append(_section(f"*🔍 コスト消費元 Top{len(drivers)}（{cost_data['target_month']} 実績）*\n" + "\n".join(lines)))

    measures = sorted(opt["measures"], key=lambda m: m["estimated_monthly_saving_usd"], reverse=True)
    monthly_total = sum(m["estimated_monthly_saving_usd"] for m in measures)
    lines = []
    for m in measures[:TOP_MEASURES]:
        owners = _owners(m)
        lines.append(
            f"• *[{m['id']}] {m['title']}* -{_usd(m['estimated_monthly_saving_usd'])}/月"
            f"（{m['start_month']}〜 {effective_months(m['start_month'], remaining)}ヶ月・リスク{RISK_LABEL[m['risk']]}）\n"
            f"    対象 {len(m['target_resources'])}件{'（' + owners + '）' if owners else ''}／判断: {m['decision_by']}"
        )
    if len(measures) > TOP_MEASURES:
        lines.append(f"…ほか {len(measures) - TOP_MEASURES} 件")
    blocks.append(
        _section(
            f"*🛠 改善策（削減見込み {_usd(monthly_total)}/月・年度内 {_usd(j.fy_savings_usd)} 税込）*\n" + "\n".join(lines)
        )
    )

    if prev := opt.get("previous_measures_status"):
        mark = {"done": "✅", "partial": "🔶", "not_done": "❌", "unknown": "❔"}
        lines = [f"• {mark[p['status']]} [{p['id']}] {p.get('title', '')} {p.get('note', '')}" for p in prev]
        blocks.append(_section("*前回提案した施策の実施状況*\n" + "\n".join(lines)))

    blocks.append(
        _section(
            f"*施策実施後の年度着地予測* {_usd(j.forecast_after_usd)}（上限 {_usd(j.high_after_usd)}）\n"
            f"予算差額 {_signed_usd(j.diff_after_usd)} → *{STATUS_LABEL[j.status_after]}*\n"
            f"参考: 予算内に収めるには残り{len(remaining)}ヶ月の月額を平均 *{_usd(j.required_monthly_avg_usd)}* 以下にする必要があります"
            f"（{cost_data['target_month']} 実績 {_usd(cost_data['target_month_usd'])}）"
        )
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _short(opt["summary"], 300)}]})
    return blocks


def action_blocks(forecast: dict, j: Judgement, budget_conf: dict, has_opt: bool, ringi_draft: str | None) -> list[dict]:
    revision = budget_conf.get("revision", {})
    mentions = " ".join(revision.get("mentions", []))
    blocks: list[dict] = [{"type": "divider"}]

    if j.status_after == STATUS_OVER:
        lead = (
            f"🚨 {mentions} *改善策の実施判断と、残る不足分の修正稟議をお願いします*\n"
            f"改善策を実施しても年度着地が予算を *{_usd(j.diff_after_usd)}* 超過する見込みです。\n"
            if has_opt
            else f"🚨 {mentions} *修正稟議の作成をお願いします*\n年度着地予測が予算を *{_usd(j.diff_after_usd)}* 超過する見込みです。\n"
        )
        blocks.append(
            _section(
                lead
                + f"推奨修正後予算: *{_usd(j.suggested_budget_usd)}*（現予算 {_usd(j.budget_usd)}"
                + ("・改善策の実施が前提" if has_opt else "")
                + "）"
                + (f"\n増額理由（案）: {forecast['revision_reason']}" if forecast.get("revision_reason") else "")
            )
        )
        if revision.get("ringi_form_url"):
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "danger",
                            "text": {"type": "plain_text", "text": "修正稟議を作成する"},
                            "url": revision["ringi_form_url"],
                        }
                    ],
                }
            )
        if ringi_draft:
            blocks.append(_section("*稟議下書き*\n```" + ringi_draft.strip() + "```"))
    elif j.status != STATUS_OK and has_opt:
        tail = "（予測上限では超過の可能性があるため、来月も推移を確認します）" if j.status_after == STATUS_WARN else ""
        blocks.append(
            _section(f"🛠 {mentions} *改善策を実施すれば予算内に収まる見込みです。施策の実施判断をお願いします*{tail}")
        )
    elif j.status == STATUS_WARN:
        blocks.append(
            _section("⚠️ 予測上限が予算を超えています。来月も同様の傾向であれば改善策の検討・修正稟議を検討してください。")
        )
    return blocks if len(blocks) > 1 else []


def build_message(
    cost_data: dict,
    forecast: dict,
    j: Judgement,
    budget_conf: dict,
    opt: dict | None = None,
    breakdown: dict | None = None,
    ringi_draft: str | None = None,
) -> dict:
    """Slack Incoming Webhook 用ペイロード（純粋関数）。"""
    month = cost_data["target_month"]
    year, mon = month.split("-")
    state = "確定" if cost_data["is_month_complete"] else f"速報・{cost_data['data_through']} まで"
    elapsed = elapsed_months(parse_month(month))
    top_n = budget_conf.get("slack", {}).get("top_services", 5)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 AWS サンドボックス コストレポート {year}年{int(mon)}月（{state}）"},
        },
        _section(
            f"*当月利用額* {_usd(cost_data['target_month_usd'])}"
            f"（{_pct_change(cost_data['target_month_usd'], cost_data['prev_month_usd'])}）"
        ),
        _section(
            f"*{cost_data['fiscal_year']} 年度累計*（{elapsed}/12ヶ月経過） {_usd(cost_data['fy_to_date_usd'])}\n"
            f"予算 {_usd(j.budget_usd)} ／ 消化率 {j.consumption_ratio * 100:.1f}%"
            f"（時間按分の目安 {elapsed / 12 * 100:.1f}%）"
        ),
        _section(
            f"*年度着地予測（LLM 見積もり・現状維持の場合）* {_usd(forecast['forecast_total_usd'])}\n"
            f"レンジ {_usd(forecast['forecast_low_usd'])} 〜 {_usd(forecast['forecast_high_usd'])}"
            f"（確度: {forecast['confidence']}）\n"
            f"予算差額 {_signed_usd(j.diff_usd)} → *{STATUS_LABEL[j.status]}*"
        ),
    ]

    top = cost_data["top_services_target_month"][:top_n]
    if top:
        lines = [
            f"• {s['service']}: {_usd(s['amount_usd'])}（{_pct_change(s['amount_usd'], s['prev_month_usd'])}）"
            for s in top
        ]
        blocks.append(_section(f"*サービス別 Top{len(top)}*\n" + "\n".join(lines)))

    blocks.append(_section("*予測根拠*\n" + "\n".join(f"• {r}" for r in forecast["rationale"])))
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"手法: {forecast['method']}"}]})

    if j.status != STATUS_OK and opt and breakdown:
        blocks += optimization_blocks(cost_data, opt, breakdown, j, cost_data["remaining_months"])
    blocks += action_blocks(forecast, j, budget_conf, bool(opt), ringi_draft)

    fallback = (
        f"AWS コストレポート {month}: 当月 {_usd(cost_data['target_month_usd'])} / "
        f"年度予測 {_usd(forecast['forecast_total_usd'])} / {STATUS_LABEL[j.status]}"
    )
    return {"text": fallback, "blocks": blocks}


def get_webhook_url() -> str:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if url:
        return url
    secret_id = os.environ.get("SLACK_WEBHOOK_SECRET_ID")
    if secret_id:
        import boto3

        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sandbox-mfa"))
        sm = session.client("secretsmanager", region_name="ap-northeast-1")
        return sm.get_secret_value(SecretId=secret_id)["SecretString"].strip()
    raise RuntimeError("SLACK_WEBHOOK_URL または SLACK_WEBHOOK_SECRET_ID を設定してください")


def post(payload: dict) -> None:
    req = urllib.request.Request(
        get_webhook_url(),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Slack 投稿失敗: HTTP {resp.status}")


def _load_optional(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", required=True, help="対象月 YYYY-MM")
    parser.add_argument("--send", action="store_true", help="Slack に投稿する（省略時は dry-run）")
    parser.add_argument("--resend", action="store_true", help="投稿済みでも再投稿する")
    args = parser.parse_args()

    out_dir = ROOT / "out" / args.month
    cost_data = json.loads((out_dir / "cost_data.json").read_text())
    forecast = json.loads((out_dir / "forecast.json").read_text())
    if errors := validate_forecast(forecast, cost_data):
        print("forecast.json が不正なため中止します:\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1

    breakdown = _load_optional(out_dir / "cost_breakdown.json")
    opt = _load_optional(out_dir / "optimization.json")
    if opt is not None:
        if breakdown is None:
            print("optimization.json がありますが cost_breakdown.json がありません", file=sys.stderr)
            return 1
        if errors := validate_optimization(opt, cost_data, breakdown):
            print("optimization.json が不正なため中止します:\n  - " + "\n  - ".join(errors), file=sys.stderr)
            return 1

    budget_conf = json.loads(BUDGET_PATH.read_text())
    try:
        j = judge(cost_data, forecast, budget_conf, opt)
    except ValueError as e:
        print(f"予算設定エラー: {e}", file=sys.stderr)
        return 1

    (out_dir / "judgement.json").write_text(
        json.dumps({**asdict(j), "fiscal_year": cost_data["fiscal_year"]}, ensure_ascii=False, indent=2)
    )
    if j.status == STATUS_OVER and opt is None:
        print(
            "予算超過見込みです。改善策の提示が必須のため、cost-optimization スキルで optimization.json を作成してください"
            "（judgement.json は出力済み）",
            file=sys.stderr,
        )
        return 3

    draft_path = out_dir / "ringi_draft.md"
    ringi_draft = draft_path.read_text() if draft_path.exists() else None
    if j.status_after == STATUS_OVER and ringi_draft is None:
        print("注意: 改善策実施後も超過見込みですが ringi_draft.md がありません（budget-revision スキルで作成）", file=sys.stderr)

    payload = build_message(cost_data, forecast, j, budget_conf, opt, breakdown, ringi_draft)

    if not args.send:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(
            f"\n[dry-run] 判定: {STATUS_LABEL[j.status]} → 施策実施後: {STATUS_LABEL[j.status_after]}（投稿するには --send）",
            file=sys.stderr,
        )
        return 0

    sent_marker = out_dir / "slack_sent.json"
    if sent_marker.exists() and not args.resend:
        print(f"投稿済みです（{sent_marker}）。再投稿は --resend", file=sys.stderr)
        return 1
    post(payload)
    sent_marker.write_text(json.dumps({"sent_at": datetime.now(timezone.utc).isoformat(), "status": j.status}))
    print(f"Slack に投稿しました: {STATUS_LABEL[j.status]} → 施策実施後: {STATUS_LABEL[j.status_after]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
