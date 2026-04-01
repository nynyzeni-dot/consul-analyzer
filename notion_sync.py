# -*- coding: utf-8 -*-
"""
Claude 分析結果（Markdown）を Notion 議事録 DB に保存する。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ユーザー指定の議事録 DB / data_source 識別子（環境変数 NOTION_DATABASE_ID で上書き可）
DEFAULT_NOTION_DATABASE_ID = "26c708db-dcc2-4c1e-bc44-95a8df53c329"
# musubihira README の DB ID（retrieve / create のフォールバック）
FALLBACK_DATABASE_ID = "e812dc2e-324e-4df2-b807-d77a35bc907c"


def get_database_id() -> str:
    return (os.getenv("NOTION_DATABASE_ID") or DEFAULT_NOTION_DATABASE_ID).strip()


def get_notion_client() -> Any | None:
    key = (os.getenv("NOTION_API_KEY") or "").strip()
    if not key:
        return None
    try:
        from notion_client import Client

        return Client(auth=key, log_level=logging.WARNING)
    except Exception as e:
        logger.warning("Notion クライアント初期化失敗: %s", e)
        return None


def _split_rich_text(text: str, max_len: int = 2000) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return [{"type": "text", "text": {"content": " "}}]
    chunks: list[dict[str, Any]] = []
    for i in range(0, len(text), max_len):
        chunks.append({"type": "text", "text": {"content": text[i : i + max_len]}})
    return chunks


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _split_rich_text(text)},
    }


def _heading_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _split_rich_text(text[:2000])},
    }


def parse_analysis_sections(markdown: str) -> dict[str, str]:
    lines = markdown.splitlines()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _pick_section(sections: dict[str, str], *keywords: str) -> str:
    for key, body in sections.items():
        for kw in keywords:
            if kw in key:
                return body
    return ""


def build_body_blocks(sections: dict[str, str], full_md: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    summary = _pick_section(sections, "数字サマリー")
    issues = _pick_section(sections, "課題")
    actions = _pick_section(sections, "改善アクション")

    def add_section(heading: str, body: str) -> None:
        if not body.strip():
            return
        blocks.append(_heading_block(heading))
        for para in body.split("\n\n"):
            if para.strip():
                blocks.append(_paragraph_block(para.strip()))

    add_section("数字サマリー", summary)
    add_section("課題（優先度順）", issues)
    add_section("改善アクション（3つ）", actions)

    if not blocks:
        blocks.append(_heading_block("分析結果"))
        blocks.append(_paragraph_block(full_md[:15000]))

    return blocks[:95]


def _find_title_property(schema: dict[str, Any]) -> str | None:
    for name, info in schema.items():
        if info.get("type") == "title":
            return name
    return None


def _pick_company_select(
    prop_schema: dict[str, Any], client_name: str
) -> dict[str, Any] | None:
    """一致する選択肢があるときだけ会社名を付与（無効な select は API エラーになる）。"""
    opts = (prop_schema.get("select") or {}).get("options") or []
    names = [o["name"] for o in opts if o.get("name")]
    if not names or not client_name:
        return None
    for n in names:
        if n == client_name or client_name in n or n in client_name:
            return {"select": {"name": n}}
    for n in names:
        if (client_name + "様") == n:
            return {"select": {"name": n}}
    return None


def build_database_properties(
    schema: dict[str, Any],
    page_title: str,
    client_name: str,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    title_prop = _find_title_property(schema)
    if title_prop:
        props[title_prop] = {"title": _split_rich_text(page_title)}

    today = dt.date.today().isoformat()
    for pname, pinfo in schema.items():
        if pname in props:
            continue
        t = pinfo.get("type")
        if t == "date" and ("日付" in pname or pname == "日付"):
            props[pname] = {"date": {"start": today}}
        elif t == "select" and "会社名" in pname:
            sel = _pick_company_select(pinfo, client_name)
            if sel:
                props[pname] = sel
        elif t == "select" and "ステータス" in pname:
            opts = (pinfo.get("select") or {}).get("options") or []
            if opts:
                names = [o["name"] for o in opts if o.get("name")]
                preferred = next(
                    (n for n in names if n in ("下書き", "メモ", "未着手", "ドラフト")),
                    None,
                )
                props[pname] = {"select": {"name": preferred or names[0]}}

    return props


def _fallback_properties(page_title: str) -> dict[str, Any]:
    """retrieve 失敗時: タイトル・日付のみ（会社名は選択肢不明のため付けない）。"""
    today = dt.date.today().isoformat()
    return {
        "議事録（タイトル）": {
            "title": _split_rich_text(page_title),
        },
        "日付": {"date": {"start": today}},
    }


def save_consult_analysis_to_notion(client_name: str, analysis_md: str) -> None:
    notion = get_notion_client()
    if notion is None:
        logger.info("NOTION_API_KEY 未設定のため Notion 保存をスキップします。")
        return

    db_id = get_database_id()
    page_title = f"{client_name} {dt.date.today().strftime('%Y-%m-%d')}"
    sections = parse_analysis_sections(analysis_md)
    children = build_body_blocks(sections, analysis_md)

    schema: dict[str, Any] = {}
    try:
        db = notion.databases.retrieve(database_id=db_id)
        schema = db.get("properties") or {}
    except Exception as e1:
        logger.warning(
            "Notion databases.retrieve に失敗 (%s)。フォールバック ID を試します。詳細: %s",
            db_id,
            e1,
        )
        if db_id != FALLBACK_DATABASE_ID:
            try:
                db = notion.databases.retrieve(database_id=FALLBACK_DATABASE_ID)
                schema = db.get("properties") or {}
                db_id = FALLBACK_DATABASE_ID
            except Exception as e2:
                logger.warning("フォールバック retrieve も失敗: %s", e2)

    properties = (
        build_database_properties(schema, page_title, client_name)
        if schema
        else _fallback_properties(page_title)
    )

    try:
        page = notion.pages.create(
            parent={"database_id": db_id},
            properties=properties,
            children=children[:100],
        )
        pid = page.get("id", "")
        logger.info("Notion に保存しました page_id=%s title=%s", pid, page_title)

        rest = children[100:]
        idx = 0
        while rest:
            chunk = rest[:100]
            rest = rest[100:]
            notion.blocks.children.append(block_id=pid, children=chunk)
            idx += 1
            if idx > 20:
                logger.warning("Notion ブロック追加上限に達しました")
                break
    except Exception as e:
        logger.exception("Notion pages.create 失敗: %s", e)
        raise


def save_consult_analysis_to_notion_safe(client_name: str, analysis_md: str) -> None:
    try:
        save_consult_analysis_to_notion(client_name, analysis_md)
    except Exception:
        logger.exception("Notion 保存に失敗しました（LINE への配信は完了している可能性があります）")
