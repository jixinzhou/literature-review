# Gunicorn 配置：文献综述生成需调用 AI，单次请求可能 1–3 分钟
# 必须提高 timeout，否则 worker 会被提前杀死
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 1
timeout = 300  # 秒，覆盖默认 30 秒
keepalive = 60
