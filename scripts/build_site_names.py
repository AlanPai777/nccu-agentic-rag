"""
scripts/build_site_names.py
Build rag/live/site_names.json (host -> the name users know it by) from docs/contact.csv. Reads one local file, sends NO request.

    python scripts/build_site_names.py            # dry-run: prints the table and what needs a look, writes nothing
    python scripts/build_site_names.py --write    # writes rag/live/site_names.json (a git-tracked file)

Rules and the hand-written overrides are in rag/live/site_names.py.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag.live import site_names as sn  # noqa: E402

CSV = ROOT / "docs" / "contact.csv"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    write = ap.parse_args().write

    rows = sn.read_rows(CSV)
    derived = sn.derive_names(rows, overrides={})          # what the rules alone give
    final = sn.derive_names(rows)                          # rules + overrides
    print(f"{len(rows)} csv rows -> {len(final)} *.nccu.edu.tw hosts (csv: {CSV.name})\n")

    print("overrides (rule result -> final):")
    for h, name in sn.OVERRIDES.items():
        print(f"  {h:28s} {derived.get(h, '(not in csv)'):30s} -> {name}")

    dup = collections.defaultdict(list)
    for h, n in final.items():
        dup[n].append(h)
    print("\nsame name for more than one host (should be empty):", {n: hs for n, hs in dup.items() if len(hs) > 1} or "none")
    print("names that still contain a parenthesis (part of the unit's name, or a note the rules did not catch):")
    for h, n in final.items():
        if re.search(r"[(（]", n):
            print(f"  {h:28s} {n}")
    print("\nall names:")
    for h, n in final.items():
        print(f"  {h:30s} {n}")

    if write:
        sn.DATA.write_text(json.dumps(final, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {sn.DATA.relative_to(ROOT)} ({len(final)} hosts)")
    else:
        print("\n(dry-run: nothing written; pass --write)")


if __name__ == "__main__":
    main()
