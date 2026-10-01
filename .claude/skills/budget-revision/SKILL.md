---
name: budget-revision
description: AWS 年度予算の修正稟議の下書きを作成する。cost-report で「改善策を実施しても予算超過見込み」と判定されたとき、または「修正稟議」「予算増額」「稟議の下書き」と言われたときに使う。引数に対象月 YYYY-MM を渡せる。
---

# budget-revision スキル（修正稟議の下書き）

引数: `$ARGUMENTS`（対象月 `YYYY-MM`。省略時は `out/` 内の最新月）

## 前提
- `out/<M>/cost_data.json`・`forecast.json`・`optimization.json`・`judgement.json` が揃っていること（無ければ先に `cost-report` スキルを手順 4 まで実行する）。
- 修正稟議は **改善策を実施しても残る不足分** を対象とする（`judgement.json` の `status_after` が `over` のとき）。`status_after` が `over` でなければ稟議は不要と報告して終わる。
- 金額は `judgement.json` の値（`budget_usd` / `forecast_after_usd` / `diff_after_usd` / `fy_savings_usd` / `suggested_budget_usd`）をそのまま使い、**LLM が数値を作り直さない**。

## 手順
1. 上記ファイルと `.claude/contexts/cost-context.md` を読む。
2. 増額理由を、使用タイプ・サービス別の推移と既知イベントから特定する。推測で理由を作らない。データで説明できない部分は「要確認」と書く。
3. 下記テンプレートで `out/<M>/ringi_draft.md` を書く（Slack に載るので **2,500 文字以内**、Markdown 見出しは使わない）。
4. 対話セッションなら下書きをユーザーに見せる。稟議システムへの登録は人が行う（Claude は登録しない）。

## テンプレート
```
件名: AWS サンドボックス環境 <FY> 年度予算の修正について
現予算: $<budget_usd>
修正後予算（案）: $<suggested_budget_usd>（増額 $<suggested_budget_usd - budget_usd>）
年度着地予測: 現状維持 $<forecast_total_usd> → 改善策実施後 $<forecast_after_usd>（<M> 時点）
年度累計実績: $<fy_to_date_usd>（<経過月>/12ヶ月）

増額理由:
1. <使用タイプ／サービス>: <具体的な数値を伴う理由>
2. ...

実施するコスト抑制策（年度内削減見込み $<fy_savings_usd>）:
- [M1] <施策名>: -$<月額>/月（<開始月>〜）
- ...

要確認事項:
- <データだけでは判断できない点。無ければ「なし」>
```
