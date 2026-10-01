---
paths:
  - "scripts/**/*.py"
  - "tests/**/*.py"
---

# Python コーディングルール

- Python 3.12+。依存は **boto3 と標準ライブラリのみ**（HTTP は `urllib.request`、テストは `unittest`）。依存を追加する場合はユーザーに確認する。
- 実行は `.venv/bin/python` を使う。
- 純粋な計算ロジック（年度計算・判定・メッセージ組み立て）と I/O（AWS / Slack / ファイル）は関数を分け、計算ロジックにはテストを書く（`tests/`）。
- テストは `.venv/bin/python -m unittest discover -s tests` で実行する。Stop フックでも自動実行される。
- 金額の丸めは表示時のみ行い、計算途中では float のまま扱う。
- 型ヒントを付ける。モジュール先頭に docstring を書く。
