# -*- coding: utf-8 -*-
"""
Railway 用起動ランチャー。
startCommand がシェル展開されず $PORT が空になる環境でも、os.environ['PORT'] で確実にバインドする。
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    port = os.environ.get("PORT", "").strip()
    if not port:
        print("エラー: 環境変数 PORT が空です。Railway のデプロイ設定を確認してください。", file=sys.stderr)
        sys.exit(1)
    args = [
        sys.executable,
        "-m",
        "gunicorn",
        "app:app",
        f"--bind=0.0.0.0:{port}",
        "--workers",
        "1",
        "--threads",
        "2",
        "--timeout",
        "120",
        "--graceful-timeout",
        "30",
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
    ]
    os.execvp(sys.executable, args)


if __name__ == "__main__":
    main()
