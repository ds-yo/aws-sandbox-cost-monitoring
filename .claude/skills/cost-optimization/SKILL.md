---
name: cost-optimization
description: AWS サンドボックスで「どのサービス・リソースがコストを消費しているか」を特定し、予算内に収めるための改善策（削減見込み額・対象リソース・オーナー・リスク付き）を作成する。cost-report で予算超過・注意と判定されたとき、または「コスト削減」「何にお金がかかっている」「改善策」「無駄なリソース」と言われたときに使う。引数に対象月 YYYY-MM を渡せる。
---

# cost-optimization スキル（コスト消費元の特定と改善策）

引数: `$ARGUMENTS`（対象月 `YYYY-MM`。省略時は `out/` 内の最新月）
ルール: `.claude/rules/cost-optimization.md` に従う。**リソースの変更・削除は実行しない**（提案のみ）。

## 1. データ確認
`out/<M>/cost_breakdown.json` と `out/<M>/inventory.json` が無ければ取得する:
```bash
.venv/bin/python scripts/fetch_breakdown.py --month <M>
.venv/bin/python scripts/inventory.py --month <M>
```

## 2. 分析
1. `cost_breakdown.json` の `usage_by_service` を金額順に見て、上位の使用タイプ（Tax を除く）で月額の8割程度を説明できるまで消費元を洗い出す。
2. 各消費元について `inventory.json` から対象リソースを特定する。大きな JSON は Python ワンライナー（`.venv/bin/python -c`）で必要なキーだけ集計して読む。
   - 例: NAT Gateway ごとに、同じ VPC で稼働中の EC2 台数を数える。EIP は `associated: false` を数える。
3. `.claude/memory/forecast-history.json` に前月の `proposed_measures` があれば、対象リソース ID が今も残っているかで実施状況を判定する。
4. `.claude/contexts/cost-context.md` に「残す理由」が書かれたリソースは削減対象から外す。

## 3. 改善策の作成
- 削減額が大きく、リスクの低いものから並べる。1つの施策は「同じ種類のリソース × 同じ判断者」でまとめる。
- 対象リソースは ID・リージョン・`owner_hint` を全件書く（Slack には件数とオーナー名だけが載る）。
- 予算内に収まらない場合も、収まらないことを隠さない（`summary` に「施策を全部実施しても月 $X 不足」などと書く）。

`out/<M>/optimization.json` に書く。保存時に PostToolUse フックが `scripts/optimization.py` で検証するので、エラーが出たら直す。

## 4. 確認
```bash
.venv/bin/python scripts/slack_report.py --month <M>
```
`judgement.json` の `fy_savings_usd`・`forecast_after_usd`・`status_after` を見て、施策の効果を報告する。
対話セッションなら、オーナー別の対象リソース一覧（表）もユーザーに提示する。
