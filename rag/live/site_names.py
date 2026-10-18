"""
rag/live/site_names.py
Host -> the name a user knows it by ("aca.nccu.edu.tw" -> "教務處"), for the sources panel's group titles (docs/phase_j_live_fetch_plan.md, P8 S3).

The table is derived from docs/contact.csv (the hand-made list of offices and their pages) by experiments/live_spikes/build_site_names.py and
stored in site_names.json, so the running system needs neither the csv nor any code to know the names. A host the table does not know (the
corpus has more sites than the csv lists, and the live fetcher may reach any *.nccu.edu.tw) is shown as its host name.

Derivation, per host:
  1. the csv row whose URL is the site's root ("https://aca.nccu.edu.tw") names the site: 教務處, 學生事務處;
  2. otherwise the first row of that host names it ("商學院(現任院長)" -> "商學院");
  3. the LAST trailing parenthetical is dropped, because those are notes about the page, not part of the unit's name
     ("圖書館(各組聯絡資訊)" -> "圖書館"); an earlier one is kept ("企業管理研究所(MBA學位學程)(策略國際)" -> "企業管理研究所(MBA學位學程)");
  4. OVERRIDES (below) beat all of that.
Only *.nccu.edu.tw hosts are kept: nothing else is ever fetched.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).with_name("site_names.json")
ALLOWED_SUFFIX = "nccu.edu.tw"

# Hand-written exceptions, all agreed with the user (2026-10-18): moltke and www.nccu.edu.tw as proposed, emba and gcit from the review of the
# derived table, es.video from the user's own knowledge of that page (docs/phase_j_live_fetch_plan.md, P8.3 S3).
OVERRIDES = {
    "moltke.nccu.edu.tw": "校務表單服務",                      # not in contact.csv
    "www.nccu.edu.tw": "政大首頁",                             # the csv's first row for this host is 校長室, which would mislead
    "emba.nccu.edu.tw": "商學院經營管理碩士學程（EMBA）",       # derived 商學院, the same as commerce.nccu.edu.tw
    "gcit.nccu.edu.tw": "全球傳播與創新科技碩士學位學程",       # derived name kept a stray note, "(師資陣容)"
    "es.video.nccu.edu.tw": "附屬高級中學（家長會）",            # the site is the parents' association's page, not the school's (user, 2026-10-18)
}

_TRAILING_NOTE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")


def strip_note(name: str) -> str:
    """Drop the last trailing parenthetical (a note about the page); never returns an empty string."""
    return _TRAILING_NOTE.sub("", name).strip() or name.strip()


def read_rows(csv_path: Path | str) -> list[tuple[str, str]]:
    """(name, url) for every csv row whose last cell is a URL. The file has 2- and 3-column rows and a few free-text lines; only the last two
    cells matter."""
    out = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[-1].strip().startswith("http") and row[-2].strip():
                out.append((row[-2].strip(), row[-1].strip()))
    return out


def derive_names(rows: list[tuple[str, str]], overrides: dict[str, str] | None = None) -> dict[str, str]:
    by_host: dict[str, list[tuple[str, str, str]]] = {}
    for name, url in rows:
        p = urlparse(url)
        host = p.netloc.lower()
        if host == ALLOWED_SUFFIX or host.endswith("." + ALLOWED_SUFFIX):
            by_host.setdefault(host, []).append((name, p.path, p.query))
    names = {}
    for host, items in by_host.items():
        root = next((n for n, path, query in items if path in ("", "/") and not query), None)
        names[host] = strip_note(root if root else items[0][0])
    names.update(OVERRIDES if overrides is None else overrides)
    return dict(sorted(names.items()))


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def site_name(host: str) -> str:
    """The user-facing name of a site, or the host itself when the table does not know it. 'www.' is optional (www.lib / lib)."""
    h = (host or "").strip().lower()
    t = _table()
    for cand in (h, h[4:] if h.startswith("www.") else "www." + h):
        if cand in t:
            return t[cand]
    return h
