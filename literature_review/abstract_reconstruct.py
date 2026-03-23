from __future__ import annotations

from typing import Any


def reconstruct_abstract_from_inverted_index(
    inverted_index: dict[str, list[int]] | None,
) -> str | None:
    """
    将 OpenAlex 的 abstract_inverted_index 还原为可读摘要文本。
    见：https://docs.openalex.org/api-entities/works/work-object#abstract_inverted_index
    """
    if not inverted_index:
        return None
    slots: list[str | None] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            while len(slots) <= pos:
                slots.append(None)
            slots[pos] = word
    if not slots:
        return None
    return " ".join(w for w in slots if w is not None)


def get_work_title(work: dict[str, Any]) -> str:
    t = work.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    dn = work.get("display_name")
    if isinstance(dn, str) and dn.strip():
        return dn.strip()
    return ""
