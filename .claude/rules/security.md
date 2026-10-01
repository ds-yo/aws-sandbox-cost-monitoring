# セキュリティルール

- 次のものをコード・設定・ドキュメント・コミットに含めない（`guard_files.py` が書き込みをブロックする）:
  - AWS アクセスキー（`AKIA...` / `ASIA...`）、シークレットキー、セッショントークン
  - Slack Webhook URL（`https://hooks.slack.com/services/...`）、Slack トークン（`xoxb-` / `xoxp-`）
- `.env` / `.claude/settings.local.json` は gitignore 対象。Claude は `.env` を作成・編集しない（値の設定はユーザーが行う）。
- `out/` 配下（取得したコストデータ）はコミットしない。
- `.claude/memory/forecast-history.json` は **追記専用**。`scripts/record_forecast.py` 経由でのみ更新し、過去エントリを書き換えない（`guard_files.py` が直接編集をブロックする）。
