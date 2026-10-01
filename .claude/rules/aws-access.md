# AWS アクセスルール

- このプロジェクトの AWS 操作は **読み取り専用**。`get-*` / `list-*` / `describe-*` 以外の AWS 操作（create / delete / put / update / terminate 等）は実行しない。
  - `.claude/hooks/guard_bash.py` が aws CLI の更新系コマンドをブロックする。
- Cost Explorer は **us-east-1** エンドポイント固定（`boto3.client("ce", region_name="us-east-1")`）。それ以外のサービスはデフォルトリージョン ap-northeast-1。
- 認証はプロファイル（環境変数 `AWS_PROFILE`、未設定時は `sandbox-mfa`）を使う。MFA 一時クレデンシャルが切れていたら `scripts/refresh-creds.sh` の実行をユーザーに依頼する（Claude が MFA コードを推測・入力しない）。
- Cost Explorer API は **1リクエスト $0.01** の課金がある。データ取得は `scripts/fetch_costs.py`（集計）・`scripts/fetch_breakdown.py`（使用タイプ・リージョン内訳）に集約し、1回のレポートで同じ API を何度も叩かない。取得済みの `out/<YYYY-MM>/*.json` があれば再利用する。
- リソースの棚卸しは `scripts/inventory.py`（describe / list 系のみ・無料）で行う。個別に AWS CLI を叩いて調べる場合も読み取り系に限る。
- リソース単位のコスト（`GetCostAndUsageWithResources`）は現状 IAM 権限が無く AccessDenied になる。スクリプトはスキップして継続する。
- 金額指標は `UnblendedCost`（USD）で統一する。
