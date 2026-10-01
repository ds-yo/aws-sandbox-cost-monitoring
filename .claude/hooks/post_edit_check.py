#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit) フック: 編集直後の即時フィードバック。

- *.py: 構文チェック（ruff があればフォーマットも）
- out/<YYYY-MM>/forecast.json: validate_forecast.py でスキーマ・整合性チェック
- out/<YYYY-MM>/optimization.json: optimization.py でスキーマ・cost_breakdown との整合性チェック
問題があれば終了コード 2 + stderr で Claude に修正を促す。
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))
VENV_PY = ROOT / ".venv" / "bin" / "python"
VALIDATORS = [
    (re.compile(r"/out/\d{4}-\d{2}/forecast\.json$"), "validate_forecast.py"),
    (re.compile(r"/out/\d{4}-\d{2}/optimization\.json$"), "optimization.py"),
]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)


def main() -> int:
    data = json.load(sys.stdin)
    path = data.get("tool_input", {}).get("file_path", "")
    python = str(VENV_PY) if VENV_PY.exists() else sys.executable

    if path.endswith(".py"):
        if shutil.which("ruff"):
            run(["ruff", "format", path])
        r = run([python, "-m", "py_compile", path])
        if r.returncode != 0:
            print(f"構文エラー: {path}\n{r.stderr}", file=sys.stderr)
            return 2

    validator = next((script for pattern, script in VALIDATORS if pattern.search(path)), None)
    if validator:
        r = run([python, str(ROOT / "scripts" / validator), path])
        if r.returncode != 0:
            print(r.stderr or r.stdout, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
