from __future__ import annotations

import html
import logging
import re
import ssl
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from literature_review.abstract_reconstruct import get_work_title, reconstruct_abstract_from_inverted_index
from literature_review.citation_gb7714 import format_citation_gb7714_iso
from literature_review.config import Settings


def _polite_params(settings: Settings) -> dict[str, str]:
    if settings.openalex_email:
        return {"mailto": settings.openalex_email}
    return {}


def get_work_language_iso(work: dict[str, Any]) -> str:
    """仅反映 OpenAlex 原始 language 字段；缺失时默认 en（勿单独用于中文分池）。"""
    lang = work.get("language")
    if isinstance(lang, str) and len(lang.strip()) >= 2:
        return lang.strip()[:2].lower()
    return "en"


_CJK_IN_TITLE = re.compile(r"[\u4e00-\u9fff]")


def infer_language_iso(work: dict[str, Any]) -> str:
    """
    用于分池与 GB/T：优先 OpenAlex 的 language；
    缺失时若标题含汉字则判为 zh，否则 en。
    避免中文文献因未标注 language 被全部当成英文。
    """
    lang = work.get("language")
    if isinstance(lang, str) and len(lang.strip()) >= 2:
        return lang.strip()[:2].lower()
    title = get_work_title(work)
    if title and _CJK_IN_TITLE.search(title):
        return "zh"
    return "en"


def _works_get_json(
    settings: Settings,
    search_query: str,
    per_page: int = 25,
    language_filter: str | None = None,
    page: int = 1,
) -> tuple[str, dict[str, Any]]:
    """请求 OpenAlex /works，返回 (完整请求 URL, 响应 JSON)。"""
    base = settings.openalex_base_url
    q = search_query.strip()
    if not q:
        return "", {}
    params: dict[str, str | int] = {
        "search": q,
        "per_page": min(max(1, per_page), 100),
        "page": max(1, int(page)),
    }
    filter_parts: list[str] = []
    if language_filter:
        lf = language_filter.strip().lower()[:8]
        filter_parts.append(f"language:{lf}")
    filter_parts.append("type:!review")
    params["filter"] = ",".join(filter_parts)
    params.update(_polite_params(settings))
    url = f"{base}/works?{urllib.parse.urlencode(params)}"
    _TLS_EXC = (
        httpx.RemoteProtocolError,
        httpx.ConnectError,
        httpx.ReadError,
        ssl.SSLError,
        OSError,
        ConnectionError,
    )
    last_err = None
    for attempt in range(5):
        try:
            with httpx.Client(timeout=60.0) as client:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
            return url, data if isinstance(data, dict) else {}
        except _TLS_EXC as e:
            last_err = e
            err_str = str(e).lower()
            is_tls = any(x in err_str for x in ("tls", "ssl", "eof", "closed", "connection"))
            if is_tls and attempt < 4:
                wait = min(45, 3 * (2**attempt))
                logger.warning("OpenAlex TLS/SSL 连接异常，%s 秒后重试（%d/5）: %s", wait, attempt + 1, e)
                time.sleep(wait)
            else:
                raise
    if last_err:
        raise last_err
    return "", {}


def summarize_work_debug(w: dict[str, Any]) -> dict[str, Any]:
    """调试输出：单条文献摘要（避免整份 raw 过大）。"""
    pl = w.get("primary_location") or {}
    src = (pl.get("source") or {}).get("display_name")
    jn = None
    if isinstance(src, str) and src.strip():
        jn = html.unescape(src.strip())
    return {
        "id": w.get("id"),
        "title": get_work_title(w),
        "language": w.get("language"),
        "publication_year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count"),
        "type": w.get("type"),
        "journal_or_source": jn,
    }


def search_works_response(
    settings: Settings,
    search_query: str,
    per_page: int = 25,
    language_filter: str | None = None,
) -> dict[str, Any]:
    """
    调试：返回 OpenAlex 一次检索的 request_url、meta、每条结果的 language/title 等。
    若 search_query 为空，返回 skipped 说明。
    """
    q = search_query.strip()
    if not q:
        return {"skipped": True, "reason": "empty search_query"}
    url, data = _works_get_json(settings, q, per_page, language_filter)
    results = list(data.get("results") or [])
    zh_n = sum(1 for w in results if get_work_language_iso(w) == "zh")
    en_n = sum(1 for w in results if get_work_language_iso(w) == "en")
    return {
        "request_url": url,
        "search_query": q,
        "language_filter": language_filter,
        "per_page_requested": min(max(1, per_page), 100),
        "meta": data.get("meta"),
        "results_count": len(results),
        "language_counts_in_results": {
            "zh": zh_n,
            "en": en_n,
            "other": len(results) - zh_n - en_n,
        },
        "results": [summarize_work_debug(w) for w in results],
    }


