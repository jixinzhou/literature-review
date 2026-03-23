from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from literature_review.config import Settings, load_settings, project_root
from literature_review.openalex_client import (
    normalize_work,
    search_works_gather,
    search_works_response,
    summarize_work_debug,
)
from literature_review.prompts import (
    INTENT_SYSTEM_PROMPT,
    SELECTION_SYSTEM_PROMPT,
    WRITING_SYSTEM_PROMPT,
    build_intent_user_prompt,
    build_selection_user_prompt,
    build_writing_user_prompt,
)
from literature_review.qwen_client import chat_completion, parse_json_strict
from literature_review.scoring import filter_out_no_abstract, filter_out_reviews, rank_works


def run_intent_step(settings: Settings, user_description: str) -> dict[str, Any]:
    text = chat_completion(
        settings,
        settings.qwen_intent_model,
        INTENT_SYSTEM_PROMPT,
        build_intent_user_prompt(user_description),
        temperature=0.2,
    )
    return parse_json_strict(text)


def resolve_research_title(intent: dict[str, Any], override: str | None) -> str:
    """用户只输入一段话时，用模型输出的 research_topic；也可由 -t 显式覆盖。"""
    if override and override.strip():
        return override.strip()
    rt = (intent.get("research_topic") or intent.get("research_title") or "").strip()
    if rt:
        return rt
    a = intent.get("analysis") or {}
    parts: list[str] = []
    for k in ("problem", "scene", "method"):
        v = a.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    if parts:
        return " — ".join(parts)
    return "相关研究"


def _simplify_search_query(query: str, max_words: int = 6) -> str:
    """
    将复杂布尔检索式简化为 OpenAlex 更易命中的关键词串。
    OpenAlex search 对简单空格分隔关键词效果更好，复杂 AND/OR 易返回 0。
    """
    q = query.strip()
    if not q or len(q) < 2:
        return q
    q = re.sub(r"\b(AND|OR|NOT)\b", " ", q, flags=re.IGNORECASE)
    q = re.sub(r'["\'()]', " ", q)
    words = [w for w in q.split() if len(w) > 1][:max_words]
    return " ".join(words) if words else q[:80]


def _build_fallback_query(intent: dict[str, Any], prefer_cn: bool) -> str:
    """检索全面失败时，从 analysis 提取简单关键词兜底。prefer_cn=True 用中文，False 用英文。"""
    a = intent.get("analysis") or {}
    problem = (a.get("problem") or "").strip()
    scene = (a.get("scene") or "").strip()
    parts = [p for p in (problem, scene) if p][:2]
    combined = " ".join(parts)
    if not combined:
        return ""
    if prefer_cn:
        return _simplify_search_query(combined, 5)
    cn2en = [
        ("路径规划", "path planning"),
        ("机器人", "robot"),
        ("群体智能", "swarm intelligence"),
        ("蚁群", "ant colony"),
        ("粒子群", "particle swarm"),
        ("遗传算法", "genetic algorithm"),
    ]
    s = combined
    for cn, en in cn2en:
        s = s.replace(cn, en)
    return _simplify_search_query(s, 5)


def _extract_queries(intent: dict[str, Any]) -> dict[str, str]:
    """仅使用「研究问题 + 场景」的 history_background，不再使用 innovation_trend。"""
    sq = intent.get("search_queries") or {}
    hist = sq.get("history_background") or {}
    return {
        "hist_en": (hist.get("en") or "").strip(),
        "hist_cn": (hist.get("cn") or "").strip(),
    }


