---
name: cost-report
description: AWS サンドボックスの月次コストレポートを作成して Slack に投稿する。Cost Explorer から当月・年度累計・内訳を取得し、LLM が年度着地額を予測、予算と比較して超過・注意なら「どのリソースがコストを使っているか」と改善策を提示し、不足分は修正稟議を促す。「コストレポート」「月次レポート」「AWS コスト確認」「年度予測」と言われたら使う。引数に対象月 YYYY-MM を渡せる。
---

# cost-report スキル（月次コストレポート）

引数: `$ARGUMENTS`（対象月 `YYYY-MM`。省略時は月初5日以内なら前月、それ以外は当月）
以下 `<M>` は対象月。各ステップが失敗したら次に進まず、原因を報告する。

## 1. データ取得
```bash
.venv/bin/python scripts/fetch_costs.py --month <M>       # 集計・月次推移・AWS予測参考値
.venv/bin/python scripts/fetch_breakdown.py --month <M>   # 使用タイプ・リージョン内訳
.venv/bin/python scripts/inventory.py --month <M>         # リソース棚卸し（読み取り専用）
```
- 認証エラー（ExpiredToken 等）の場合は `scripts/refresh-creds.sh` の実行をユーザーに依頼して止まる。
- 取得済みのファイルは再利用される（`--force` は CE 課金が発生するので必要時のみ）。

## 2. 年度着地額の予測（LLM・現状維持前提）
`.claude/rules/forecast.md` に従い `out/<M>/forecast.json` を書く。`config/budget.json` は **このステップでは読まない**。
保存時に PostToolUse フックが検証するので、エラーが出たら修正する。

## 3. 予算判定（dry-run）
```bash
.venv/bin/python scripts/slack_report.py --month <M>
```
- ✅ OK → 手順 5 へ。
- ⚠️ 注意 / 🚨 超過見込み → 手順 4 へ（🚨 で optimization.json が無いと終了コード 3 で止まるのは正常）。
- 予算未設定エラーなら、`config/budget.json` に設定すべき値をユーザーに確認して止まる。

## 4. コスト分析・改善策（⚠️ / 🚨 のみ）
1. `cost-optimization` スキルの手順で `out/<M>/optimization.json` を作る。
2. 手順 3 をもう一度実行し、`judgement.json` の `status_after`（施策実施後の判定）を確認する。
3. `status_after` が 🚨 なら `budget-revision` スキルで `out/<M>/ringi_draft.md` を作り、もう一度 dry-run して下書きが入ったことを確認する。

## 5. 投稿
- 対話セッション: dry-run の要点（当月額・年度累計・予測・判定・主な改善策・施策後の判定）をユーザーに提示し、了承を得てから `--send` を付けて実行する。
- 自動実行（`scripts/run_monthly.sh` から `AUTO_SEND=1` で起動された場合）: 確認なしで `--send` を実行してよい。
```bash
.venv/bin/python scripts/slack_report.py --month <M> --send
```

## 6. 記録（メモリ更新）
```bash
.venv/bin/python scripts/record_forecast.py --month <M>
```
- 予測と、提案した施策（対象リソース ID）が履歴に残り、翌月の実施状況チェックに使われる。
- 次回以降も効く知見（新しい定常費用、一過性費用など）があれば `.claude/contexts/cost-context.md` への追記を **提案** する。
- 対話セッションなら `progress.md` の該当タスクを更新する（自動実行時は編集しない）。

## 最終出力
対象月、当月額、年度累計、予測（レンジ）、判定（現状維持 → 施策後）、主な改善策の上位3件、投稿・記録の有無を報告する。
