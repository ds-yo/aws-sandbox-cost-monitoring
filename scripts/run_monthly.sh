#!/bin/bash
# 月次コストレポートを Claude Code のヘッドレスモードで実行する（cron / launchd から呼ぶ想定）。
#
# 使い方: scripts/run_monthly.sh [YYYY-MM]
# 前提:   SLACK_WEBHOOK_URL（または SLACK_WEBHOOK_SECRET_ID）と AWS 認証が有効であること
# cron例: 0 9 1 * * /path/to/aws-sandbox-cost-monitoring/scripts/run_monthly.sh
set -euo pipefail

cd "$(dirname "$0")/.."
MONTH="${1:-}"
mkdir -p logs
LOG="logs/run_$(date +%Y%m%d_%H%M%S).log"

export AUTO_SEND=1

claude -p "/cost-report ${MONTH}
自動実行です（AUTO_SEND=1）。ユーザー確認なしで投稿（--send）と記録まで行ってください。progress.md・cost-context.md は編集せず、提案があれば最終出力に書いてください。" \
  --allowedTools \
    "Read" \
    "Edit(out/**)" \
    "Bash(.venv/bin/python scripts/fetch_costs.py:*)" \
    "Bash(.venv/bin/python scripts/validate_forecast.py:*)" \
    "Bash(.venv/bin/python scripts/fetch_breakdown.py:*)" \
    "Bash(.venv/bin/python scripts/inventory.py:*)" \
    "Bash(.venv/bin/python scripts/optimization.py:*)" \
    "Bash(.venv/bin/python scripts/slack_report.py:*)" \
    "Bash(.venv/bin/python scripts/record_forecast.py:*)" \
  2>&1 | tee "$LOG"
