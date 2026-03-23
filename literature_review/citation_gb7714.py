from __future__ import annotations

from typing import Any

from literature_review.abstract_reconstruct import get_work_title


def format_gb7714_authors(names: list[str], lang_iso: str) -> str:
    """GB/T 7714：著者超过 3 个时著录前 3 个加「等」或「, et al.」。"""
    if not names:
        return "佚名"
    if len(names) <= 3:
        return ", ".join(names)
    a, b, c = names[0], names[1], names[2]
    if lang_iso == "zh":
        return f"{a}, {b}, {c}, 等"
    return f"{a}, {b}, {c}, et al."


def _collect_author_names(work: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for a in work.get("authorships") or []:
        auth = (a or {}).get("author") or {}
        dn = auth.get("display_name")
        if isinstance(dn, str) and dn.strip():
            out.append(dn.strip())
    return out


def _work_type_marker(work: dict[str, Any]) -> str:
    t = (work.get("type") or "").lower()
    if t in ("dissertation",):
        return "D"
    if t in ("book",):
        return "M"
    if t in ("book-chapter",):
        return "M"
    if t in ("proceeding-article", "posted-content"):
        return "C"
    if t in ("report",):
        return "R"
    if t in ("article", "review", "letter", "editorial", "peer-review", "standard", "software"):
        return "J"
    return "J"


def _pages(biblio: dict[str, Any]) -> str:
    fp = biblio.get("first_page")
    lp = biblio.get("last_page")
    if fp and lp:
        return f"{fp}-{lp}"
    if fp:
        return str(fp)
    return ""


def format_citation_gb7714_iso(work: dict[str, Any], lang_iso: str) -> str:
    """
    参考文献条目（GB/T 7714-2015 常见期刊 [J] 等；元数据缺失则省略对应片段）。
    序号 [1] 由上游列表生成，此处不重复。
    """
    names = _collect_author_names(work)
    authors = format_gb7714_authors(names, lang_iso)
    title = get_work_title(work) or "题名不详"
    year = work.get("publication_year")
    year_s = str(year) if year is not None else "出版年不详"

    pl = work.get("primary_location") or {}
    src = pl.get("source") or {}
    journal = ""
    if isinstance(src.get("display_name"), str) and src["display_name"].strip():
        journal = src["display_name"].strip()

    biblio = work.get("biblio") or {}
    volume = biblio.get("volume")
    issue = biblio.get("issue")
    pages = _pages(biblio)

    doi = work.get("doi")
    doi_s = ""
    if isinstance(doi, str) and doi.strip():
        d = doi.replace("https://doi.org/", "").strip()
        doi_s = f"DOI: {d}"

    marker = _work_type_marker(work)

    if marker == "J":
        vol_issue = ""
        if volume and issue:
            vol_issue = f"{volume}({issue})"
        elif volume:
            vol_issue = str(volume)
        page_part = ""
        if pages:
            page_part = f": {pages}"
        jn = journal if journal else "刊名不详"
        tail = f"{jn}, {year_s}"
        if vol_issue:
            tail += f", {vol_issue}"
        tail += page_part
        if doi_s:
            tail += f". {doi_s}"
        return f"{authors}. {title}[J]. {tail}."

    if marker == "D":
        inst = pl.get("institution") or {}
        inst_name = ""
        if isinstance(inst.get("display_name"), str):
            inst_name = inst["display_name"].strip()
        place = "保存地不详"
        if inst_name:
            place = inst_name
        return f"{authors}. {title}[D]. {place}, {year_s}."

    if marker == "C":
        ev = pl.get("venue") or {}
        conf = ""
        if isinstance(ev.get("display_name"), str):
            conf = ev["display_name"].strip()
        page_part = f": {pages}" if pages else ""
        mid = conf or "会议名称不详"
        return f"{authors}. {title}[C]//{mid}. {year_s}{page_part}."

    if marker == "M":
        pub = pl.get("publisher") or {}
        pub_name = ""
        if isinstance(pub.get("display_name"), str):
            pub_name = pub["display_name"].strip()
        tail = f"{pub_name}. {year_s}." if pub_name else f"{year_s}."
        return f"{authors}. {title}[M]. {tail}"

    return f"{authors}. {title}[{marker}]. {year_s}."
