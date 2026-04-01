#!/bin/sh
# Railway が注入する PORT でリッスン（未設定時は起動失敗で気づけるよう空バインドを避ける）
set -e
if [ -z "${PORT}" ]; then
  echo "エラー: 環境変数 PORT が設定されていません。" >&2
  exit 1
fi
exec gunicorn app:app --bind "0.0.0.0:${PORT}" --workers 1 --threads 2 --timeout 120
