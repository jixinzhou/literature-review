"""
Web 服务入口：Flask 提供前端页面与 API。
运行：python app.py
部署：支持 Zeabur、Railway 等云平台（使用 PORT 环境变量）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session

# 先于 Flask 读取密钥：确保本地 .env 中的 BETA_ACCESS_TOKEN 生效
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()

from literature_review.config import (
    QwenNotConfiguredError,
    VolcTranslateNotConfiguredError,
    ensure_qwen_configured,
    load_settings,
)
from literature_review.pipeline import (
    resolve_research_title,
    run_intent_step,
    run_writing_step,
    select_top_en_only,
)
from literature_review.translate import translate_works_to_zh

app = Flask(__name__, static_folder="static")
PROJECT_ROOT = _PROJECT_ROOT
logger = logging.getLogger("literature-review")
if not logging.root.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# 会话签名：生产环境请设置 FLASK_SECRET_KEY（可与 BETA_ACCESS_TOKEN 不同）
app.secret_key = (
    (os.environ.get("FLASK_SECRET_KEY") or "").strip()
    or (os.environ.get("BETA_ACCESS_TOKEN") or "").strip()
    or "literature-review-dev-only-secret"
)


def _beta_token_expected() -> str:
    """非空时须先通过内测页登录（会话）或请求头携带相同口令（脚本/调试）。"""
    return (os.environ.get("BETA_ACCESS_TOKEN") or "").strip()


def _token_from_request() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Beta-Access-Token") or "").strip()


def _session_beta_ok() -> bool:
    return bool(session.get("beta_ok"))


def _require_beta_access():
    """配置了 BETA_ACCESS_TOKEN 时：须已登录会话，或请求头携带正确口令。"""
    expected = _beta_token_expected()
    if not expected:
        return None
    if _session_beta_ok():
        return None
    if _token_from_request() == expected:
        return None
    return jsonify({"error": "请先输入内测码访问本站，或内测口令错误"}), 401


@app.before_request
def _guard_static_index():
    """禁止绕过门禁直接打开 /static/index.html。"""
    if not _beta_token_expected() or _session_beta_ok():
        return None
    if request.path == "/static/index.html":
        return redirect("/")
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
    if _beta_token_expected() and not _session_beta_ok():
        return send_from_directory(app.static_folder, "gate.html")
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """提交内测码，通过后写入会话 Cookie。"""
    expected = _beta_token_expected()
    if not expected:
        return jsonify({"ok": True, "message": "未启用内测门禁"}), 200
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if code != expected:
        return jsonify({"ok": False, "error": "内测码错误"}), 401
    session["beta_ok"] = True
    return jsonify({"ok": True})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.pop("beta_ok", None)
    return jsonify({"ok": True})


@app.route("/api/auth/status", methods=["GET"])
def api_auth_status():
    exp = _beta_token_expected()
    return jsonify({
        "require_beta": bool(exp),
        "logged_in": _session_beta_ok() if exp else True,
    })


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
        ensure_qwen_configured(settings)
        intent = run_intent_step(settings, description)
        research_topic = resolve_research_title(intent, data.get("title"))
        result = select_top_en_only(settings, intent, return_candidates=15)
        works, candidates = result

        return jsonify({
            "research_topic": research_topic,
            "works": [_serialize_work(w) for w in works],
            "candidates": [_serialize_work(w) for w in candidates],
        })
    except QwenNotConfiguredError as e:
        logger.warning("POST /api/search：%s\n%s", e.short_message, e.detail)
        return jsonify({"error": e.short_message}), 400
    except Exception as e:
        logger.exception("POST /api/search 失败")
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST"])
def api_translate():
    """文献标题/摘要译为中文：由前端「一键翻译」调用（火山引擎 TranslateText）。"""
    denied = _require_beta_access()
    if denied is not None:
        return denied
    data = request.get_json(silent=True) or {}
    raw_works = data.get("works") or []
    raw_candidates = data.get("candidates") or []
    if not raw_works and not raw_candidates:
        return jsonify({"error": "请提供 works 或 candidates"}), 400

    seen: set[str] = set()
    unique: list[dict] = []
    for w in raw_works + raw_candidates:
        if not isinstance(w, dict):
            continue
        oid = (w.get("openalex_id") or "").strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        unique.append(dict(w))

    try:
        settings = load_settings()
        zh_map = translate_works_to_zh(settings, unique)
        return jsonify({"translations": zh_map})
    except VolcTranslateNotConfiguredError as e:
        logger.warning("POST /api/translate：%s\n%s", e.short_message, e.detail)
        return jsonify({"error": e.short_message}), 400
    except Exception as e:
        logger.exception("POST /api/translate 失败")
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
        ensure_qwen_configured(settings)
        review_text = run_writing_step(settings, research_title, works)
        return jsonify({"review_text": review_text})
    except QwenNotConfiguredError as e:
        logger.warning("POST /api/generate：%s\n%s", e.short_message, e.detail)
        return jsonify({"error": e.short_message}), 400
    except Exception as e:
        logger.exception("POST /api/generate 失败")
        return jsonify({"error": str(e)}), 500


def main():
    if not (os.environ.get("BETA_ACCESS_TOKEN") or "").strip():
        print(
            "[literature-review] 未设置 BETA_ACCESS_TOKEN：不会显示内测页，将直接进入主界面。\n"
            "  本地测试内测门禁：在 .env 中增加一行 BETA_ACCESS_TOKEN=你的内测码 后重启 python app.py",
            flush=True,
        )
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    # 云端部署（Zeabur 等会设置 PORT）需 host=0.0.0.0 以监听所有接口
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
