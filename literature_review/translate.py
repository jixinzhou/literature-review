"""英文文献标题与摘要译为简体中文（火山引擎 TranslateText），供前端展示；撰写综述仍使用原文。"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from literature_review.config import Settings, VolcTranslateNotConfiguredError
from literature_review.volc_translate import translate_text_list

logger = logging.getLogger(__name__)

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
    combined = f"{t}\n{a}"
    return _cjk_ratio(combined) < 0.35


def _iter_text_batches(
    items: list[dict[str, Any]], field: str
) -> Iterator[tuple[list[str], list[str]]]:
    """
    按火山限制切批：每批 TextList 最多 16 条，总字符不超过 5000。
    产出 (openalex_id 列表, 与之一一对应的文本列表)。
    """
    batch_ids: list[str] = []
    batch_texts: list[str] = []
    cur_chars = 0
    for w in items:
        oid = (w.get("openalex_id") or "").strip()
        if not oid:
            continue
        t = (w.get(field) or "").strip()
        if len(t) > 5000:
            t = t[:5000]
        if batch_texts and (
            len(batch_texts) >= 16 or cur_chars + len(t) > 5000
        ):
            yield batch_ids, batch_texts
            batch_ids, batch_texts = [], []
            cur_chars = 0
        batch_ids.append(oid)
        batch_texts.append(t)
        cur_chars += len(t)
    if batch_texts:
        yield batch_ids, batch_texts


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

    ak = (settings.volc_access_key_id or "").strip()
    sk = (settings.volc_secret_access_key or "").strip()
    if not ak or not sk:
        raise VolcTranslateNotConfiguredError()

    try:
        for batch_ids, batch_texts in _iter_text_batches(to_translate, "title"):
            zh_list = translate_text_list(ak, sk, batch_texts, target_language="zh")
            for oid, zh in zip(batch_ids, zh_list):
                if oid not in out:
                    out[oid] = {"title_zh": "", "abstract_zh": ""}
                out[oid]["title_zh"] = zh

        for batch_ids, batch_texts in _iter_text_batches(to_translate, "abstract"):
            zh_list = translate_text_list(ak, sk, batch_texts, target_language="zh")
            for oid, zh in zip(batch_ids, zh_list):
                if oid not in out:
                    out[oid] = {"title_zh": "", "abstract_zh": ""}
                out[oid]["abstract_zh"] = zh
    except Exception as e:
        logger.warning("火山翻译失败: %s", e)
        raise

    # 去掉全无内容的条目
    return {
        k: v
        for k, v in out.items()
        if (v.get("title_zh") or "").strip() or (v.get("abstract_zh") or "").strip()
    }


def apply_zh_fields(works: list[dict[str, Any]], zh_map: dict[str, dict[str, str]]) -> None:
    """原地写入 title_zh、abstract_zh。"""
    for w in works:
        oid = (w.get("openalex_id") or "").strip()
        if not oid or oid not in zh_map:
            continue
        z = zh_map[oid]
        w["title_zh"] = z.get("title_zh") or ""
        w["abstract_zh"] = z.get("abstract_zh") or ""
