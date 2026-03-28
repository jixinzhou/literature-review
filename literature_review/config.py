from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 与「当前工作目录」无关：始终从项目根目录加载 .env（main.py 所在目录的上一级即 literature_review 的包根上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """项目根目录（含 main.py、.env）。"""
    return _PROJECT_ROOT


def _load_env_files() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")
    # 兼容：在仓库根目录运行时，当前目录下的 .env 可覆盖（便于临时覆盖）
    load_dotenv()


_load_env_files()


@dataclass(frozen=True)
class Settings:
    qwen_api_key: str
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_intent_model: str = "qwen-plus"
    qwen_writing_model: str = "qwen-plus"
    #: 文献标题/摘要中译：建议 qwen-flash / qwen-turbo（快、非思考链）；勿用 qwen-max 等做批量翻译
    qwen_translate_model: str = "qwen-flash"
    openalex_email: str | None = None
    openalex_base_url: str = "https://api.openalex.org"
    #: 英文候选池目标条数（用于 OpenAlex 聚合后再排序取 TOP_K_EN）
    fetch_pool_size: int = 50
    top_k_en: int = 15
    top_k_zh: int = 5
    use_ai_selection: bool = True  # 是否用 AI 按标题筛选文献


def load_settings() -> Settings:
    key = os.getenv("QWEN_API_KEY", "").strip()
    if not key:
        env_path = _PROJECT_ROOT / ".env"
        ex_path = _PROJECT_ROOT / ".env.example"
        raise RuntimeError(
            "未设置 QWEN_API_KEY。\n"
            f"- 请在项目根目录创建文件：{env_path}\n"
            f"  （可将 {ex_path} 复制为 .env，再填写 QWEN_API_KEY；仅改 .env.example 不会生效）\n"
            "- 变量名须为 QWEN_API_KEY=你的密钥，勿加引号或多余空格。"
        )
    email = os.getenv("OPENALEX_EMAIL", "").strip() or None
    return Settings(
        qwen_api_key=key,
        qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
        qwen_intent_model=os.getenv("QWEN_INTENT_MODEL", "qwen-plus"),
        qwen_writing_model=os.getenv("QWEN_WRITING_MODEL", "qwen-plus"),
        qwen_translate_model=os.getenv("QWEN_TRANSLATE_MODEL", "qwen-flash"),
        openalex_email=email,
        openalex_base_url=os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org").rstrip("/"),
        fetch_pool_size=int(os.getenv("FETCH_POOL_SIZE", "50")),
        top_k_en=int(os.getenv("TOP_K_EN", "15")),
        top_k_zh=int(os.getenv("TOP_K_ZH", "5")),
        use_ai_selection=os.getenv("USE_AI_SELECTION", "true").lower() in ("1", "true", "yes"),
    )