def search_works(
    settings: Settings,
    search_query: str,
    per_page: int = 25,
    language_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    使用 OpenAlex /works 的 search 参数做全文检索。
    language_filter: 可选，如 en；对应 filter=language:en。
    中文文献建议不设此参数，改用中文检索词检索；单独 filter=language:zh 在实务中常召回偏少或不准。
    """
    q = search_query.strip()
    if not q:
        return []
    _, data = _works_get_json(settings, q, per_page, language_filter, page=1)
    return list(data.get("results") or [])


def search_works_gather(
    settings: Settings,
    search_query: str,
    min_results: int,
    language_filter: str | None = None,
    per_page: int = 100,
    max_pages: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    分页拉取 OpenAlex /works，去重后直至凑够 min_results 条或无更多页。
    解决单次 search 仅返回少量命中（如中文检索只给 5 条）的问题。
    """
    q = search_query.strip()
    stats: dict[str, Any] = {
        "pages_fetched": 0,
        "request_urls": [],
        "meta_count_last": None,
        "stopped_reason": "",
    }
    if not q or min_results <= 0:
        stats["stopped_reason"] = "empty_query_or_min_results"
        return [], stats

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    page = 1
    pp = min(max(1, per_page), 100)

    while len(out) < min_results and page <= max_pages:
        url, data = _works_get_json(settings, q, pp, language_filter, page=page)
        stats["request_urls"].append(url)
        meta = data.get("meta") if isinstance(data, dict) else {}
        stats["meta_count_last"] = meta.get("count") if isinstance(meta, dict) else None

        batch = list(data.get("results") or [])
        for w in batch:
            wid = w.get("id") or ""
            if wid and wid not in seen:
                seen.add(wid)
                out.append(w)

        stats["pages_fetched"] = page

        if len(batch) == 0:
            stats["stopped_reason"] = "empty_page"
            break
        if len(out) >= min_results:
            stats["stopped_reason"] = "min_results_met"
            break
        if len(batch) < pp:
            stats["stopped_reason"] = "partial_last_page"
            break
        total = meta.get("count") if isinstance(meta, dict) else None
        if total is not None and page * pp >= int(total):
            stats["stopped_reason"] = "reached_meta_count"
            break
        page += 1

    if not stats["stopped_reason"]:
        stats["stopped_reason"] = "max_pages" if page > max_pages else "exhausted_while"

    return out, stats


def normalize_work(raw: dict[str, Any]) -> dict[str, Any]:
    """提取标题、摘要、年份、被引、语言、GB/T 7714 引用串。"""
    inv = raw.get("abstract_inverted_index")
    abstract = None
    if isinstance(inv, dict):
        abstract = reconstruct_abstract_from_inverted_index(inv)
    title = get_work_title(raw)
    year = raw.get("publication_year")
    cited = raw.get("cited_by_count")
    if cited is None:
        cited = 0
    lang = infer_language_iso(raw)
    citation_text = format_citation_gb7714_iso(raw, lang)
    wid = raw.get("id") or raw.get("openalex_id") or ""
    return {
        "openalex_id": wid,
        "title": title,
        "abstract": abstract,
        "publication_year": year,
        "cited_by_count": int(cited) if cited is not None else 0,
        "language": lang,
        "citation_text": citation_text,
        "raw": raw,
    }


def merge_work_results(
    list_a: list[dict[str, Any]],
    list_b: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for w in list_a + list_b:
        wid = w.get("id") or ""
        if not wid:
            continue
        if wid in seen:
            continue
        seen.add(wid)
        out.append(w)
    return out


def merge_work_lists(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按顺序合并多路结果并去重（保留先出现的顺序）。支持 raw 的 id 与 normalize 后的 openalex_id。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for lst in lists:
        for w in lst:
            wid = w.get("id") or w.get("openalex_id") or ""
            if not wid or wid in seen:
                continue
            seen.add(wid)
            out.append(w)
    return out
