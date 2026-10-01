# 年度額予測（LLM 見積もり）ルール

年度着地予測は LLM（Claude）が見積もる。AWS の `GetCostForecast` の値は **参考値** として使ってよいが、そのまま採用しない。

## 必ず参照する入力
1. `out/<YYYY-MM>/cost_data.json`（年度累計・月別推移・サービス別内訳・当月日次・AWS 予測参考値）
2. `out/<YYYY-MM>/cost_breakdown.json`・`inventory.json`（使用タイプ内訳とリソース。当月途中に作られたリソースの増加分を見落とさない）
3. `.claude/memory/forecast-history.json`（過去の予測値と実績。予測の偏りを補正する）
4. `.claude/contexts/cost-context.md`（既知のイベント・計画・一過性の費用）

## 見積もりの原則
- 年度予測 = **年度累計実績（`fy_to_date_usd`） + 当月の残り日数分（`current_month_remaining_usd`） + 残り月の予測合計**。累計実績を下回る予測は不正。
- **予算額を見ずに見積もる**（`cost_data.json` には予算を含めていない）。予算に引きずられた見積もりを避けるため、`config/budget.json` は予測確定後に scripts が参照する。
- 直近3ヶ月・6ヶ月のトレンドを両方見る。一過性の費用（年額サポート、Marketplace、RI/SP 前払い、検証用の一時リソース等）は月次ペースから除外して別途加算する。
- 当月が締まっていない（`is_month_complete: false`）場合、当月分は日次データから月末までを外挿する。
- 当月の途中に作られ、まだ1ヶ月分の課金が出ていないリソース（例: 月末に作られた Aurora・NAT Gateway）は、翌月以降の満額を見込んで加算する。
- 年度予測は **現状維持（改善策を実施しない）** 前提で出す。改善策の効果は `optimization.json` に分け、`slack_report.py` が差し引く。
- 過去の予測が実績に対して系統的に上振れ／下振れしていたら補正し、その旨を根拠に書く。
- 不確実性は **レンジ（low / high）** で表す。`low <= forecast <= high` を守る。
- 根拠（rationale）は Slack に載るので **3行以内・具体的な数値入り** で書く。「〜と思われる」だけの根拠は不可。

## 出力
`out/<YYYY-MM>/forecast.json` に以下のスキーマで書く（`scripts/validate_forecast.py` で検証される）:

```json
{
  "fiscal_year": "FY2026",
  "target_month": "2026-09",
  "forecast_total_usd": 1234.5,
  "forecast_low_usd": 1100.0,
  "forecast_high_usd": 1400.0,
  "current_month_remaining_usd": 0.0,
  "remaining_months_usd": {"2026-10": 100.0, "...": 0},
  "method": "直近3ヶ月平均 + 既知イベント加算",
  "rationale": ["根拠1", "根拠2"],
  "assumptions": ["前提1"],
  "confidence": "high | medium | low",
  "revision_reason": "予算超過見込みの場合のみ: 修正稟議に記載する増額理由（任意）"
}
```

- 予算との比較・判定（OK / 注意 / 超過）は LLM が行わず、`scripts/slack_report.py` が決定的に計算する。
