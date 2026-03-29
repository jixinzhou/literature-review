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
    #: 火山引擎：文献标题/摘要「一键翻译」用（TranslateText）
    volc_access_key_id: str = ""
    volc_secret_access_key: str = ""
    openalex_email: str | None = None
    openalex_base_url: str = "https://api.openalex.org"
    #: 英文候选池目标条数（用于 OpenAlex 聚合后再排序取 TOP_K_EN）
    fetch_pool_size: int = 50
    top_k_en: int = 15
    top_k_zh: int = 5
    use_ai_selection: bool = True  # 是否用 AI 按标题筛选文献


def _qwen_key_missing_message() -> str:
    env_path = _PROJECT_ROOT / ".env"
    ex_path = _PROJECT_ROOT / ".env.example"
    return (
        "未设置 QWEN_API_KEY（意图解析与综述生成需要通义千问）。\n"
        f"- 请在项目根目录创建或编辑：{env_path}\n"
        f"  （可将 {ex_path} 复制为 .env，再填写 QWEN_API_KEY；仅改 .env.example 不会生效）\n"
        "- 变量名须为 QWEN_API_KEY=你的密钥，勿加引号或多余空格。"
    )


class QwenNotConfiguredError(RuntimeError):
    """缺少 QWEN_API_KEY：HTTP API 返回简短文案，detail 写入日志。"""

    short_message = (
        "未配置通义千问密钥：请在项目根目录创建或编辑 .env，添加 "
        "QWEN_API_KEY=你的密钥 后重启服务。"
    )

    def __init__(self) -> None:
        self.detail = _qwen_key_missing_message()
        super().__init__(self.short_message)


def _volc_key_missing_message() -> str:
    env_path = _PROJECT_ROOT / ".env"
    return (
        "未设置火山引擎翻译密钥。\n"
        f"- 请在项目根目录编辑：{env_path}\n"
        "- 设置 VOLC_ACCESS_KEY_ID 与 VOLC_SECRET_ACCESS_KEY。"
    )


class VolcTranslateNotConfiguredError(RuntimeError):
    """缺少火山翻译密钥。"""

    short_message = (
        "未配置火山翻译密钥：请在 .env 中设置 VOLC_ACCESS_KEY_ID 与 "
        "VOLC_SECRET_ACCESS_KEY 后重试。"
    )

    def __init__(self) -> None:
        self.detail = _volc_key_missing_message()
        super().__init__(self.short_message)


def load_settings() -> Settings:
    """加载配置；QWEN_API_KEY 可为空（仅「一键翻译」等可不依赖通义千问）。"""
    key = os.getenv("QWEN_API_KEY", "").strip()
    email = os.getenv("OPENALEX_EMAIL", "").strip() or None
    return Settings(
        qwen_api_key=key,
        qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
        qwen_intent_model=os.getenv("QWEN_INTENT_MODEL", "qwen-plus"),
        qwen_writing_model=os.getenv("QWEN_WRITING_MODEL", "qwen-plus"),
        volc_access_key_id=os.getenv("VOLC_ACCESS_KEY_ID", "").strip(),
        volc_secret_access_key=os.getenv("VOLC_SECRET_ACCESS_KEY", "").strip(),
        openalex_email=email,
        openalex_base_url=os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org").rstrip("/"),
        fetch_pool_size=int(os.getenv("FETCH_POOL_SIZE", "50")),
        top_k_en=int(os.getenv("TOP_K_EN", "15")),
        top_k_zh=int(os.getenv("TOP_K_ZH", "5")),
        use_ai_selection=os.getenv("USE_AI_SELECTION", "true").lower() in ("1", "true", "yes"),
    )


def ensure_qwen_configured(settings: Settings) -> None:
    """在调用意图解析、综述生成等需通义千问的流程前调用。"""
    if not (settings.qwen_api_key or "").strip():
        raise QwenNotConfiguredError()
