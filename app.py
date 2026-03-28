"""
Web 服务入口：Flask 提供前端页面与 API。
运行：python app.py
部署：支持 Zeabur、Railway 等云平台（使用 PORT 环境变量）
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from literature_review.config import load_settings
from literature_review.pipeline import (
    resolve_research_title,
    run_intent_step,
    run_writing_step,
    select_top_en_only,
)
from literature_review.translate import apply_zh_fields, translate_works_to_zh

app = Flask(__name__, static_folder="static")
PROJECT_ROOT = Path(__file__).resolve().parent


def _beta_token_expected() -> str:
    """非空时，/api/search 与 /api/generate 需携带相同口令（见 _require_beta_access）。"""
    return (os.environ.get("BETA_ACCESS_TOKEN") or "").strip()


def _token_from_request() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Beta-Access-Token") or "").strip()


def _require_beta_access():
    """若配置了 BETA_ACCESS_TOKEN，则校验请求头；未配置则不校验（便于本地开发）。"""
    expected = _beta_token_expected()
    if not expected:
        return None
    if _token_from_request() != expected:
        return jsonify({"error": "内测口令未提供或错误"}), 401
    return None


def _serialize_work(w: dict) -> dict:
    """剔除 raw 等大字段，便于 JSON 传输。"""
    out = {
        "openalex_id": w.get("openalex_id"),
        "title": w.get("title") or "",
        "abstract": w.get("abstract") or "",
        "publication_year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count", 0),
        "citation_text": w.get("citation_text") or "",
    }
    if w.get("title_zh") is not None:
        out["title_zh"] = w.get("title_zh") or ""
    if w.get("abstract_zh") is not None:
        out["abstract_zh"] = w.get("abstract_zh") or ""
    return out


def _deserialize_work(w: dict) -> dict:
    """前端传回的 works 需包含撰写所需字段。"""
    return {
        "openalex_id": w.get("openalex_id"),
        "title": w.get("title") or "",
        "abstract": w.get("abstract") or "",
        "publication_year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count", 0),
        "citation_text": w.get("citation_text") or "",
    }


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    """意图解析 + 文献检索，返回研究主题与入选文献。"""
    denied = _require_beta_access()
    if denied is not None:
        return denied
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "请提供研究描述"}), 400

    try:
        settings = load_settings()
        intent = run_intent_step(settings, description)
        research_topic = resolve_research_title(intent, data.get("title"))
        result = select_top_en_only(settings, intent, return_candidates=15)
        works, candidates = result

        translate_on = data.get("translate_literature", True)
        if translate_on:
            seen: set[str] = set()
            unique: list[dict] = []
            for w in works + candidates:
                oid = (w.get("openalex_id") or "").strip()
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                unique.append(w)
            zh_map = translate_works_to_zh(settings, unique)
            apply_zh_fields(works, zh_map)
            apply_zh_fields(candidates, zh_map)

        return jsonify({
            "research_topic": research_topic,
            "works": [_serialize_work(w) for w in works],
            "candidates": [_serialize_work(w) for w in candidates],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """根据确认的文献生成国内外研究现状。"""
    denied = _require_beta_access()
    if denied is not None:
        return denied
    data = request.get_json(silent=True) or {}
    research_title = (data.get("research_title") or "").strip()
    raw_works = data.get("works") or []
    if not research_title:
        return jsonify({"error": "请提供研究题目"}), 400
    if not raw_works:
        return jsonify({"error": "请提供文献列表"}), 400

    works = [_deserialize_work(w) for w in raw_works]
    try:
        settings = load_settings()
        review_text = run_writing_step(settings, research_title, works)
        return jsonify({"review_text": review_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main():
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    # 云端部署（Zeabur 等会设置 PORT）需 host=0.0.0.0 以监听所有接口
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
