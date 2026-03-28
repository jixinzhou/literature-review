"""英文文献标题与摘要译为简体中文（通义千问），供前端展示；撰写综述仍使用原文。"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from literature_review.config import Settings
from literature_review.prompts import TRANSLATE_SYSTEM_PROMPT
from literature_review.qwen_client import chat_completion, parse_json_strict

logger = logging.getLogger(__name__)

# 粗略判断：已有较多中文时跳过机器翻译，避免重复加工
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _cjk_ratio(text: str) -> float:
    if not text or not text.strip():
        return 0.0
    n = sum(1 for c in text if _CJK_RE.match(c))
    return n / max(len(text), 1)


def _needs_translation(title: str, abstract: str) -> bool:
    t = (title or "").strip()
    a = (abstract or "").strip()
    if not t and not a:
        return False
    # 标题与摘要整体偏中文则不再译
    combined = f"{t}\n{a}"
    return _cjk_ratio(combined) < 0.35


def _translate_extra_body() -> dict[str, Any]:
    """
    关闭思考链以加速直出（仅部分 DashScope 模型支持）。
    默认不发送；若需开启可设 QWEN_TRANSLATE_DISABLE_THINKING=true。
    若接口报错，请保持默认或改回 false。
    """
    if os.getenv("QWEN_TRANSLATE_DISABLE_THINKING", "").lower() in ("1", "true", "yes"):
        return {"enable_thinking": False}
    return {}


def _chunk_items(items: list[dict[str, Any]], max_per_chunk: int = 4) -> list[list[dict[str, Any]]]:
    if not items:
        return []
    return [items[i : i + max_per_chunk] for i in range(0, len(items), max_per_chunk)]


def translate_works_to_zh(settings: Settings, works: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """
    按 openalex_id 返回 { id: { "title_zh": ..., "abstract_zh": ... } }。
    失败或跳过项不会出现在结果中。
    """
    out: dict[str, dict[str, str]] = {}
    to_translate: list[dict[str, Any]] = []
    for w in works:
        oid = (w.get("openalex_id") or "").strip()
        if not oid:
            continue
        title = (w.get("title") or "").strip()
        abstract = (w.get("abstract") or "").strip()
        if not _needs_translation(title, abstract):
            continue
        to_translate.append({"openalex_id": oid, "title": title, "abstract": abstract})

    if not to_translate:
        return out

    model = settings.qwen_translate_model

    for chunk in _chunk_items(to_translate, max_per_chunk=4):
        user_lines = []
        for i, item in enumerate(chunk, 1):
            user_lines.append(
                f"【{i}】openalex_id: {item['openalex_id']}\n"
                f"title: {item['title']}\n"
                f"abstract: {item['abstract']}"
            )
        user_prompt = (
            "请将下列每条文献的 title、abstract 译为简体中文。保持学术语气，专有名词可保留英文。\n"
            "输出一个 JSON 数组，元素字段：openalex_id（字符串）、title_zh、abstract_zh（无摘要则 abstract_zh 为空字符串）。\n"
            "除 JSON 外不要输出任何文字。\n\n"
            + "\n\n".join(user_lines)
        )
        try:
            text = chat_completion(
                settings,
                model,
                TRANSLATE_SYSTEM_PROMPT,
                user_prompt,
                temperature=0.15,
                timeout=90.0,
                extra_body=_translate_extra_body(),
            )
            parsed = parse_json_strict(text)
            if isinstance(parsed, list):
                rows = parsed
            else:
                rows = (
                    parsed.get("items")
                    or parsed.get("translations")
                    or parsed.get("results")
                    or []
                )
            if not isinstance(rows, list):
                raise ValueError("模型返回非数组")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                oid = (row.get("openalex_id") or "").strip()
                if not oid:
                    continue
                tz = (row.get("title_zh") or "").strip()
                az = (row.get("abstract_zh") or "").strip()
                if tz or az:
                    out[oid] = {"title_zh": tz, "abstract_zh": az}
        except Exception as e:
            logger.warning("文献批量翻译失败（本批 %d 条）: %s", len(chunk), e)

    return out


def apply_zh_fields(works: list[dict[str, Any]], zh_map: dict[str, dict[str, str]]) -> None:
    """原地写入 title_zh、abstract_zh。"""
    for w in works:
        oid = (w.get("openalex_id") or "").strip()
        if not oid or oid not in zh_map:
            continue
        z = zh_map[oid]
        w["title_zh"] = z.get("title_zh") or ""
        w["abstract_zh"] = z.get("abstract_zh") or ""
