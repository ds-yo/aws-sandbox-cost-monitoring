#!/usr/bin/env python3
"""PreToolUse(Bash) フック: 危険・ルール違反のコマンドをブロックする。

- aws CLI の更新系操作（読み取り専用ルール: .claude/rules/aws-access.md）
- Slack Webhook への直接送信（slack_report.py 経由ルール: .claude/rules/slack-report.md）
- 予測履歴ファイルのシェル経由の改変（追記専用ルール: .claude/rules/security.md）
- git フックの迂回（--no-verify）
終了コード 2 + stderr で Claude にブロック理由を返す。
"""

import json
import re
import shlex
import sys

READONLY_PREFIXES = ("get-", "list-", "describe-", "lookup-")
READONLY_EXACT = {("s3", "ls"), ("configure", "list"), ("configure", "get"), ("configure", "list-profiles")}
GLOBAL_OPTS_WITH_VALUE = {"--profile", "--region", "--output", "--query", "--endpoint-url", "--color"}


def check_aws(command: str) -> str | None:
    for segment in re.split(r"&&|\|\||;|\||\n", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        # 先頭の環境変数代入（AWS_PROFILE=xxx aws ...）を読み飛ばす
        while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
            tokens = tokens[1:]
        if not tokens or tokens[0] != "aws":
            continue
        rest = tokens[1:]
        args: list[str] = []
        skip = False
        for t in rest:
            if skip:
                skip = False
                continue
            if t in GLOBAL_OPTS_WITH_VALUE:
                skip = True
                continue
            if t.startswith("-"):
                continue
            args.append(t)
            if len(args) == 2:
                break
        if len(args) < 2:
            continue
        service, op = args
        if (service, op) in READONLY_EXACT or op.startswith(READONLY_PREFIXES):
            continue
        return f"aws {service} {op} は更新系の可能性があるためブロックしました（このプロジェクトの AWS 操作は読み取り専用）"
    return None


def check(command: str) -> str | None:
    if reason := check_aws(command):
        return reason
    if "hooks.slack.com" in command:
        return "Slack Webhook への直接送信は禁止です。scripts/slack_report.py（dry-run → --send）を使ってください"
    if "forecast-history.json" in command and "record_forecast.py" not in command:
        if re.search(r">|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\btruncate\b", command):
            return "forecast-history.json は追記専用です。scripts/record_forecast.py 経由でのみ更新してください"
    if re.search(r"\bgit\b.*\s--no-verify\b", command):
        return "git フックの迂回（--no-verify）は禁止です"
    return None


def main() -> int:
    data = json.load(sys.stdin)
    reason = check(data.get("tool_input", {}).get("command", ""))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
