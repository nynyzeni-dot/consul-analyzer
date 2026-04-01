# -*- coding: utf-8 -*-
"""
LINE Messaging API Webhook: テキストを受け取り analyzer と同じロジックで Claude 分析し返信する。
line-bot-sdk に依存せず requests + 署名検証のみ（Windows でも pip 可能）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
from typing import Any

import requests
from flask import Flask, abort, request

from analyzer import analyze_transcript, get_client, load_env
from notion_sync import save_consult_analysis_to_notion_safe

load_env()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET") or "").strip()
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_PROFILE_URL = "https://api.line.me/v2/bot/profile/{user_id}"

LINE_TEXT_MAX = 4500


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def verify_line_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET or not signature:
        return False
    mac = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(signature, expected)


def line_reply(reply_token: str, text: str) -> None:
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:5000]}],
    }
    r = requests.post(
        LINE_REPLY_URL,
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()


def line_push(user_id: str, text: str) -> None:
    for chunk in split_for_line(text):
        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": chunk[:5000]}],
        }
        r = requests.post(
            LINE_PUSH_URL,
            headers=_headers(),
            json=payload,
            timeout=60,
        )
        r.raise_for_status()


def get_display_name(user_id: str) -> str:
    url = LINE_PROFILE_URL.format(user_id=user_id)
    try:
        r = requests.get(url, headers=_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        name = (data.get("displayName") or "").strip()
        return name if name else "LINEユーザー"
    except Exception as e:
        logger.warning("プロフィール取得失敗: %s", e)
        return "LINEユーザー"


def split_for_line(text: str, max_len: int = LINE_TEXT_MAX) -> list[str]:
    if len(text) <= max_len:
        return [text] if text else [""]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:max_len])
        rest = rest[max_len:]
    return chunks


def run_analysis_and_push(user_id: str, client_name: str, text: str) -> None:
    try:
        anthropic_client = get_client()
        md = analyze_transcript(anthropic_client, client_name, text)
        parts = split_for_line(md)
        for i, part in enumerate(parts):
            prefix = f"[{i + 1}/{len(parts)}]\n" if len(parts) > 1 else ""
            line_push(user_id, prefix + part)
        save_consult_analysis_to_notion_safe(client_name, md)
    except RuntimeError as e:
        line_push(user_id, f"エラー: {str(e)[:LINE_TEXT_MAX]}")
    except Exception as e:
        logger.exception("分析処理で例外")
        line_push(user_id, f"エラー: 処理に失敗しました。{str(e)[:LINE_TEXT_MAX]}")


def extract_user_id(source: dict[str, Any]) -> str | None:
    return source.get("userId")


def handle_event(event: dict[str, Any]) -> None:
    if event.get("type") != "message":
        return

    reply_token = event.get("replyToken")
    source = event.get("source") or {}
    user_id = extract_user_id(source)
    message = event.get("message") or {}

    if not reply_token or not user_id:
        return

    if message.get("type") != "text":
        try:
            line_reply(reply_token, "テキストメッセージのみ対応しています。")
        except Exception as e:
            logger.warning("reply 失敗: %s", e)
        return

    text = (message.get("text") or "").strip()
    if not text:
        try:
            line_reply(reply_token, "テキストを送信してください。")
        except Exception as e:
            logger.warning("reply 失敗: %s", e)
        return

    try:
        line_reply(reply_token, "コンサル文面を分析しています。少々お待ちください。")
    except Exception as e:
        logger.warning("reply 失敗: %s", e)
        return

    def job() -> None:
        name = get_display_name(user_id)
        run_analysis_and_push(user_id, name, text)

    threading.Thread(target=job, daemon=True).start()


@app.get("/")
def health() -> tuple[str, int]:
    return "ok", 200


@app.post("/callback")
def callback() -> tuple[str, int]:
    if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
        abort(503)

    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()
    if not verify_line_signature(body, signature):
        logger.warning("署名検証に失敗しました")
        abort(400)

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        abort(400)

    for event in data.get("events", []):
        try:
            handle_event(event)
        except Exception:
            logger.exception("イベント処理中に例外")

    return "OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
