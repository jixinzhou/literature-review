from __future__ import annotations

import json
import logging
import re
import ssl
import time
from typing import Any

import httpx

from literature_review.config import Settings

logger = logging.getLogger(__name__)


def chat_completion(
    settings: Settings,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    timeout: float = 300.0,
    *,
    extra_body: dict[str, Any] | None = None,
) -> str:
    """OpenAI 兼容 Chat Completions。综述生成耗时长，默认 300 秒超时。含 TLS 断开重试。"""
    url = f"{settings.qwen_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    if extra_body:
        body.update(extra_body)
    _TLS_EXC = (
        httpx.RemoteProtocolError,
        httpx.ConnectError,
        httpx.ReadError,
        ssl.SSLError,
        OSError,
        ConnectionError,
    )
    last_err = None
    data = None
    for attempt in range(5):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
            break
        except _TLS_EXC as e:
            last_err = e
            err_str = str(e).lower()
            is_tls = any(x in err_str for x in ("tls", "ssl", "eof", "closed", "connection"))
            if is_tls and attempt < 4:
                wait = min(60, 5 * (2**attempt))
                logger.warning("TLS/SSL 连接异常，%s 秒后重试（%d/5）: %s", wait, attempt + 1, e)
                time.sleep(wait)
            else:
                raise
    if data is None and last_err:
        raise last_err
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"模型无返回内容: {data}")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        raise RuntimeError("模型返回格式异常")
    return content


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)


def parse_json_strict(text: str) -> dict[str, Any]:
    """从模型输出中解析 JSON（允许外层 ```json 包裹）。"""
    t = text.strip()
    m = _JSON_FENCE.search(t)
    if m:
        t = m.group(1).strip()
    return json.loads(t)
