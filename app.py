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

app = Flask(__name__, static_folder="static")
PROJECT_ROOT = Path(__file__).resolve().parent


def _serialize_work(w: dict) -> dict:
    """剔除 raw 等大字段，便于 JSON 传输。"""
    return {
        "openalex_id": w.get("openalex_id"),
        "title": w.get("title") or "",
        "abstract": w.get("abstract") or "",
        "publication_year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count", 0),
        "citation_text": w.get("citation_text") or "",
    }


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
