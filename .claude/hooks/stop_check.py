#!/usr/bin/env python3
"""Stop フック: Python コードに未コミットの変更があればユニットテストを実行する。

失敗したら終了コード 2 で停止をブロックし、Claude に修正させる。
stop_hook_active（このフックによる継続中）の場合は無限ループ防止のため何もしない。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))
VENV_PY = ROOT / ".venv" / "bin" / "python"


def changed_python_files() -> list[str]:
    r = subprocess.run(
        ["git", "status", "--porcelain", "-uall"], cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    return [line[3:] for line in r.stdout.splitlines() if line.endswith(".py")]


def main() -> int:
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return 0
    if not changed_python_files():
        return 0
    python = str(VENV_PY) if VENV_PY.exists() else sys.executable
    r = subprocess.run(
        [python, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        print(f"ユニットテストが失敗しています。修正してください:\n{r.stderr[-3000:]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
