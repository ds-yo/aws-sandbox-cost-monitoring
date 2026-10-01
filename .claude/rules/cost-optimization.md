# コスト分析・改善策ルール

## 基本方針
- 予算判定が **⚠️ 注意 / 🚨 超過見込み** のとき、修正稟議より先に **「どのサービス・リソースがコストを使っているか」と「予算内に収めるための改善策」** を提示する。
- 修正稟議は **改善策を実施しても残る不足分** についてのみ依頼する（推奨額は施策実施後の予測から `slack_report.py` が計算）。
- Claude は改善策を **提案するだけ**。リソースの停止・削除・変更は実行しない（`aws-access.md` の読み取り専用ルール）。実施はリソースのオーナーが判断する。

## 分析の手順
1. `out/<M>/cost_breakdown.json` の使用タイプ（例: `APN1-NatGateway-Hours`）で金額の大きい順に消費元を特定する。
2. `out/<M>/inventory.json` で使用タイプを具体的なリソース ID に結び付ける。オーナーは VPC 名・Name タグ・ユーザー名から推定し、`owner_hint` に書く（推定であることを前提に扱う）。
3. 稼働状況から「使われていないのに課金されているもの」を優先して洗い出す。典型例:
   - 稼働中 EC2 が 0 台の VPC にある NAT Gateway / Interface VPC エンドポイント / Network Firewall / ALB
   - 未関連付けの Elastic IP（`PublicIPv4:IdleAddress`）
   - 最小容量が 0 でない Aurora Serverless v2、Multi-AZ の検証用 RDS、停止されていない RDS
   - 利用者のいない WorkSpaces・Directory Service、未アタッチの EBS、古いスナップショット
4. Databricks・MWAA などのマネージドサービスが作った VPC のリソースは、そのサービスの利用状況を確認しないと消せない。`risk` を上げ、`decision_by` に利用者の確認が必要と書く。
5. GuardDuty / Config / CloudTrail / WAF / KMS などの **セキュリティ統制のための費用は削減対象にしない**。どうしても挙げる場合は `risk: high` と「セキュリティ担当の判断が必要」を明記する。

## 削減見込み額の出し方
- `estimated_monthly_saving_usd` は **税抜** の月額。税（`config/budget.json` の `tax_rate`）は `slack_report.py` が加算する。
- 根拠は **当月の実績額（使用タイプ単位）÷ 対象数** を基本にし、`saving_basis` に計算式を書く（例: `APN1-NatGateway-Hours $767.75 ÷ 18台 ≒ $42.7/台 × 14台`）。
- 当月の途中から発生したコストで、当月実績を超える削減額になる場合は `ramp_up: true` を付け、単価 × 時間で根拠を書く。
- `start_month` は実施判断と作業に要する期間を見込んで現実的に置く（目安: レポート翌月の **翌月** から。オーナーが明確でリスクの低いものだけ翌月）。
- 同じコストを複数の施策で二重に数えない。

## 出力（`out/<M>/optimization.json`）
`scripts/optimization.py` で検証される。

```json
{
  "fiscal_year": "FY2026",
  "target_month": "2026-09",
  "cost_drivers": [
    {"title": "NAT Gateway（東京 18台）", "usage_types": ["APN1-NatGateway-Hours"], "resource_count": 18,
     "finding": "18台すべて稼働 EC2 が 0 台の VPC に存在"}
  ],
  "measures": [
    {"id": "M1", "title": "未使用 NAT Gateway の削除", "service": "EC2 - Other",
     "usage_types": ["APN1-NatGateway-Hours"],
     "target_resources": [{"id": "nat-xxxx", "region": "ap-northeast-1", "owner_hint": "harato"}],
     "action": "オーナー確認のうえ削除（再作成は Terraform/コンソールで数分）",
     "estimated_monthly_saving_usd": 597.8, "saving_basis": "$767.75 ÷ 18台 × 14台",
     "start_month": "2026-11", "effort": "low", "risk": "low",
     "decision_by": "各 VPC のオーナー", "ramp_up": false}
  ],
  "previous_measures_status": [{"id": "M1", "title": "...", "status": "done|partial|not_done|unknown", "note": "..."}],
  "summary": "Slack に載る1〜2文の総括"
}
```

- `cost_drivers` の金額は LLM が書かない（`slack_report.py` が `cost_breakdown.json` から計算する）。
- 前月に提案した施策（`.claude/memory/forecast-history.json` の `proposed_measures`）があれば、対象リソース ID が `inventory.json` に残っているかで実施状況を判定し、`previous_measures_status` に書く。
