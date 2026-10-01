#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit) フック: 書き込み禁止ファイルとシークレット混入をブロックする。

ルール: .claude/rules/security.md
"""

import json
import re
import sys
from pathlib import Path

PROTECTED_SUFFIXES = (".claude/memory/forecast-history.json",)
SECRET_PATTERNS = {
    "AWS アクセスキー": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "AWS シークレットキー": re.compile(r"aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+]{40}"),
    "Slack Webhook URL": re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    "Slack トークン": re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}"),
}


def written_text(tool_input: dict) -> str:
    parts = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    parts += [e.get("new_string", "") for e in tool_input.get("edits", [])]
    return "\n".join(p for p in parts if p)


def check(tool_input: dict) -> str | None:
    path = tool_input.get("file_path", "")
    name = Path(path).name
    if path.endswith(PROTECTED_SUFFIXES):
        return f"{name} は追記専用です。scripts/record_forecast.py 経由で更新してください"
    if name == ".env" or name.startswith(".env."):
        return ".env はユーザーが管理します。設定が必要な変数名と用途をユーザーに伝えてください"
    text = written_text(tool_input)
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            return f"{label} らしき値が含まれています。環境変数または Secrets Manager を使ってください"
    return None


def main() -> int:
    data = json.load(sys.stdin)
    reason = check(data.get("tool_input", {}))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
