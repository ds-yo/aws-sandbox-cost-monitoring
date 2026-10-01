#!/usr/bin/env python3
"""Stop フック: ファイルを変更したのに progress.md を更新していなければ終了をブロックする。

ルール: .claude/rules/progress.md
判定: 未コミットの変更ファイル（git status）と out/ 配下のうち、progress.md より新しいものがあればブロック。
自動実行（AUTO_SEND=1）と、このフックによる継続中（stop_hook_active）は対象外。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))
PROGRESS = ROOT / "progress.md"
IGNORED_PARTS = {"__pycache__", ".venv", "logs", ".git"}
IGNORED_FILES = {".DS_Store", "slack_preview.json"}


def changed_files() -> list[Path]:
    r = subprocess.run(
        ["git", "status", "--porcelain", "-uall"], cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    files = [ROOT / line[3:].strip('"') for line in r.stdout.splitlines()]
    out_dir = ROOT / "out"  # gitignore 対象だがレポートの成果物なので対象にする
    if out_dir.exists():
        files += [p for p in out_dir.rglob("*") if p.is_file()]
    return [
        p
        for p in files
        if p.exists()
        and p != PROGRESS
        and p.name not in IGNORED_FILES
        and not IGNORED_PARTS & set(p.relative_to(ROOT).parts)
    ]


def main() -> int:
    data = json.load(sys.stdin)
    if data.get("stop_hook_active") or os.environ.get("AUTO_SEND") == "1":
        return 0
    progress_mtime = PROGRESS.stat().st_mtime if PROGRESS.exists() else 0.0
    newer = sorted(
        (p for p in changed_files() if p.stat().st_mtime > progress_mtime),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not newer:
        return 0
    listed = "\n".join(f"  - {p.relative_to(ROOT)}" for p in newer[:10])
    more = f"\n  …ほか {len(newer) - 10} 件" if len(newer) > 10 else ""
    print(
        "progress.md より新しい変更があります。.claude/rules/progress.md に従って progress.md"
        f"（現在地・完了・意思決定ログ・次セッションの対応事項）を更新してください:\n{listed}{more}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