def _fetch_by_query(
    settings: Settings,
    query: str,
    min_gather: int,
    *,
    language_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    按检索词搜索 OpenAlex，返回原始结果（不按语言过滤）。
    逻辑：英文检索词 → 返回的即英文轨候选；中文检索词 → 返回的即中文轨候选。
    """
    q = query.strip()
    if not q:
        return []
    raw, _ = search_works_gather(
        settings, q, min_gather, language_filter=language_filter, per_page=100, max_pages=10
    )
    return raw


def _query_is_complex(q: str) -> bool:
    """含 AND/OR/NOT 的检索式易在冷门主题上返回 0，需优先尝试简化版。"""
    return bool(re.search(r"\b(AND|OR|NOT)\b", q, re.I))


def _fetch_en_candidates(settings: Settings, query: str) -> list[dict[str, Any]]:
    """
    英文检索词 → OpenAlex 返回的全部文献 → 作为英文轨候选，后续从中取 top 15。
    复杂布尔式时优先尝试简化版（冷门主题易返回 0）。
    """
    q = query.strip()
    if not q:
        return []
    min_g = max(settings.fetch_pool_size, settings.top_k_en * 2, 20)
    simple = _simplify_search_query(q) if _query_is_complex(q) else ""

    def _try(qry: str, lang: str | None) -> list[dict[str, Any]]:
        return _fetch_by_query(settings, qry, min_g, language_filter=lang)

    # 复杂式时先试简化（冷门主题布尔式常返回 0）
    if simple and simple != q:
        out = _try(simple, "en") or _try(simple, None)
        if out:
            return out
    out = _try(q, "en") or _try(q, None)
    return out


def _fetch_zh_candidates(settings: Settings, query: str) -> list[dict[str, Any]]:
    """
    中文检索词 → OpenAlex 返回的全部文献 → 作为中文轨候选，后续从中取 top 5。
    复杂布尔式时优先尝试简化版。
    """
    q = query.strip()
    if not q:
        return []
    min_g = max(settings.top_k_zh * 15, 40)
    simple = _simplify_search_query(q) if _query_is_complex(q) else ""
    if simple and simple != q:
        out = _fetch_by_query(settings, simple, min_g, language_filter=None)
        if out:
            return out
    out = _fetch_by_query(settings, q, min_g, language_filter=None)
    if not out and simple and simple != q:
        out = _fetch_by_query(settings, simple, min_g, language_filter=None)
    return out


def _ai_select_from_titles(
    settings: Settings,
    research_topic: str,
    works: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    """
    将文献标题交给 AI，按研究主题与类型平衡筛选出 top_n 篇。
    解析失败时回退到原顺序的前 top_n 篇。
    """
    if not works or top_n <= 0:
        return works[:top_n]
    pool_size = min(len(works), max(top_n * 2, 30))
    pool = works[:pool_size]
    titles = [(i + 1, (w.get("title") or "").strip() or "(无标题)") for i, w in enumerate(pool)]
    user_prompt = build_selection_user_prompt(research_topic, titles, top_n)
    try:
        text = chat_completion(
            settings,
            settings.qwen_intent_model,
            SELECTION_SYSTEM_PROMPT,
            user_prompt,
            temperature=0.2,
        )
        data = parse_json_strict(text)
        indices = data.get("selected_indices") or []
        if not isinstance(indices, list):
            indices = []
        seen: set[int] = set()
        ordered: list[dict[str, Any]] = []
        for idx in indices:
            i = int(idx) if isinstance(idx, (int, float)) else None
            if i is None or i < 1 or i > len(pool) or i in seen:
                continue
            seen.add(i)
            ordered.append(pool[i - 1])
        if len(ordered) >= top_n:
            return ordered[:top_n]
    except Exception:
        pass
    return pool[:top_n]


def select_top_en_only(
    settings: Settings,
    intent: dict[str, Any],
    *,
    return_candidates: int = 0,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    仅英文检索：英文检索词 → 返回文献 → 打分排序 → （可选）AI 按标题筛选 → 取 top TOP_K_EN 篇。
    return_candidates>0 时返回 (selected, candidates)，candidates 为池中未入选的后续文献。
    """
    q = _extract_queries(intent)
    en_query = q["hist_en"] or ""
    if not en_query:
        fb_en = _build_fallback_query(intent, prefer_cn=False)
        if fb_en:
            en_query = fb_en
    if not en_query:
        raise ValueError(
            "意图解析结果中缺少英文检索式（search_queries.history_background.en）"
        )

    raw_en = _fetch_en_candidates(settings, en_query)
    if not raw_en:
        fb_en = _build_fallback_query(intent, prefer_cn=False)
        if fb_en and fb_en != en_query:
            raw_en = _fetch_en_candidates(settings, fb_en)
    if not raw_en:
        raise ValueError(
            "英文检索未命中任何文献，请尝试更通用的关键词或检查网络。"
        )

    norm_en = normalize_pool(raw_en)
    norm_en = filter_out_reviews(norm_en)
    norm_en = filter_out_no_abstract(norm_en)
    if not norm_en:
        raise ValueError(
            "过滤综述和无摘要文献后无剩余文献。请尝试更换检索词或放宽条件。"
        )
    full_ranked = rank_works(norm_en)
    top_k = max(0, settings.top_k_en)

    if settings.use_ai_selection:
        research_topic = resolve_research_title(intent, None)
        selected = _ai_select_from_titles(settings, research_topic, full_ranked, top_k)
    else:
        selected = full_ranked[:top_k]

    for w in selected:
        w["_literature_pool"] = "en"

    if return_candidates > 0:
        selected_ids = {w.get("openalex_id") or w.get("id") for w in selected}
        candidates = [w for w in full_ranked if (w.get("openalex_id") or w.get("id")) not in selected_ids][
            :return_candidates
        ]
        for w in candidates:
            w["_literature_pool"] = "en"
        return selected, candidates
    return selected


def inspect_openalex_debug(settings: Settings, intent: dict[str, Any]) -> dict[str, Any]:
    """
    调试中间结果：仅英文检索轨，与 select_top_en_only 一致。
    """
    q = _extract_queries(intent)
    en_min = max(settings.fetch_pool_size, settings.top_k_en * 2, 20)
    en_query = q["hist_en"]

    payload: dict[str, Any] = {
        "_说明": "仅英文检索；英文检索词返回的文献取 top TOP_K_EN。",
        "extracted_queries": q,
        "top_k_en": settings.top_k_en,
        "en_min_gather": en_min,
        "intent_json": intent,
    }

    if en_query:
        payload["en_track_sample"] = search_works_response(
            settings, en_query, min(100, en_min), "en"
        )
        raw_en = _fetch_en_candidates(settings, en_query)
        payload["en_candidates_count"] = len(raw_en)
        norm = normalize_pool(raw_en)
        payload["after_normalize_count"] = len(norm)
        ranked = rank_works(norm)[: settings.top_k_en]
        payload["top_selected_count"] = len(ranked)
    else:
        payload["en_track_sample"] = {"skipped": True, "reason": "无英文检索式"}
        payload["en_candidates_count"] = 0

    return payload


def write_openalex_inspect_json(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    """写入 JSON，默认项目根目录 openalex_inspect.json。"""
    out = path or project_root() / "openalex_inspect.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out


def normalize_pool(raw_works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_work(w) for w in raw_works]


def format_literature_block(works: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, w in enumerate(works, start=1):
        title = w.get("title") or ""
        abstract = w.get("abstract") or "（无摘要）"
        cite = w.get("citation_text") or ""
        lines.append(
            f"[{i}] 标题：{title}\n摘要：{abstract}\n引用格式：{cite}\n"
        )
    return "\n".join(lines)


def print_works_for_confirmation(works: list[dict[str, Any]]) -> None:
    for i, w in enumerate(works, start=1):
        det = w.get("_score_detail") or {}
        score = det.get("score", "")
        year = w.get("publication_year", "")
        cited = w.get("cited_by_count", "")
        title = w.get("title", "")
        abst = w.get("abstract") or ""
        preview = abst[:280] + ("…" if len(abst) > 280 else "")
        lang = w.get("language", "")
        pool = w.get("_literature_pool", "")
        tag = "[英文]" if pool == "en" else ("[中文]" if pool == "zh" else "")
        print(f"\n--- [{i}] {tag} score={score}  lang={lang}  year={year}  cited={cited} ---")
        print(title)
        print(preview)


def confirm_with_user(works: list[dict[str, Any]]) -> bool:
    print_works_for_confirmation(works)
    try:
        s = input("\n确认以上文献并进入综述生成？(y/n，默认 y): ").strip().lower()
    except EOFError:
        return False
    if not s:
        return True
    return s in ("y", "yes", "是", "ok", "1")


def run_writing_step(
    settings: Settings,
    research_title: str,
    works: list[dict[str, Any]],
) -> str:
    block = format_literature_block(works)
    user = build_writing_user_prompt(research_title, block, total_count=len(works))
    return chat_completion(
        settings,
        settings.qwen_writing_model,
        WRITING_SYSTEM_PROMPT,
        user,
        temperature=0.4,
    )


def run_full_pipeline(
    user_description: str,
    research_title: str | None = None,
    *,
    skip_confirm: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    端到端：意图 -> OpenAlex 英文检索 -> 打分排序取 TOP_K_EN 篇 -> （可选确认）-> 综述。
    仅使用英文文献（OpenAlex 中文检索效果不佳已去除）。
    """
    cfg = settings or load_settings()
    intent = run_intent_step(cfg, user_description)
    resolved_title = resolve_research_title(intent, research_title)
    print(f"\n【研究主题】{resolved_title}\n")
    top = select_top_en_only(cfg, intent)
    print(f"进入综述的文献：英文 {len(top)}/{cfg.top_k_en} 篇。\n")
    if not skip_confirm and not confirm_with_user(top):
        return {
            "intent": intent,
            "research_title": resolved_title,
            "top_works": top,
            "review_text": "",
            "cancelled": True,
        }
    review = run_writing_step(cfg, resolved_title, top)
    return {
        "intent": intent,
        "research_title": resolved_title,
        "top_works": top,
        "review_text": review,
        "cancelled": False,
    }


def main_cli(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="国内外研究现状：意图解析 → OpenAlex → 筛选 → 通义千问综述（无前端）"
    )
    p.add_argument(
        "description",
        nargs="?",
        help="研究描述（一段话即可，无需单独标题）",
    )
    p.add_argument(
        "-f",
        "--file",
        dest="file",
        help="从文件读取研究描述",
    )
    p.add_argument(
        "-t",
        "--title",
        dest="title",
        default=None,
        help="可选：手动指定综述中的研究题目；省略则由模型从描述中提炼 research_topic",
    )
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="跳过人工确认，直接生成综述",
    )
    p.add_argument(
        "--inspect-openalex",
        action="store_true",
        help="仅做意图解析并抓取 OpenAlex 调试信息，写入项目根目录 openalex_inspect.json 后退出",
    )
    args = p.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            desc = fh.read()
    elif args.description:
        desc = args.description
    else:
        desc = sys.stdin.read()
    desc = (desc or "").strip()
    if not desc:
        p.print_help()
        print("\n错误：请提供研究描述（参数、--file 或 stdin）。", file=sys.stderr)
        return 2

    if args.inspect_openalex:
        try:
            cfg = load_settings()
            intent = run_intent_step(cfg, desc)
            payload = inspect_openalex_debug(cfg, intent)
            out_path = write_openalex_inspect_json(payload)
            print(f"已写入 OpenAlex 调试 JSON：{out_path}")
            print("请打开该文件查看：request_url、meta、各条 results 的 language/title。")
        except Exception as e:
            print(f"运行失败：{e}", file=sys.stderr)
            return 1
        return 0

    try:
        out = run_full_pipeline(
            desc,
            research_title=args.title,
            skip_confirm=args.yes,
        )
    except Exception as e:
        print(f"运行失败：{e}", file=sys.stderr)
        return 1

    if out.get("cancelled"):
        print("已取消，未生成综述。")
        return 0

    print("\n" + "=" * 60 + "\n【国内外研究现状】\n" + "=" * 60 + "\n")
    print(out["review_text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
