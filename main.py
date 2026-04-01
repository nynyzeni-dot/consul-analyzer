# -*- coding: utf-8 -*-
"""
コンサル音声テキスト整理ツール（CLI）
input/ の .txt を読み、Claude API で整理した Markdown を output/ に保存する。
"""

from __future__ import annotations

import sys

from analyzer import (
    BASE_DIR,
    analyze_transcript,
    get_client,
    list_input_txts,
    load_env,
    read_transcript,
    save_output,
)


def main() -> int:
    load_env()
    try:
        paths = list_input_txts()
    except RuntimeError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    if not paths:
        print(
            "エラー: input フォルダに処理対象の .txt ファイルがありません。",
            file=sys.stderr,
        )
        return 1

    try:
        client = get_client()
    except RuntimeError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    exit_code = 0
    for path in paths:
        stem = path.stem
        client_name = stem
        try:
            text = read_transcript(path)
        except OSError as e:
            print(f"エラー: ファイルを読めませんでした ({path.name}): {e}", file=sys.stderr)
            exit_code = 1
            continue
        except UnicodeDecodeError as e:
            print(
                f"エラー: UTF-8 として読めませんでした ({path.name})。ファイルを UTF-8 で保存してください。\n詳細: {e}",
                file=sys.stderr,
            )
            exit_code = 1
            continue

        print(f"処理中: {path.name} …")
        try:
            md = analyze_transcript(client, client_name, text)
            out = save_output(stem, md)
            print(f"  保存しました: {out.relative_to(BASE_DIR)}")
        except RuntimeError as e:
            print(f"エラー ({path.name}): {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
