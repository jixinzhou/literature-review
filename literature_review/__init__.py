"""国内外研究现状自动生成 — 核心库（无前端）。"""

from literature_review.pipeline import (
    inspect_openalex_debug,
    run_full_pipeline,
    write_openalex_inspect_json,
)

__version__ = "0.1.0"

__all__ = [
    "run_full_pipeline",
    "inspect_openalex_debug",
    "write_openalex_inspect_json",
    "__version__",
]
