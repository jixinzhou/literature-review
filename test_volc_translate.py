"""
独立测试脚本：验证火山引擎翻译密钥与签名是否正常。
用法：python test_volc_translate.py
"""
import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

AK = os.getenv("VOLC_ACCESS_KEY_ID", "").strip()
SK = os.getenv("VOLC_SECRET_ACCESS_KEY", "").strip()

Service = "translate"
Version = "2020-06-01"
Region = "cn-north-1"
Host = "translate.volcengineapi.com"
ContentType = "application/json"


def norm_query(params):
    query = ""
    for key in sorted(params.keys()):
        if type(params[key]) == list:
            for k in params[key]:
                query = (
                    query + quote(key, safe="-_.~") + "=" + quote(k, safe="-_.~") + "&"
                )
        else:
            query = (query + quote(key, safe="-_.~") + "=" + quote(params[key], safe="-_.~") + "&")
    query = query[:-1]
    return query.replace("+", "%20")


def hmac_sha256(key: bytes, content: str):
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def hash_sha256(content: str):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_request(method, date, query, header, ak, sk, action, body):
    credential = {
        "access_key_id": ak,
        "secret_access_key": sk,
        "service": Service,
        "region": Region,
    }
    request_param = {
        "body": body,
        "host": Host,
        "path": "/",
        "method": method,
        "content_type": ContentType,
        "date": date,
        "query": {"Action": action, "Version": Version, **query},
    }
    if body is None:
        request_param["body"] = ""
    x_date = request_param["date"].strftime("%Y%m%dT%H%M%SZ")
    short_x_date = x_date[:8]
    x_content_sha256 = hash_sha256(request_param["body"])
    sign_result = {
        "Host": request_param["host"],
        "X-Content-Sha256": x_content_sha256,
        "X-Date": x_date,
        "Content-Type": request_param["content_type"],
    }
    signed_headers_str = ";".join(
        ["content-type", "host", "x-content-sha256", "x-date"]
    )
    canonical_request_str = "\n".join(
        [request_param["method"].upper(),
         request_param["path"],
         norm_query(request_param["query"]),
         "\n".join(
             [
                 "content-type:" + request_param["content_type"],
                 "host:" + request_param["host"],
                 "x-content-sha256:" + x_content_sha256,
                 "x-date:" + x_date,
             ]
         ),
         "",
         signed_headers_str,
         x_content_sha256,
         ]
    )
    hashed_canonical_request = hash_sha256(canonical_request_str)
    credential_scope = "/".join([short_x_date, credential["region"], credential["service"], "request"])
    string_to_sign = "\n".join(["HMAC-SHA256", x_date, credential_scope, hashed_canonical_request])
    k_date = hmac_sha256(credential["secret_access_key"].encode("utf-8"), short_x_date)
    k_region = hmac_sha256(k_date, credential["region"])
    k_service = hmac_sha256(k_region, credential["service"])
    k_signing = hmac_sha256(k_service, "request")
    signature = hmac_sha256(k_signing, string_to_sign).hex()
    sign_result["Authorization"] = "HMAC-SHA256 Credential={}, SignedHeaders={}, Signature={}".format(
        credential["access_key_id"] + "/" + credential_scope,
        signed_headers_str,
        signature,
    )
    header = {**header, **sign_result}
    r = requests.request(method=method,
                         url="https://{}{}".format(request_param["host"], request_param["path"]),
                         headers=header,
                         params=request_param["query"],
                         data=request_param["body"],
                         )
    return r.json()


def utc_now():
    try:
        from datetime import timezone
        return datetime.datetime.now(timezone.utc)
    except ImportError:
        return datetime.datetime.utcnow()


if __name__ == "__main__":
    print(f"AK (前8位): {AK[:8]}...")
    print(f"SK (前8位): {SK[:8]}...")
    if not AK or not SK:
        print("\n错误：.env 中 VOLC_ACCESS_KEY_ID 或 VOLC_SECRET_ACCESS_KEY 为空！")
        raise SystemExit(1)

    now = utc_now()
    body = json.dumps({
        "TargetLanguage": "zh",
        "TextList": ["Hello world"],
    })
    print(f"\n请求 body: {body}")
    print(f"UTC 时间: {now.strftime('%Y%m%dT%H%M%SZ')}")
    print("正在调用火山翻译 TranslateText ...\n")

    result = make_request("POST", now, {}, {}, AK, SK, "TranslateText", body)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    meta = result.get("ResponseMetadata", {})
    err = meta.get("Error")
    if err:
        print(f"\n失败：{err.get('Code')} - {err.get('Message')}")
    else:
        tlist = result.get("TranslationList", [])
        if tlist:
            print(f"\n翻译成功：{tlist[0].get('Translation')}")
