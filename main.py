"""
命令行入口：python main.py "一段话描述你的研究即可" ；可选 -t 手动指定题目
环境变量见 .env.example（QWEN_API_KEY 必填；OpenAlex 可选填 OPENALEX_EMAIL）。
"""

from __future__ import annotations

import sys

from literature_review.pipeline import main_cli

if __name__ == "__main__":
    raise SystemExit(main_cli())
