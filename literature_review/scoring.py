from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

_REVIEW_TITLE_PATTERN = re.compile(
    r"\b(review|survey|overview|state[- ]?of[- ]?the[- ]?art|systematic review|"
    r"meta[- ]?analysis|综述|进展|述评|评述)\b",
    re.IGNORECASE,
)


def _is_review_like(work: dict[str, Any]) -> bool:
    """标题或 OpenAlex type 显示为综述类。"""
    raw = work.get("raw") or {}
    if str(raw.get("type") or "").lower() == "review":
        return True
    title = (work.get("title") or "").strip()
    return bool(title and _REVIEW_TITLE_PATTERN.search(title))


def filter_out_reviews(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剔除综述、述评类文献，仅保留原创研究。"""
    return [w for w in works if not _is_review_like(w)]


def filter_out_no_abstract(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剔除无摘要的文献，仅保留有摘要的。"""
    return [w for w in works if (w.get("abstract") or "").strip()]


def current_year() -> int:
    return datetime.utcnow().year


def s_rec(age_years: float) -> float:
    """
    时间权重：Age≤5 年为满分 1；超过后按 (Age-5)/10 线性衰减至 0。
    与需求一致：S_rec = max(0, 1 - (Age-5)/10)，Age 为相对当前年的年数。
    """
    if age_years <= 5:
        return 1.0
    return max(0.0, 1.0 - (age_years - 5.0) / 10.0)


def s_auth(citations: int, c_max: float) -> float:
    """
    权威性：ln(1+Ci) / ln(1+Cmax)，Cmax 为本批样本中的最大被引（避免马太效应的绝对尺度）。
    """
    if c_max <= 0:
        return 0.0
    num = math.log1p(max(0, citations))
    den = math.log1p(c_max)
    if den <= 0:
        return 0.0
    return min(1.0, max(0.0, num / den))


def score_work(
    publication_year: int | None,
    cited_by_count: int,
    c_max: float,
    ref_year: int | None = None,
    language_iso: str | None = None,
) -> dict[str, float]:
    """
    单篇得分与分量，ref_year 默认当前年。
    中文文献（zh）降低权威性权重、提高时间权重，避免被引偏低被挤出前列。
    """
    ry = ref_year if ref_year is not None else current_year()
    if publication_year is None:
        age = 100.0
    else:
        age = float(ry - int(publication_year))
        if age < 0:
            age = 0.0
    sr = s_rec(age)
    sa = s_auth(cited_by_count, c_max)
    lang = (language_iso or "en")[:2].lower()
    if lang == "zh":
        w_rec, w_auth = 0.65, 0.35
    else:
        w_rec, w_auth = 0.5, 0.5
    total = w_rec * sr + w_auth * sa
    # 综述类已在 filter_out_reviews 中剔除，此处无需再降权
    return {
        "S_rec": sr,
        "S_auth": sa,
        "score": total,
        "age_years": age,
        "w_rec": w_rec,
        "w_auth": w_auth,
    }


def rank_works(
    normalized_works: list[dict[str, Any]],
    ref_year: int | None = None,
) -> list[dict[str, Any]]:
    """
    对已规范化工作列表打分并排序；Cmax 取本批 cited_by_count 最大值。
    每项增加 _score_detail 字段。
    """
    if not normalized_works:
        return []
    c_max = max((w.get("cited_by_count") or 0) for w in normalized_works)
    c_max = float(c_max) if c_max > 0 else 0.0

    ranked: list[dict[str, Any]] = []
    for w in normalized_works:
        det = score_work(
            w.get("publication_year"),
            int(w.get("cited_by_count") or 0),
            c_max,
            ref_year=ref_year,
            language_iso=w.get("language"),
        )
        item = dict(w)
        item["_score_detail"] = det
        ranked.append(item)

    ranked.sort(key=lambda x: float(x["_score_detail"]["score"]), reverse=True)
    return ranked
