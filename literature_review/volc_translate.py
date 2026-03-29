"""火山引擎文本翻译 TranslateText（OpenAPI 签名），供文献标题/摘要批量译入中文。

签名算法参照：https://github.com/volcengine/volc-openapi-demos/blob/main/signature/python/sign.py
HTTP 使用 requests（与官方示例一致），避免 httpx 对 URL 的二次编码导致 SignatureDoesNotMatch。
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import quote

import requests as _requests

logger = logging.getLogger(__name__)

_SERVICE = "translate"
_VERSION = "2020-06-01"
_REGION = "cn-north-1"
_HOST = "translate.volcengineapi.com"
_ACTION = "TranslateText"
_CONTENT_TYPE = "application/json"


def _utc_now() -> datetime.datetime:
    try:
        from datetime import timezone
        return datetime.datetime.now(timezone.utc)
    except ImportError:
        return datetime.datetime.utcnow()


def _norm_query(params: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(params.keys()):
        val = params[key]
        if isinstance(val, list):
            for k in val:
                parts.append(
                    quote(key, safe="-_.~") + "=" + quote(str(k), safe="-_.~")
                )
        else:
            parts.append(
                quote(key, safe="-_.~") + "=" + quote(str(val), safe="-_.~")
            )
    return "&".join(parts).replace("+", "%20")


def _hmac_sha256(key: bytes, content: str) -> bytes:
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _hash_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _make_request(
    method: str,
    date: datetime.datetime,
    query: dict[str, Any],
    body: str,
    ak: str,
    sk: str,
) -> dict:
    """构造签名 header 并发送 HTTP 请求，返回 JSON 响应。"""
    request_query = {"Action": _ACTION, "Version": _VERSION, **query}

    x_date = date.strftime("%Y%m%dT%H%M%SZ")
    short_x_date = x_date[:8]
    x_content_sha256 = _hash_sha256(body)

    signed_headers_str = "content-type;host;x-content-sha256;x-date"
    canonical_request_str = "\n".join(
        [
            method.upper(),
            "/",
            _norm_query(request_query),
            "\n".join(
                [
                    "content-type:" + _CONTENT_TYPE,
                    "host:" + _HOST,
                    "x-content-sha256:" + x_content_sha256,
                    "x-date:" + x_date,
                ]
            ),
            "",
            signed_headers_str,
            x_content_sha256,
        ]
    )

    hashed_canonical_request = _hash_sha256(canonical_request_str)
    credential_scope = "/".join([short_x_date, _REGION, _SERVICE, "request"])
    string_to_sign = "\n".join(
        ["HMAC-SHA256", x_date, credential_scope, hashed_canonical_request]
    )

    k_date = _hmac_sha256(sk.encode("utf-8"), short_x_date)
    k_region = _hmac_sha256(k_date, _REGION)
    k_service = _hmac_sha256(k_region, _SERVICE)
    k_signing = _hmac_sha256(k_service, "request")
    signature = _hmac_sha256(k_signing, string_to_sign).hex()

    authorization = "HMAC-SHA256 Credential={}, SignedHeaders={}, Signature={}".format(
        ak + "/" + credential_scope,
        signed_headers_str,
        signature,
    )

    headers = {
        "Host": _HOST,
        "X-Content-Sha256": x_content_sha256,
        "X-Date": x_date,
        "Content-Type": _CONTENT_TYPE,
        "Authorization": authorization,
    }

    r = _requests.request(
        method=method,
        url="https://{}{}".format(_HOST, "/"),
        headers=headers,
        params=request_query,
        data=body,
    )
    r.raise_for_status()
    return r.json()


def translate_text_list(
    access_key_id: str,
    secret_access_key: str,
    text_list: list[str],
    *,
    target_language: str = "zh",
    source_language: str | None = None,
    timeout: float = 60.0,
) -> list[str]:
    """
    调用 TranslateText；TextList 与返回 Translation 顺序一致。
    单请求：列表长度 ≤16，总字符 ≤5000（由调用方控制）。
    """
    if not text_list:
        return []
    ak = (access_key_id or "").strip()
    sk = (secret_access_key or "").strip()

    body_obj: dict[str, Any] = {
        "TargetLanguage": target_language,
        "TextList": text_list,
    }
    if source_language:
        body_obj["SourceLanguage"] = source_language
    body = json.dumps(body_obj, ensure_ascii=False)

    now = _utc_now()
    data = _make_request("POST", now, {}, body, ak, sk)

    meta = data.get("ResponseMetadata") or {}
    err = meta.get("Error")
    if err:
        code = err.get("Code", "")
        msg = err.get("Message", str(err))
        raise RuntimeError(f"火山翻译错误 [{code}]: {msg}")

    tlist = data.get("TranslationList") or []
    out: list[str] = []
    for item in tlist:
        if isinstance(item, dict):
            out.append((item.get("Translation") or "").strip())
        else:
            out.append("")
    if len(out) != len(text_list):
        logger.warning(
            "火山翻译条数与请求不一致: 请求 %d 条, 返回 %d 条，已用空串补齐",
            len(text_list),
            len(out),
        )
    while len(out) < len(text_list):
        out.append("")
    return out[: len(text_list)]
