# -*- coding: utf-8 -*-
"""
Claude 分析結果（Markdown）を Notion DB に保存する。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_NOTION_DATABASE_ID = "7892876a-3b90-4614-b90f-8dc426e129a5"
STATUS_FIXED = "未対応"

# プロパティ名（Notion DB と一致させる）
PROP_TITLE = "クライアント名"
PROP_DATE = "日付"
PROP_SALES = "売上"
PROP_STAFF = "スタッフ数"
PROP_ISSUE_URGENT = "課題（緊急）"
PROP_ISSUE_MID = "課題（中期）"
PROP_ISSUE_LONG = "課題（長期）"
PROP_ACT1 = "アクション①今週"
PROP_ACT2 = "アクション②来月"
PROP_ACT3 = "アクション③3ヶ月後"
PROP_STATUS = "ステータス"


def get_database_id() -> str:
    """
    使用する Notion データベース ID。
    環境変数 NOTION_DATABASE_ID があれば最優先（Railway の Variables で上書きする）。
    """
    env_val = (os.getenv("NOTION_DATABASE_ID") or "").strip()
    return env_val if env_val else DEFAULT_NOTION_DATABASE_ID


def database_id_source() -> dict[str, Any]:
    """診断用: 実際に使う ID と、環境変数由来かどうか。"""
    env_val = (os.getenv("NOTION_DATABASE_ID") or "").strip()
    effective = env_val if env_val else DEFAULT_NOTION_DATABASE_ID
    return {
        "effective_database_id": effective,
        "from_environment_variable": bool(env_val),
        "env_value_raw_length": len(env_val),
        "default_if_unset": DEFAULT_NOTION_DATABASE_ID,
    }


def run_notion_database_test() -> dict[str, Any]:
    """
    Notion API で databases.retrieve を実行し、DB に接続できるか確認する。
    API キーや ID は返さない（設定有無のフラグのみ）。
    """
    src = database_id_source()
    db_id = src["effective_database_id"]
    out: dict[str, Any] = {
        "ok": False,
        "database_id": db_id,
        "database_id_from_env": src["from_environment_variable"],
        "default_database_id": DEFAULT_NOTION_DATABASE_ID,
        "notion_api_key_set": bool((os.getenv("NOTION_API_KEY") or "").strip()),
    }

    client = get_notion_client()
    if client is None:
        out["error"] = "NOTION_API_KEY が未設定です。Railway の Variables に設定してください。"
        out["hint"] = "NOTION_DATABASE_ID は任意。未設定時は default_database_id を使用します。"
        return out

    try:
        db = client.databases.retrieve(database_id=db_id)
        out["ok"] = True
        title_arr = db.get("title") or []
        parts: list[str] = []
        for item in title_arr:
            if not isinstance(item, dict):
                continue
            if item.get("plain_text"):
                parts.append(str(item["plain_text"]))
            else:
                te = item.get("text")
                if isinstance(te, dict) and te.get("content"):
                    parts.append(str(te["content"]))
        out["database_title"] = "".join(parts) or "(無題)"
        out["property_count"] = len(db.get("properties") or {})
    except Exception as e:
        out["error"] = str(e)
        out["error_type"] = type(e).__name__
        for attr in ("status", "code", "body"):
            if hasattr(e, attr):
                try:
                    out[f"notion_{attr}"] = getattr(e, attr)
                except Exception:
                    pass
        out["hint"] = (
            "database_id が無効な場合、Notion の DB ページ URL 内の database/ の後の UUID を確認し、"
            "Railway の NOTION_DATABASE_ID に設定してください。"
            "対象 DB をインテグレーションに共有（接続）しているかも確認してください。"
        )

    return out


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
    text = (text or "").strip()
    if not text:
        return [{"type": "text", "text": {"content": " "}}]
    chunks: list[dict[str, Any]] = []
    for i in range(0, len(text), max_len):
        chunks.append({"type": "text", "text": {"content": text[i : i + max_len]}})
    return chunks


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


def extract_sales_and_staff(summary: str) -> tuple[str, str]:
    """数字サマリーから売上・スタッフ数らしき記述を抽出。"""
    if not summary.strip():
        return "", ""

    sales_lines: list[str] = []
    staff_lines: list[str] = []
    for raw in summary.splitlines():
        line = raw.strip().lstrip("-").strip()
        if not line:
            continue

        staff_hit = any(
            k in line
            for k in (
                "スタッフ",
                "人体制",
                "スタイリスト",
                "アシスタント",
                "正社員",
                "パート",
                "デビュー",
            )
        ) or bool(re.search(r"\d+\s*名", line))
        sales_hit = any(
            k in line
            for k in (
                "売上",
                "売り上げ",
                "単価",
                "新規",
                "粗利",
                "損益",
                "分岐点",
            )
        ) or bool(re.search(r"\d+(?:\.\d+)?\s*[〜～]?\s*\d*\s*万", line))

        if staff_hit and not sales_hit:
            staff_lines.append(line)
        elif sales_hit and not staff_hit:
            sales_lines.append(line)
        elif staff_hit and sales_hit:
            staff_lines.append(line)
            sales_lines.append(line)
        else:
            sales_lines.append(line)

    sales = "\n".join(sales_lines).strip()
    staff = "\n".join(staff_lines).strip()
    if not sales and summary.strip():
        sales = summary.strip()[:2000]
    return sales, staff


def extract_issue_levels(issues_text: str) -> tuple[str, str, str]:
    """🔴緊急 / 🟡中期 / 🟢長期 ブロックを分離。"""
    text = issues_text or ""
    urgent: list[str] = []
    mid: list[str] = []
    long_t: list[str] = []
    mode: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if "🔴" in stripped or re.match(r"^[-*]?\s*🔴", stripped):
            mode = "u"
            rest = re.sub(r"^[-*]?\s*🔴\s*緊急\s*[：:]\s*", "", stripped).strip()
            if rest:
                urgent.append(rest)
            continue
        if "🟡" in stripped or re.match(r"^[-*]?\s*🟡", stripped):
            mode = "m"
            rest = re.sub(r"^[-*]?\s*🟡\s*中期\s*[：:]\s*", "", stripped).strip()
            if rest:
                mid.append(rest)
            continue
        if "🟢" in stripped or re.match(r"^[-*]?\s*🟢", stripped):
            mode = "l"
            rest = re.sub(r"^[-*]?\s*🟢\s*長期\s*[：:]\s*", "", stripped).strip()
            if rest:
                long_t.append(rest)
            continue

        if mode == "u":
            urgent.append(stripped)
        elif mode == "m":
            mid.append(stripped)
        elif mode == "l":
            long_t.append(stripped)

    return (
        "\n".join(urgent).strip(),
        "\n".join(mid).strip(),
        "\n".join(long_t).strip(),
    )


def extract_actions(actions_text: str) -> tuple[str, str, str]:
    """①今週 ②来月 ③3ヶ月 を抽出。"""
    t = (actions_text or "").strip()
    if not t:
        return "", "", ""

    parts2 = t.split("②", 1)
    head = parts2[0]
    a1 = re.sub(r"^[\s\S]*?①\s*今週[^:：]*[：:]\s*", "", head, count=1).strip()
    if not a1 and "①" in head:
        a1 = head.split("①", 1)[-1].strip()
        a1 = re.sub(r"^今週[^:：]*[：:]\s*", "", a1).strip()

    if len(parts2) < 2:
        return a1[:2000], "", ""

    mid_and_rest = parts2[1]
    parts3 = mid_and_rest.split("③", 1)
    a2 = parts3[0].strip()
    a2 = re.sub(r"^来月[^:：]*[：:]\s*", "", a2, flags=re.S).strip()

    if len(parts3) < 2:
        return a1[:2000], a2[:2000], ""

    a3 = parts3[1].strip()
    a3 = re.sub(
        r"^3\s*ヶ月後[^:：]*[：:]\s*",
        "",
        a3,
        flags=re.S,
    ).strip()

    return a1[:2000], a2[:2000], a3[:2000]


def extract_all_fields(client_name: str, analysis_md: str) -> dict[str, str]:
    sections = parse_analysis_sections(analysis_md)
    summary = _pick_section(sections, "数字サマリー")
    issues = _pick_section(sections, "課題")
    actions = _pick_section(sections, "改善アクション")

    sales, staff = extract_sales_and_staff(summary)
    urg, mid, lng = extract_issue_levels(issues)
    a1, a2, a3 = extract_actions(actions)

    return {
        PROP_TITLE: client_name.strip() or "（名称なし）",
        PROP_DATE: dt.date.today().isoformat(),
        PROP_SALES: sales,
        PROP_STAFF: staff,
        PROP_ISSUE_URGENT: urg,
        PROP_ISSUE_MID: mid,
        PROP_ISSUE_LONG: lng,
        PROP_ACT1: a1,
        PROP_ACT2: a2,
        PROP_ACT3: a3,
        PROP_STATUS: STATUS_FIXED,
    }


def _parse_staff_count(text: str) -> int | None:
    if not text:
        return None
    m = re.search(
        r"(?:スタッフ|スタイリスト|アシスタント|計|全体|体制)(?:[^\d]{0,12})?(\d+)\s*名",
        text,
    )
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*人体制", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*名", text)
    if m:
        return int(m.group(1))
    return None


def _parse_number_maybe(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", text.replace("〜", "~").replace("～", "~"))
    if m:
        return float(m.group(1)) * 10000
    m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _notion_prop_for_value(
    prop_name: str, value: str, pinfo: dict[str, Any]
) -> dict[str, Any] | None:
    ptype = pinfo.get("type")
    if ptype == "title":
        return {"title": _split_rich_text(value)}
    if ptype == "date":
        return {"date": {"start": value}}
    if ptype == "rich_text":
        return {"rich_text": _split_rich_text(value)}
    if ptype == "number":
        if prop_name == PROP_STAFF:
            sn = _parse_staff_count(value)
            if sn is not None:
                return {"number": float(sn)}
        num = _parse_number_maybe(value)
        if num is not None:
            return {"number": num}
        return None
    if ptype == "select":
        if prop_name == PROP_STATUS:
            return {"select": {"name": STATUS_FIXED}}
        return None
    if ptype == "status":
        if prop_name == PROP_STATUS:
            return {"status": {"name": STATUS_FIXED}}
        return None
    return None


def build_notion_properties(
    schema: dict[str, Any], fields: dict[str, str]
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for pname, raw_val in fields.items():
        if pname not in schema:
            continue
        pinfo = schema[pname]
        val = raw_val if pname != PROP_STATUS else STATUS_FIXED
        built = _notion_prop_for_value(pname, val, pinfo)
        if built is not None:
            props[pname] = built
    return props


def _fallback_properties_guess(fields: dict[str, str]) -> dict[str, Any]:
    """retrieve 失敗時: コンサル分析 DB の型想定（ステータスは SELECT・未対応/対応中/完了）。"""
    return {
        PROP_TITLE: {"title": _split_rich_text(fields[PROP_TITLE])},
        PROP_DATE: {"date": {"start": fields[PROP_DATE]}},
        PROP_SALES: {"rich_text": _split_rich_text(fields[PROP_SALES])},
        PROP_STAFF: {"rich_text": _split_rich_text(fields[PROP_STAFF])},
        PROP_ISSUE_URGENT: {"rich_text": _split_rich_text(fields[PROP_ISSUE_URGENT])},
        PROP_ISSUE_MID: {"rich_text": _split_rich_text(fields[PROP_ISSUE_MID])},
        PROP_ISSUE_LONG: {"rich_text": _split_rich_text(fields[PROP_ISSUE_LONG])},
        PROP_ACT1: {"rich_text": _split_rich_text(fields[PROP_ACT1])},
        PROP_ACT2: {"rich_text": _split_rich_text(fields[PROP_ACT2])},
        PROP_ACT3: {"rich_text": _split_rich_text(fields[PROP_ACT3])},
        PROP_STATUS: {"select": {"name": STATUS_FIXED}},
    }


def save_consult_analysis_to_notion(client_name: str, analysis_md: str) -> None:
    notion = get_notion_client()
    if notion is None:
        logger.info("NOTION_API_KEY 未設定のため Notion 保存をスキップします。")
        return

    db_id = get_database_id()
    fields = extract_all_fields(client_name, analysis_md)

    schema: dict[str, Any] = {}
    try:
        db = notion.databases.retrieve(database_id=db_id)
        schema = db.get("properties") or {}
    except Exception as e:
        logger.warning("Notion databases.retrieve に失敗: %s", e)

    if schema:
        properties = build_notion_properties(schema, fields)
        if PROP_STATUS in schema and PROP_STATUS not in properties:
            pinfo = schema[PROP_STATUS]
            if pinfo.get("type") == "select":
                properties[PROP_STATUS] = {"select": {"name": STATUS_FIXED}}
            elif pinfo.get("type") == "status":
                properties[PROP_STATUS] = {"status": {"name": STATUS_FIXED}}
    else:
        properties = _fallback_properties_guess(fields)

    try:
        page = notion.pages.create(
            parent={"database_id": db_id},
            properties=properties,
            children=[],
        )
        pid = page.get("id", "")
        logger.info(
            "Notion に保存しました page_id=%s client=%s",
            pid,
            fields[PROP_TITLE],
        )
    except Exception as e:
        logger.exception("Notion pages.create 失敗: %s", e)
        raise


def save_consult_analysis_to_notion_safe(client_name: str, analysis_md: str) -> None:
    try:
        save_consult_analysis_to_notion(client_name, analysis_md)
    except Exception:
        logger.exception("Notion 保存に失敗しました（LINE への配信は完了している可能性があります）")
