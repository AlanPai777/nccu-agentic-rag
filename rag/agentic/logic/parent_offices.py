"""
rag/agentic/logic/parent_offices.py
Bare parent units: 教務處 and 學生事務處 are registered in the office index with their site's
HOME PAGE, which lists no staff (教務處 has 9 characters, and 學生事務處 is a news page the contact parser turns into a made-up "contact").
The staff are on the pages of the units under them (教務長室, 註冊組, ... / 學務長室, ...), registered in the same host, in
docs/contact.csv's order (the head's office first).

When such a parent is named:
  * by the USER'S QUESTION -> read the next children, config.PARENT_BATCH_SIZE (3) at a time (the host's rate limiter still paces the requests),
    keep the batch's contacts and stop as soon as one batch has parsed contacts; keep going otherwise. When no child has any, the
    parent falls back to its own page the ordinary way (its home page, then KNOWN_CONTACTS, then nothing).
  * by a PAGE or FORM text -> skipped. A bare "教務處" there is almost always the institution (an announcement, a stamp, a
    regulation's title), and its own page has no staff to look up.

Pure orchestration, no LangGraph state: `read_batch(names)` is supplied by the caller (live pages -> a ContactsResult, or None when
the snapshot is being used), so this runs offline with fakes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("rag.live")


@dataclass
class Expansion:
    order: list[str]                                   # offices in the order the answer should list them
    plain: list[str]                                   # those that still need the ordinary lookup (not expanded children)
    entries: dict[str, dict] = field(default_factory=dict)        # child office -> its finished lookup entry
    live: object | None = None                         # the children's pages merged (live mode), else None
    fallback_notes: dict[str, str] = field(default_factory=dict)  # parent -> note, when none of its children had any contact
    skipped: list[str] = field(default_factory=list)   # parents ignored (named in page text, or next to one of their children)
    expanded: dict[str, list[str]] = field(default_factory=dict)  # parent -> the children whose contacts were kept


def _batch_size() -> int:
    from rag.live import config
    return max(1, config.PARENT_BATCH_SIZE)


def triage(offices: list[str], from_question: bool) -> tuple[list[str], dict[str, tuple[list[dict], list[dict]]], list[str]]:
    """(detected offices minus the skipped parents, {parent: (home records, child records)} to expand, skipped parents)."""
    from rag.skills.office_lookup_skill import parent_children

    detected = list(dict.fromkeys(offices))
    parents = {o: pc for o in detected if (pc := parent_children(o))}
    skipped: list[str] = []
    for parent, (_homes, kids) in list(parents.items()):
        if any(k["name"] in detected for k in kids):   # "教務處 ... 註冊組": the child was named, the parent adds nothing
            skipped.append(parent)
            del parents[parent]
    if not from_question:
        skipped += list(parents)
        parents = {}
    return [o for o in detected if o not in skipped], parents, skipped


def expand_parent_offices(offices: list[str], from_question: bool, skill,
                          read_batch: Callable[[list[str]], object | None]) -> Expansion:
    from rag.live.contacts import merge_contact_results

    detected, parents, skipped = triage(offices, from_question)
    for parent in skipped:
        log.info("contact: parent unit %s not looked up (named in page text, or next to one of its own children)", parent)

    exp = Expansion(order=[], plain=[], skipped=skipped)
    live = None
    for parent, (homes, kids) in parents.items():
        names = [k["name"] for k in kids]
        size = _batch_size()
        kept: list[str] = []
        for i in range(0, len(names), size):
            batch = names[i:i + size]
            try:
                live_b = read_batch(batch)
            except Exception as e:                       # noqa: BLE001 -- the live check is an addition: fall back to the index text
                log.warning("contact: reading %s failed, using the snapshot: %s: %s", batch, type(e).__name__, e)
                live_b = None
            live = merge_contact_results(live, live_b)
            got = skill.run(batch, live=live_b)
            kept = [n for n in batch if got[n].get("contacts") and got[n].get("contacts_source") == "page"]
            log.info("contact: parent %s -> read %s, %d with contacts", parent, batch, len(kept))
            for n in kept:
                got[n]["note"] = "；".join(x for x in (f"「{parent}」是網站首頁、沒有人員資料，改讀同網站的{n}", got[n].get("note")) if x)
                exp.entries[n] = got[n]
            if kept:
                break
        if kept:
            exp.expanded[parent] = [n for n in names if n in exp.entries]
        else:
            exp.fallback_notes[parent] = f"同網站的 {len(names)} 個子單位頁面都沒有解析到人員"
            log.info("contact: parent %s -> none of its %d children had contacts, falling back to its own page", parent, len(names))
    exp.live = live

    for o in detected:
        if o in exp.expanded:
            exp.order += exp.expanded[o]
        else:                                            # an ordinary office, or a parent whose children had nobody
            exp.order.append(o)
            exp.plain.append(o)
    return exp
