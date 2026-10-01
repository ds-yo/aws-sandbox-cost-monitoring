# aws-sandbox-cost-monitoring

## プロジェクト概要

AWS サンドボックス環境のコスト監視・レポーティングを行うプロジェクト。
Cost Explorer API を使ってコストデータを取得し、定期レポートを生成・通知する。

## 前提・規約

### 対象 AWS 環境
- アカウント: サンドボックス用 AWS アカウント
- リージョン: ap-northeast-1（東京）をデフォルトとする

### ディレクトリ構成
```
aws-sandbox-cost-monitoring/
├── CLAUDE.md                      # このファイル（毎セッション自動読み込み）
├── .mcp.json                      # MCPサーバー設定
├── .claude/
│   ├── settings.json             # ハーネス設定（commit 対象）
│   ├── settings.local.json       # 個人設定（gitignore 対象）
│   ├── skills/cost-report/       # コストレポートスキル
│   ├── commands/                  # スラッシュコマンド
│   └── agents/                    # サブエージェント定義
└── .gitignore
```

### コーディング規約
- 言語: Python 3.12+
- AWS SDK: boto3
- 認証: AWS プロファイルまたは環境変数（IAM ロール推奨）
- シークレット類はコードに直書きしない。環境変数または AWS Secrets Manager を使う

### 注意事項
- `settings.local.json` は `.gitignore` に含める
- AWS の認証情報・シークレットは絶対にコミットしない
