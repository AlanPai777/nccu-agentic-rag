"""
rag/live/compare.py
normalize() + compare(): decide whether a live page differs from the snapshot (§5.2).

Over-normalizing hides real changes, under-normalizing makes every page "different", so
VOLATILE_PATTERNS only holds fields confirmed to change per visit (P0: osa 點擊數, www.lib 瀏覽數; P1: cashier 頁尾 瀏覽人次).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from rag.agent_tools import extract_form_ids

# Page-view counters. Whole-line counters are dropped; inline "label: number" pairs are cut out.
VOLATILE_PATTERNS = [
    # number optional: a JS-filled counter is an empty "瀏覽數:" in static HTML (P1, www.lib)
    re.compile(r"^\W*(?:點擊數|瀏覽數|瀏覽次數|瀏覽人次|點閱數|點閱次數|人氣)\s*[:：]?\s*[\d,]*\W*$"),
    # <noscript> text appears in static HTML only, never in the rendered snapshot (P1, www.lib)
    re.compile(r"^您的瀏覽器不支援\s*JavaScript"),
]
VOLATILE_INLINE = re.compile(r"(?:點擊數|瀏覽數|瀏覽次數|瀏覽人次|參觀人次|訪客人次|點閱數|點閱次數)\s*[:：]\s*[\d,]+(?:\s*[人次])?")

EXT_RE = re.compile(r"(?<!\d)\d{5}(?!\d)")


def normalize(text: str) -> str:
    out = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t　\xa0]+", " ", line).strip()
        if not line or any(p.match(line) for p in VOLATILE_PATTERNS):
            continue
        line = VOLATILE_INLINE.sub("", line).strip()
        if line:
            out.append(line)
    return "\n".join(out)


@dataclass
class Comparison:
    same: bool
    similarity: float
    forms_added: list[str] = field(default_factory=list)
    forms_removed: list[str] = field(default_factory=list)
    exts_added: list[str] = field(default_factory=list)
    exts_removed: list[str] = field(default_factory=list)
    lines_added: list[str] = field(default_factory=list)      # capped samples, for logs
    lines_removed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.same:
            return "same"
        parts = [f"similarity={self.similarity:.3f}"]
        for label, v in (("forms+", self.forms_added), ("forms-", self.forms_removed),
                         ("ext+", self.exts_added), ("ext-", self.exts_removed)):
            if v:
                parts.append(f"{label}{','.join(v)}")
        parts.append(f"lines +{len(self.lines_added)}/-{len(self.lines_removed)}")
        return " ".join(parts)


def _delta(a: set[str], b: set[str]) -> tuple[list[str], list[str]]:
    return sorted(b - a), sorted(a - b)


def compare(snapshot: str, live: str, sample: int = 6) -> Comparison:
    a, b = normalize(snapshot), normalize(live)
    if a == b:
        return Comparison(same=True, similarity=1.0)
    al, bl = a.split("\n"), b.split("\n")
    sm = difflib.SequenceMatcher(None, al, bl, autojunk=False)
    added, removed = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("replace", "delete"):
            removed += al[i1:i2]
        if op in ("replace", "insert"):
            added += bl[j1:j2]
    fa, fr = _delta(set(extract_form_ids(a)), set(extract_form_ids(b)))
    ea, er = _delta(set(EXT_RE.findall(a)), set(EXT_RE.findall(b)))
    # line-level ratio keeps this cheap on long pages; char-level only when small
    sim = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if len(a) + len(b) < 20_000 else sm.ratio()
    return Comparison(False, sim, fa, fr, ea, er, [x[:120] for x in added[:sample]], [x[:120] for x in removed[:sample]])
