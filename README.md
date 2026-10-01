# aws-sandbox-cost-monitoring

社内 AWS サンドボックス環境（アカウント 921407950230）のコストを毎月確認し、Slack にレポートするプロジェクト。

- 当月の利用額と、年度（4月〜翌3月）の累計・着地予測を出す
- 年度の着地予測は LLM（Claude）が見積もる
- 予算を超えそうなときは、**どのサービス・リソースがコストを使っているかと、その改善策** を示す
- 改善策を実施しても予算に収まらない分については、Slack 上で **修正稟議の作成** を依頼する

Claude Code の「ハーネス」（ルール・スキル・フック・メモリ・検証）として組んである。構成は [ハーネスエンジニアリング実装ガイド](https://qiita.com/nogataka/items/d1b3fcf355c630cd7fc8) を参考にした。

---

## 処理の流れ

```
 ① データ取得（スクリプト・読み取り専用）
    fetch_costs.py      … 月次推移・年度累計・サービス別・AWS 予測（参考値）
    fetch_breakdown.py  … 使用タイプ別・リージョン別の内訳
    inventory.py        … リソースの棚卸し（NAT GW / EIP / RDS など）
          │
 ② 年度着地予測（LLM）… forecast.json      ← 予算は見ずに見積もる
          │   ※保存時にフックが自動検証
 ③ 予算判定（スクリプト）… slack_report.py（dry-run）
          │
          ├─ ✅ 予算内 ──────────────────────────────┐
          │                                            │
 ④ ⚠️ 注意 / 🚨 超過見込みのとき                     │
    コスト消費元の特定と改善策（LLM）… optimization.json
    改善策の効果を差し引いて再判定（スクリプト）       │
    それでも超過する場合 → 稟議下書き（LLM）… ringi_draft.md
          │                                            │
 ⑤ Slack 投稿（slack_report.py --send）←──────────────┘
          │
 ⑥ 記録（record_forecast.py）… 予測・判定・提案した施策を履歴に追記
```

役割分担は次のとおり。

- **LLM が行うこと:** 見積もりと分析（予測、改善策、稟議の下書き）
- **スクリプトが行うこと:** 判定と計算（予算比較、施策効果の計算、修正後予算の推奨額）。稟議依頼を出すかどうかの判断が LLM の解釈でぶれないようにするため、ここはスクリプトに固定している

---

## セットアップ

### 1. Python 環境（Python 3.12 以上。現在の .venv は 3.14）
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
依存は boto3 だけ。Slack への投稿は標準ライブラリの urllib、テストは unittest で書いている。

### 2. AWS 認証（MFA）
```bash
scripts/refresh-creds.sh    # MFA コードを入力 → プロファイル sandbox-mfa に一時クレデンシャル（最大36時間）
```
スクリプトは環境変数 `AWS_PROFILE` を使う。未設定なら `sandbox-mfa` を使う。

### 3. 予算・通知先の設定（`config/budget.json`）
```json
{
  "fiscal_years": {
    "FY2026": { "budget_jpy": 2500000, "fx_jpy_per_usd": 150 }
  },
  "tax_rate": 0.1,
  "revision": {
    "buffer_ratio": 0.1,
    "round_to_usd": 100,
    "ringi_form_url": "",
    "mentions": []
  },
  "slack": { "top_services": 5 }
}
```
| キー | 内容 |
|---|---|
| `budget_usd` または `budget_jpy` + `fx_jpy_per_usd` | 年度予算。円建ての場合は換算レートも書く |
| `tax_rate` | 改善策の削減額に上乗せする税率 |
| `revision.buffer_ratio` / `round_to_usd` | 修正後予算の推奨額を計算するときの余裕の比率と、切り上げの単位 |
| `revision.ringi_form_url` | Slack の「修正稟議を作成する」ボタンのリンク先 |
| `revision.mentions` | 通知時にメンションする相手（例: `"<@U012345>"`、`"<!subteam^S012345>"`） |

### 4. Slack Webhook
次のどちらかを設定する。**値はファイルに書かない。**
```bash
export SLACK_WEBHOOK_URL=...              # Incoming Webhook の URL
# または
export SLACK_WEBHOOK_SECRET_ID=...        # Secrets Manager（ap-northeast-1）のシークレット ID
```

---

## 使い方

### Claude Code から（基本）
| コマンド | 内容 |
|---|---|
| `/cost-report 2026-09` | 月次レポート一式（取得 → 予測 → 判定 → 改善策 → 投稿確認 → 記録） |
| `/cost-optimization 2026-09` | コスト消費元の特定と改善策だけを作る |
| `/budget-revision 2026-09` | 修正稟議の下書きだけを作る |

対象月を省略した場合、月初5日以内なら前月（締めた月の確定レポート）、それ以外は当月（速報）が対象になる。
対話セッションでは、Slack に投稿する前に dry-run の内容が提示され、了承してから投稿される。

### スクリプトを直接実行する
```bash
.venv/bin/python scripts/fetch_costs.py --month 2026-09
.venv/bin/python scripts/fetch_breakdown.py --month 2026-09
.venv/bin/python scripts/inventory.py --month 2026-09
# （forecast.json / optimization.json は LLM が作成）
.venv/bin/python scripts/validate_forecast.py out/2026-09/forecast.json
.venv/bin/python scripts/optimization.py out/2026-09/optimization.json
.venv/bin/python scripts/slack_report.py --month 2026-09          # dry-run
.venv/bin/python scripts/slack_report.py --month 2026-09 --send   # 投稿
.venv/bin/python scripts/record_forecast.py --month 2026-09
```
- **取得データの再利用:** 取得済みのファイルはそのまま使う。再取得するときは `--force` を付ける（Cost Explorer API は1回 $0.01 かかる。1回のレポートで計5回程度呼ぶ）。
- **二重投稿の防止:** 一度投稿した月は `--resend` を付けないと再投稿できない。
- **終了コード 3:** `slack_report.py` は、🚨 超過見込みなのに `optimization.json` がないと終了コード 3 で止まる。改善策の提示を必須にしているため。

### 定期実行（ヘッドレス）
```bash
scripts/run_monthly.sh [YYYY-MM]
# cron 例: 0 9 1 * * /path/to/aws-sandbox-cost-monitoring/scripts/run_monthly.sh
```
`claude -p` で `/cost-report` を実行する。投稿と記録まで自動で行い、ログは `logs/` に残る。
**注意:** 今の認証は MFA の一時クレデンシャル（最大36時間）なので、無人での定期実行はまだできない（下記「未実装・課題」を参照）。

### テスト
```bash
.venv/bin/python -m unittest discover -s tests
```
対象は年度計算、集計、予測の検証、改善策の検証、予算判定、Slack メッセージの組み立て（計32件）。

---

## 開発手順（コードを修正するとき）

### 1. 作業前の準備
```bash
cd aws-sandbox-cost-monitoring
source .venv/bin/activate          # 以降は python / pip が .venv のものになる（終了は deactivate）
pip install -r requirements.txt    # 依存が変わった場合だけ
scripts/refresh-creds.sh           # AWS にアクセスするスクリプトを動かす場合（有効期限は最大36時間）
```
- `activate` しない場合は、コマンドの `python` を `.venv/bin/python` に置き換える。
- Claude Code は常に `.venv/bin/python scripts/...` の形で実行する（`.claude/settings.json` の許可ルールがこの形を前提にしているため）。
- `main` に直接コミットしない。作業用のブランチを切る（例: `git switch -c feature/resource-owners`）。

### 2. 修正するときの決まり（詳細は `.claude/rules/python.md`）
- 依存は boto3 と標準ライブラリだけ。追加したい場合は相談し、`requirements.txt` に書く。
- 計算ロジック（年度計算・判定・メッセージ組み立て）と I/O（AWS・Slack・ファイル）は関数を分け、計算ロジックには `tests/` にテストを書く。
- AWS は読み取り専用（get / list / describe / lookup 系のみ）。
- 予算・宛先などの設定値は `config/budget.json` に書く。コードに直接書かない。シークレットは環境変数か Secrets Manager に置く。

### 3. 動作確認
```bash
python -m unittest discover -s tests                     # ユニットテスト（AWS 不要・数秒）
python scripts/slack_report.py --month 2026-09           # 既存の out/ を使った dry-run（Slack には送らない）
python scripts/fetch_costs.py --month 2026-09 --force    # 取得処理を変えた場合だけ（CE API 課金 $0.01/回）
```
フックを修正した場合は、JSON を標準入力で渡して単体で動かせる。
```bash
echo '{"tool_input":{"command":"aws ec2 terminate-instances --instance-ids i-1"}}' | python3 .claude/hooks/guard_bash.py; echo $?   # 2 ならブロック
```
フックは `python3`（システムの Python・標準ライブラリだけ）で動くので、`.venv` の外でも動くように書く。

### 4. ルール・スキル・フックを変更するとき
| 変更するもの | 注意点 |
|---|---|
| `.claude/rules/*.md` | 次のセッションから読み込まれる |
| `.claude/skills/*/SKILL.md` | `description` がスキルを呼び出すきっかけになる。使い方が変わったら README の「使い方」も直す |
| `.claude/hooks/*.py` | 次のツール実行から反映される |
| `.claude/settings.json` のフック・権限 | Claude Code を再起動するか、`/hooks` で確認してから反映される |

### 5. コミットする前に
- [ ] `python -m unittest discover -s tests` がすべて通る（Claude Code で作業している場合は Stop フックでも自動で実行される）
- [ ] `progress.md` を更新した（`.claude/rules/progress.md`。Claude Code で作業している場合は Stop フックがチェックする）
- [ ] 使い方・構成が変わったら README.md を更新した
- [ ] `out/`、`logs/`、`.env`、`.claude/settings.local.json` がコミット対象に入っていない（`.gitignore` 済みだが `git status` で確認する）
- [ ] AWS キーや Webhook URL がコードやドキュメントに入っていない

Claude Code に修正を依頼する場合も、流れは同じ。ルールに従って修正し、保存時（PostToolUse）と終了時（Stop）にフックが構文・テスト・`progress.md` の更新をチェックする。

---

## Slack レポートの構成

1. ヘッダー（対象月、確定か速報か）
2. 当月利用額（前月比）
3. 年度累計、予算消化率、経過月数
4. 年度着地予測（現状維持・レンジ付き）、予算差額、判定
5. サービス別 Top5
6. 予測の根拠
7. （⚠️ / 🚨 のとき）コスト消費元 Top5（使用タイプ単位の実績額と所見）
8. （⚠️ / 🚨 のとき）改善策（月あたり削減額、開始月、リスク、対象リソース数、オーナー、判断者）
9. （⚠️ / 🚨 のとき）前回提案した施策の実施状況、施策実施後の着地予測、予算内に収めるための月額上限
10. 依頼ブロック（施策の実施判断／修正稟議。ボタンと下書き付き）

| 現状維持の判定 | 改善策実施後の判定 | Slack での依頼 |
|---|---|---|
| ✅ 予算内 | — | 通常のレポートのみ |
| ⚠️ / 🚨 | ✅ / ⚠️ | 改善策の **実施判断** を依頼 |
| 🚨 | 🚨 | 改善策の実施判断に加えて、**残る不足分の修正稟議** を依頼 |

判定の基準は次のとおり。
- ✅ 予算内: 予測の上限が予算以下
- ⚠️ 注意: 予測値は予算以下だが、予測の上限が予算を超える
- 🚨 超過見込み: 予測値が予算を超える

---

## ディレクトリ構成

```
aws-sandbox-cost-monitoring/
├── README.md                     # このファイル
├── CLAUDE.md                     # Claude Code が毎セッション読み込むプロジェクト概要
├── progress.md                   # [メモリ] 進捗・意思決定ログ・次にやること
├── requirements.txt              # Python の依存（boto3 のみ）
├── config/
│   └── budget.json               # 予算・税率・メンション先・稟議フォーム URL
├── scripts/
│   ├── fiscal.py                 # 年度計算（FY2026 = 2026/4〜2027/3）
│   ├── fetch_costs.py            # Cost Explorer: 月次推移・年度累計・AWS 予測
│   ├── fetch_breakdown.py        # Cost Explorer: 使用タイプ・リージョン内訳
│   ├── inventory.py              # リソース棚卸し（describe / list のみ）
│   ├── validate_forecast.py      # forecast.json の検証
│   ├── optimization.py           # optimization.json の検証と施策効果の計算
│   ├── slack_report.py           # 予算判定・メッセージ組み立て・投稿
│   ├── record_forecast.py        # 予測履歴への追記
│   ├── run_monthly.sh            # ヘッドレスでの月次実行
│   ├── refresh-creds.sh          # MFA 一時クレデンシャルの取得
│   └── cost_report.py            # （旧）直近3ヶ月をターミナルに表示する確認用スクリプト
├── tests/                        # unittest
├── out/<YYYY-MM>/                # 出力（gitignore 対象）
│   ├── cost_data.json / cost_breakdown.json / inventory.json   … 取得データ
│   ├── forecast.json / optimization.json / ringi_draft.md      … LLM の出力
│   └── judgement.json / slack_sent.json                        … 判定結果・投稿済みの印
└── .claude/
    ├── settings.json             # [フック] フック設定・権限（commit 対象）
    ├── settings.local.json       # 個人設定（gitignore 対象）
    ├── rules/                    # [ルール]
    ├── skills/                   # [スキル]
    ├── hooks/                    # [フック] スクリプト本体
    ├── memory/
    │   └── forecast-history.json # [メモリ] 予測・実績・提案した施策の履歴（追記専用）
    └── contexts/
        └── cost-context.md       # [メモリ] 人が管理する前提知識
```

---

## ハーネスの構成

### ルール（`.claude/rules/`）
| ファイル | 内容 |
|---|---|
| `fiscal-year.md` | 年度の定義と呼び方。計算は必ず `fiscal.py` を使う |
| `aws-access.md` | AWS は読み取り専用。Cost Explorer は us-east-1。API 課金に注意する |
| `forecast.md` | LLM が予測するときの原則（予算を見ない、レンジで出す、途中から発生したコストの加算）と出力の形式 |
| `cost-optimization.md` | コスト消費元を特定する手順、削減額の根拠の書き方、セキュリティ系の費用を削減対象にしない、など |
| `slack-report.md` | 投稿は dry-run を経てから。判定の基準、レポートの構成 |
| `security.md` | シークレットを書かない。予測履歴は追記のみ |
| `python.md` | 依存は boto3 だけ。テストを書く（`scripts/`・`tests/` を編集するときだけ読み込まれる） |
| `progress.md` | 問い合わせへの対応で何かが変わったら、応答を終える前に `progress.md` を更新する。いつ・何を・どう書くか |

### スキル（`.claude/skills/`）
| スキル | 内容 |
|---|---|
| `cost-report` | 月次レポート全体の手順 |
| `cost-optimization` | コスト消費元の特定と改善策の作成 |
| `budget-revision` | 修正稟議の下書き（改善策を実施しても超過する場合） |

### フック（`.claude/settings.json` → `.claude/hooks/`）
| イベント | スクリプト | 役割 |
|---|---|---|
| SessionStart | `session_start.py` | `progress.md` の対応事項、直近の予測履歴、未設定の項目をコンテキストに読み込む |
| PreToolUse（Bash） | `guard_bash.py` | AWS の更新系コマンド（get / list / describe / lookup 以外）、Webhook への直接送信、予測履歴の改変、`--no-verify` をブロックする |
| PreToolUse（Edit / Write） | `guard_files.py` | `.env` と予測履歴の直接編集、AWS キーや Slack トークンの混入をブロックする |
| PostToolUse（Edit / Write） | `post_edit_check.py` | `.py` の構文チェック。`forecast.json` と `optimization.json` の自動検証 |
| Stop | `stop_check.py` | Python に変更があれば、終了前にユニットテストを実行する |
| Stop | `progress_check.py` | `progress.md` より新しい変更ファイル（未コミット分と `out/`）があれば終了をブロックし、`progress.md` の更新を促す（自動実行時は対象外） |

### メモリ
| ファイル | 書く主体 | 用途 |
|---|---|---|
| `progress.md` | Claude と人 | 進捗、意思決定ログ、次のセッションでやること |
| `.claude/memory/forecast-history.json` | `record_forecast.py` だけ | 毎月の予測・実績・判定・提案した施策。翌月の予測補正と施策の実施確認に使う。改ざんを防ぐため JSON の追記専用にしている |
| `.claude/contexts/cost-context.md` | 人 | データだけでは分からない情報（研修の予定、年1回の請求、残す理由のあるリソースなど） |

会話の全文はメモリとしては保存しない。次に必要な決定事項と未完了のタスクだけを `progress.md` に残す。

---

## 環境についての前提（2026-10-01 の調査結果）

- **組織上の位置づけ:** サンドボックスは AWS Organizations の **メンバーアカウント**。管理アカウントは 082896731144（リセラー）。
  - コスト配分タグ（`aws:createdBy` を含む）の有効化と、タグポリシーの設定は **管理アカウントでしかできない**。そのため、今の状態ではタグを使ってユーザー別にコストを集計することはできない。
- **CloudTrail:** 証跡 `ds-ded-cloudtrail` が、2020-11 から全リージョン分を S3 に記録している。記録されるユーザー名は IAM ユーザー名なので、リソースの作成者を特定できる。
- **権限の制約:** リソース単位のコストを取得する `GetCostAndUsageWithResources` は、権限がなく AccessDenied になる（スクリプトはこれを飛ばして処理を続ける）。

---

## 現状（2026-10-01 時点）

| 項目 | 状態 |
|---|---|
| データ取得・予測・判定・Slack メッセージ（dry-run） | 実装済み。2026-09 の実データで動作を確認した |
| 改善策の検証と施策効果の計算 | 実装済み（テスト済み） |
| 2026-09 のレポート | `cost_data` / `cost_breakdown` / `inventory` / `forecast` は作成済み。**`optimization.json` は未作成**（分析結果と改善策11件は `out/2026-09/analysis_notes.md` に記載） |
| Slack への投稿 | **未実施**（Webhook、メンション先、稟議フォーム URL が未設定） |
| 予測履歴への記録 | **未実施**（`forecast-history.json` は空） |

2026-09 の試算結果:
- 年度累計は $13,094 で、予算 $16,667（250万円、1ドル=150円で換算）の 78.6% を消化している
- 現状のままでは年度着地は $31,950 の見込み
- 改善策11件（月 $2,149 の削減）をすべて実施すると、着地は約 $19,900 の見込み。それでも約 $3,300（約49万円）不足する

## 未実装・課題

- [ ] **リソース作成者の特定**（`scripts/resource_owners.py`）: 作成から90日以内は CloudTrail の `lookup-events`、それより古いものは S3 の証跡ログから作成者の IAM ユーザーを特定する。改善策を作成者ごとの確認依頼にまとめ、ユーザー別の推定コストも出す
- [ ] IAM ユーザーと Slack ユーザー ID の対応表（`config/owners.json`）と、作成者ごとのメンション
- [ ] リセラーへ、`aws:createdBy` と `Owner` のコスト配分タグ有効化を依頼する（検討中）
- [ ] `config/budget.json` の為替レートを確定する（今は暫定の150円）。Webhook、メンション先、稟議フォーム URL を設定する
- [ ] 無人での定期実行環境: MFA の一時クレデンシャルでは cron を回せないため、IAM ロール方式を検討する
- [ ] 月が終わっていても AWS 側の請求が未確定（Estimated）の場合に、ヘッダーを「確定」ではなく「速報」と表示する
- [ ] `CLAUDE.md` のディレクトリ構成を現状に合わせて更新する
