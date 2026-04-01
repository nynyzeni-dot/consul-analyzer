# -*- coding: utf-8 -*-
"""
コンサル音声テキストの Claude 分析ロジック（CLI・LINE Bot 共通）
"""

from __future__ import annotations

import os
from pathlib import Path

from anthropic import Anthropic
from anthropic import APIError, APIConnectionError, APITimeoutError, RateLimitError
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_FORMAT_SPEC = """
必ず次の Markdown 構造のみを出力すること。前置き・後書き・コードフェンスは禁止。

# {client_name}

## 数字サマリー
- 売上・スタッフ数・単価・新規数（原文に数値がなければ「原文に明記なし」などと正直に書く）

## 課題（優先度順）
- 🔴 緊急: （箇条書きで1行以上。なければ「なし」）
- 🟡 中期: （同上）
- 🟢 長期: （同上）

## 改善アクション（3つ）
① 今週やること: （具体的に）
② 来月やること: （具体的に）
③ 3ヶ月後までにやること: （具体的に）

見出しの「# 」の直後のクライアント名は、指定名と完全一致させること。
"""


def load_env() -> None:
    env_path = BASE_DIR / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


def get_client() -> Anthropic:
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "環境変数 ANTHROPIC_API_KEY が設定されていません。.env を確認してください。"
        )
    return Anthropic(api_key=key)


def get_model() -> str:
    return (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5").strip()


def list_input_txts() -> list[Path]:
    if not INPUT_DIR.is_dir():
        raise RuntimeError(
            f"入力フォルダが見つかりません: {INPUT_DIR}"
        )
    files = sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".txt" and not p.name.startswith(".")
    )
    return files


def read_transcript(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_user_message(client_name: str, transcript: str) -> str:
    return f"""以下は美容室オーナーとのコンサルの音声をテキスト化したものです。

【クライアント名（ファイル名から決定・見出しにそのまま使う）】
{client_name}

--- 原文 ---
{transcript}
---

{OUTPUT_FORMAT_SPEC.format(client_name=client_name)}
"""


def strip_code_fences(text: str) -> str:
    """API が ```markdown で囲んで返した場合に外す。"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def analyze_transcript(client: Anthropic, client_name: str, transcript: str) -> str:
    model = get_model()
    user_content = build_user_message(client_name, transcript)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=8192,
            system=(
                "あなたは美容室向け組織コンサルの要約担当です。"
                "入力テキストから事実と推測を区別し、簡潔な日本語で整理する。"
                "出力は指定の Markdown のみ。"
            ),
            messages=[{"role": "user", "content": user_content}],
        )
    except RateLimitError as e:
        raise RuntimeError(f"API のレート制限に達しました。しばらく待ってから再試行してください。\n詳細: {e}") from e
    except APIConnectionError as e:
        raise RuntimeError(f"API への接続に失敗しました。ネットワークを確認してください。\n詳細: {e}") from e
    except APITimeoutError as e:
        raise RuntimeError(f"API がタイムアウトしました。再試行してください。\n詳細: {e}") from e
    except APIError as e:
        raise RuntimeError(f"Claude API エラー: {e}") from e

    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    if not parts:
        raise RuntimeError("API からテキスト応答が返りませんでした。")
    return strip_code_fences("".join(parts))


def save_output(stem: str, markdown: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{stem}.md"
    out_path.write_text(markdown + "\n", encoding="utf-8")
    return out_path
