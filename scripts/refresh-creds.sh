#!/bin/bash
set -euo pipefail

# -----------------------------------------------
# 環境に合わせて変更してください
MFA_SERIAL="arn:aws:iam::921407950230:mfa/y.osumi"
SOURCE_PROFILE="sandbox"       # 元の長期クレデンシャルのプロファイル名
TARGET_PROFILE="sandbox-mfa"   # 一時クレデンシャルの書き込み先プロファイル名
DURATION=129600                # 有効期間（秒）: 最大36時間
# -----------------------------------------------

command -v jq >/dev/null 2>&1 || { echo "Error: jq が必要です。brew install jq でインストールしてください。"; exit 1; }

read -rp "MFA code: " TOKEN

CREDS=$(aws sts get-session-token \
  --serial-number "$MFA_SERIAL" \
  --token-code "$TOKEN" \
  --duration-seconds "$DURATION" \
  --profile "$SOURCE_PROFILE" \
  --output json)

aws configure set aws_access_key_id     "$(echo "$CREDS" | jq -r '.Credentials.AccessKeyId')"     --profile "$TARGET_PROFILE"
aws configure set aws_secret_access_key "$(echo "$CREDS" | jq -r '.Credentials.SecretAccessKey')" --profile "$TARGET_PROFILE"
aws configure set aws_session_token     "$(echo "$CREDS" | jq -r '.Credentials.SessionToken')"    --profile "$TARGET_PROFILE"
aws configure set region                ap-northeast-1                                             --profile "$TARGET_PROFILE"

EXPIRY=$(echo "$CREDS" | jq -r '.Credentials.Expiration')
echo "完了: プロファイル '$TARGET_PROFILE' に書き込みました。有効期限: $EXPIRY"
