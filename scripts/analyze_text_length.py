"""
scripts/analyze_text_length.py
Measures how long the extracted text of the corpus's HTML pages is. The result helps choose when a page fetched statically should
count as too short to be complete, so that it is worth rendering in a browser. Reads local files only, sends NO request, calls NO LLM,
and never writes under the corpus directory.

    python scripts/analyze_text_length.py                                  # dry-run: counts what it would read, writes nothing
    python scripts/analyze_text_length.py --run --out DIR                  # computes, writes summary.json, by_subdomain.tsv, shortest.tsv to DIR
    python scripts/analyze_text_length.py --run --out DIR --recheck 20     # also re-extracts up to 20 sampled raw pages per subdomain
    python scripts/analyze_text_length.py --run --out DIR --flags          # also crosses the lengths with the crawler's saved framework flags
    python scripts/analyze_text_length.py --run --out DIR --band 30:100 --band 0:50:oic   # also samples pages in a length band, optionally one subdomain
    python scripts/analyze_text_length.py --run --out DIR --size           # also compares short pages' raw HTML size, taken from map.json

Called by: a person, by hand. Nothing imports it.
Reads: <corpus>/<subdomain>/extracted_texts.jsonl for every subdomain. With --recheck also <corpus>/<subdomain>/map.json and the saved raw
HTML files it points to. With --flags also <corpus>/<subdomain>/js_queue.jsonl. With --size also map.json, for the file_size it records
for each page (the raw HTML files themselves are not opened). All of them are opened for reading only.
Writes: only the files in --out. The script refuses an --out that lies inside the corpus directory.
Last line of stdout: a one-line JSON summary of the key numbers, so a caller can read it without parsing the tables.

Why it reads the jsonl first: it is the text the earlier extraction produced from the crawler's static downloads, so its length is the
nearest stand-in for what a static fetch yields today. --recheck exists because the extractor may have changed since the jsonl was
written, so a sample is extracted again with the current extractor and compared.

What it cannot show: the corpus was crawled once, long ago. A short page here may be a real short page, a redirect, an error page or a
shell that needs JavaScript, and nothing in this script tells them apart. Only a few subdomains have a known label (see WATCH).
"""

from __future__ import annotations

import argparse
import heapq
import json
import random
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True      # the script and the modules it imports must leave no cache files behind
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Candidate cut-offs, in characters. 50 comes from an earlier manual check by the crawler's authors and 64 is the length of one page
# that check confirmed as JavaScript-rendered, so both are facts about that check. The others are only a spread to show the shape.
THRESHOLDS = (20, 30, 50, 64, 100, 150, 200, 300, 500)

# Subdomains with a known outcome. The first three were confirmed by an earlier crawler check as having detail pages that need
# JavaScript. oic is included because its staff page returned only 37 characters when fetched statically, and nothing else is known.
KNOWN_JS = ("x", "cpbae", "gcit")
WATCH = KNOWN_JS + ("oic",)

# Raw HTML sizes in bytes at which to count pages. These are choices. One page of the known JavaScript subdomain x was 178 KB of HTML
# for 11 characters of text according to the crawler's own report, which is a fact about that one page and the reason these sit near it.
SIZE_CUTS = (20_000, 50_000, 100_000)

PERCENTILES = (1, 5, 10, 25, 50, 75, 90)
SHORTEST_ROWS = 300                 # a choice, enough to read through by eye without drowning in rows
PREVIEW_CHARS = 60
SEED = 0                            # fixed so that a re-run samples the same pages


def fail(message: str, fix: str) -> None:
    print(f"error: {message}")
    print(f"fix: {fix}")
    sys.exit(2)


def visible_len(text: str) -> int:
    """Characters that are not whitespace. The live comparison also collapses whitespace, so this is close to its length."""
    return len(re.sub(r"\s+", "", text or ""))


def nonempty_lines(text: str) -> int:
    return sum(1 for line in (text or "").splitlines() if line.strip())


def percentile(sorted_values: list[int], p: int) -> int:
    """Nearest-rank percentile of an already sorted list. Returns 0 for an empty list."""
    if not sorted_values:
        return 0
    rank = max(1, -(-p * len(sorted_values) // 100))       # ceiling without importing math
    return sorted_values[min(rank, len(sorted_values)) - 1]


def stat_signature(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_size, st.st_mtime_ns


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def read_jsonl_html(path: Path) -> tuple[list[dict], int]:
    """HTML records of one extracted_texts.jsonl, plus the number of lines that could not be parsed."""
    rows: list[dict] = []
    bad = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if rec.get("source_type") == "html":
                rows.append(rec)
    return rows, bad


def parse_band(spec: str) -> tuple[int, int, str | None]:
    """'LOW:HIGH' or 'LOW:HIGH:SUBDOMAIN' -> (low, high, subdomain or None). A page is in the band when low <= length < high."""
    parts = spec.split(":")
    if len(parts) not in (2, 3) or not parts[0].isdigit() or not parts[1].isdigit():
        fail(f"bad --band value: {spec}", "use LOW:HIGH or LOW:HIGH:SUBDOMAIN, for example 30:100 or 0:50:oic")
    return int(parts[0]), int(parts[1]), (parts[2] if len(parts) == 3 else None)


def load_flagged_urls(corpus: Path, sub: str, sigs: dict[Path, tuple[int, int]]) -> set[str]:
    """URLs the crawler's own scan saved with at least one framework fingerprint. A page that is absent was not flagged, was too small
    for the scan to judge, or was never scanned, so absence is weaker evidence than presence."""
    path = corpus / sub / "js_queue.jsonl"
    if not path.is_file():
        return set()
    sigs[path] = stat_signature(path)
    flagged: set[str] = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("fingerprints") and rec.get("url"):
                flagged.add(rec["url"])
    return flagged


def size_group(sub: str) -> str:
    return "known_js" if sub in KNOWN_JS else ("oic" if sub == "oic" else "other")


def load_sizes(corpus: Path, sub: str, sigs: dict[Path, tuple[int, int]]) -> dict[str, int]:
    """url -> raw HTML size in bytes, from the file_size the crawler recorded in map.json. The HTML files are not opened."""
    path = corpus / sub / "map.json"
    if not path.is_file():
        return {}
    sigs[path] = stat_signature(path)
    with open(path, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    return {e["url"]: e["file_size"] for e in entries
            if isinstance(e, dict) and e.get("url") and isinstance(e.get("file_size"), int)}


def recheck_sample(corpus: Path, sub: str, records: list[dict], per_sub: int, sigs: dict[Path, tuple[int, int]]) -> dict:
    """Extracts up to per_sub sampled raw pages again with the current extractor and compares their length with the jsonl's."""
    from rag.preprocess import extract_html_bytes       # imported here so that a dry-run needs none of the HTML libraries

    map_path = corpus / sub / "map.json"
    if not map_path.is_file():
        return {"sampled": 0, "missing_map": True}
    sigs[map_path] = stat_signature(map_path)
    with open(map_path, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    saved = {e.get("url"): e.get("saved_path") for e in entries if isinstance(e, dict) and e.get("saved_path")}
    pool = sorted(r["url"] for r in records if r.get("url") in saved)
    sample = random.Random(SEED).sample(pool, min(per_sub, len(pool)))
    old_len = {r["url"]: visible_len(r.get("text", "")) for r in records}
    out = {"sampled": 0, "missing_file": 0, "identical": 0, "new_shorter_10pct": 0, "new_longer_10pct": 0, "ratios": []}
    for url in sample:
        raw_path = ROOT / saved[url]
        if not raw_path.is_file():
            out["missing_file"] += 1
            continue
        sigs[raw_path] = stat_signature(raw_path)
        with open(raw_path, "rb") as fh:
            new = visible_len(extract_html_bytes(fh.read(), url))
        old = old_len[url]
        out["sampled"] += 1
        if new == old:
            out["identical"] += 1
        elif old and new < 0.9 * old:
            out["new_shorter_10pct"] += 1
        elif old and new > 1.1 * old:
            out["new_longer_10pct"] += 1
        if old:
            out["ratios"].append(round(new / old, 3))
    ratios = sorted(out.pop("ratios"))
    out["median_new_over_old"] = ratios[len(ratios) // 2] if ratios else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure the length of extracted HTML text in the corpus (read-only).")
    ap.add_argument("--corpus", default=str(ROOT / "output"), help="corpus directory (default: output/ in the repository)")
    ap.add_argument("--run", action="store_true", help="compute and write the result files (without it, only a dry-run)")
    ap.add_argument("--out", help="directory for the result files, must not be inside the corpus")
    ap.add_argument("--recheck", type=int, default=0, help="re-extract up to N sampled raw pages per subdomain (0 = off)")
    ap.add_argument("--flags", action="store_true", help="cross the lengths with the crawler's saved framework fingerprints")
    ap.add_argument("--size", action="store_true", help="compare the raw HTML size of short pages (from map.json) across groups")
    ap.add_argument("--band", action="append", default=[], help="LOW:HIGH[:SUBDOMAIN], sample pages in that length band (repeatable)")
    ap.add_argument("--band-rows", type=int, default=40, help="rows per band sample (default 40, a choice that is easy to read through)")
    args = ap.parse_args()
    bands = [parse_band(b) for b in args.band]

    corpus = Path(args.corpus)
    if not corpus.is_dir():
        fail(f"corpus directory not found: {corpus}", "pass --corpus with the directory that holds one folder per subdomain")
    subs = sorted(p.name for p in corpus.iterdir() if (p / "extracted_texts.jsonl").is_file())
    if not subs:
        fail("no extracted_texts.jsonl under the corpus directory", "check that --corpus points at the corpus root")

    if not args.run:
        total = sum((corpus / s / "extracted_texts.jsonl").stat().st_size for s in subs)
        print(f"dry-run: would read {len(subs)} extracted_texts.jsonl files ({total / 1e6:.1f} MB) under {corpus}")
        print(f"dry-run: recheck sample per subdomain = {args.recheck}, thresholds = {list(THRESHOLDS)}")
        print(json.dumps({"mode": "dry-run", "subdomains": len(subs), "jsonl_bytes": total}))
        return

    if not args.out:
        fail("--run needs --out", "pass --out with a directory outside the corpus")
    out_dir = Path(args.out)
    if is_inside(out_dir, corpus):
        fail(f"--out is inside the corpus: {out_dir}", "choose a directory outside the corpus directory")
    out_dir.mkdir(parents=True, exist_ok=True)

    sigs: dict[Path, tuple[int, int]] = {}
    lengths: list[int] = []
    per_sub: dict[str, list[int]] = {}
    one_line_flags: list[tuple[int, bool]] = []
    shortest: list[tuple[int, str, str, int, str]] = []
    bad_lines = 0
    rechecks: dict[str, dict] = {}
    # For --flags: per subdomain, how many pages are shorter than each cut-off, and how many of those the crawler also flagged.
    flag_table = {t: {"short": 0, "short_and_flagged": 0, "by_sub": {}} for t in THRESHOLDS}
    flagged_total = 0
    # For --band: a reservoir sample per band, so one pass over the files is enough and a re-run gives the same rows.
    rng = random.Random(SEED)
    reservoirs: dict[tuple, list] = {b: [] for b in bands}
    band_seen: dict[tuple, int] = {b: 0 for b in bands}
    # For --size: (length, raw HTML bytes) of every page under 100 characters, per group, and for comparison how common large HTML is
    # among pages of 300 characters or more, which are not suspected of missing content.
    size_short: dict[str, list[tuple[int, int]]] = {"known_js": [], "oic": [], "other": []}
    size_base = {g: {"pages": 0, **{c: 0 for c in SIZE_CUTS}} for g in size_short}

    for sub in subs:
        path = corpus / sub / "extracted_texts.jsonl"
        sigs[path] = stat_signature(path)
        rows, bad = read_jsonl_html(path)
        bad_lines += bad
        flagged = load_flagged_urls(corpus, sub, sigs) if args.flags else set()
        sizes = load_sizes(corpus, sub, sigs) if args.size else {}
        vals = []
        for rec in rows:
            text = rec.get("text", "")
            n = visible_len(text)
            lines = nonempty_lines(text)
            url = rec.get("url", "")
            vals.append(n)
            one_line_flags.append((n, lines <= 1))
            preview = re.sub(r"\s+", " ", text).strip()[:PREVIEW_CHARS]
            shortest.append((n, sub, url, lines, preview))
            if args.flags:
                is_flagged = url in flagged
                flagged_total += is_flagged
                for t in THRESHOLDS:
                    if n < t:
                        flag_table[t]["short"] += 1
                        if is_flagged:
                            flag_table[t]["short_and_flagged"] += 1
                            flag_table[t]["by_sub"][sub] = flag_table[t]["by_sub"].get(sub, 0) + 1
            if args.size and url in sizes:
                group = size_group(sub)
                if n < 100:
                    size_short[group].append((n, sizes[url]))
                elif n >= 300:
                    size_base[group]["pages"] += 1
                    for c in SIZE_CUTS:
                        size_base[group][c] += sizes[url] >= c
            for b in bands:
                if b[0] <= n < b[1] and (b[2] is None or b[2] == sub):
                    band_seen[b] += 1
                    item = (sub, n, lines, url, preview)
                    if len(reservoirs[b]) < args.band_rows:
                        reservoirs[b].append(item)
                    else:
                        j = rng.randrange(band_seen[b])
                        if j < args.band_rows:
                            reservoirs[b][j] = item
        shortest = heapq.nsmallest(SHORTEST_ROWS, shortest)       # keeps memory flat across 150 subdomains
        per_sub[sub] = vals
        lengths.extend(vals)
        if args.recheck > 0 and rows:
            rechecks[sub] = recheck_sample(corpus, sub, rows, args.recheck, sigs)

    lengths.sort()
    n_all = len(lengths)
    overall = {
        "html_pages": n_all,
        "percentiles": {f"p{p}": percentile(lengths, p) for p in PERCENTILES},
        "below": {str(t): {"count": sum(1 for v in lengths if v < t), "share": round(sum(1 for v in lengths if v < t) / n_all, 5)}
                  for t in THRESHOLDS},
    }
    # Whether the short pages are one-line shells is the pattern the known JavaScript pages show, so it is worth counting.
    for t in (50, 100):
        short = [one for n, one in one_line_flags if n < t]
        overall["below"][str(t)]["one_line_share"] = round(sum(short) / len(short), 3) if short else None

    watch = {}
    for sub in WATCH:
        vals = sorted(per_sub.get(sub, []))
        watch[sub] = {
            "html_pages": len(vals),
            "min": vals[0] if vals else None, "median": percentile(vals, 50), "max": vals[-1] if vals else None,
            "below": {str(t): sum(1 for v in vals if v < t) for t in (30, 50, 64, 100, 200)},
        }

    rows_tsv = ["subdomain\thtml_pages\tp10\tmedian\tshare_below_50\tshare_below_100"]
    for sub in subs:
        vals = sorted(per_sub[sub])
        if not vals:
            continue
        rows_tsv.append(f"{sub}\t{len(vals)}\t{percentile(vals, 10)}\t{percentile(vals, 50)}\t"
                        f"{sum(1 for v in vals if v < 50) / len(vals):.4f}\t{sum(1 for v in vals if v < 100) / len(vals):.4f}")
    (out_dir / "by_subdomain.tsv").write_text("\n".join(rows_tsv) + "\n", encoding="utf-8")

    short_tsv = ["rank\tsubdomain\tvisible_len\tnonempty_lines\turl\tpreview"]
    for i, (n, sub, url, lines, preview) in enumerate(sorted(shortest), 1):
        short_tsv.append(f"{i}\t{sub}\t{n}\t{lines}\t{url}\t{preview.replace(chr(9), ' ')}")
    (out_dir / "shortest.tsv").write_text("\n".join(short_tsv) + "\n", encoding="utf-8")

    flags_summary = None
    if args.flags:
        flags_summary = {"flagged_pages_total": flagged_total, "by_threshold": {}}
        for t in THRESHOLDS:
            row = flag_table[t]
            top = sorted(row["by_sub"].items(), key=lambda kv: -kv[1])[:8]
            flags_summary["by_threshold"][str(t)] = {
                "short": row["short"], "short_and_flagged": row["short_and_flagged"],
                "share_of_short_that_is_flagged": round(row["short_and_flagged"] / row["short"], 4) if row["short"] else None,
                "top_subdomains_of_short_and_flagged": top,
            }

    size_summary = None
    if args.size:
        size_summary = {"cuts_bytes": list(SIZE_CUTS), "short": {}, "long_pages_for_comparison": {}}
        for limit in (50, 100):
            size_summary["short"][str(limit)] = {}
            for group, items in size_short.items():
                chosen = sorted(sz for n, sz in items if n < limit)
                size_summary["short"][str(limit)][group] = {
                    "pages": len(chosen),
                    "html_bytes_p10": percentile(chosen, 10), "html_bytes_median": percentile(chosen, 50), "html_bytes_p90": percentile(chosen, 90),
                    "share_at_least": {str(c): (round(sum(1 for s in chosen if s >= c) / len(chosen), 4) if chosen else None) for c in SIZE_CUTS},
                    "count_at_least": {str(c): sum(1 for s in chosen if s >= c) for c in SIZE_CUTS},
                }
        for group, base in size_base.items():
            pages = base["pages"]
            size_summary["long_pages_for_comparison"][group] = {
                "pages": pages,
                "share_at_least": {str(c): (round(base[c] / pages, 4) if pages else None) for c in SIZE_CUTS},
            }

    band_summary = []
    for b in bands:
        name = f"band_{b[0]}_{b[1]}" + (f"_{b[2]}" if b[2] else "") + ".tsv"
        lines_out = ["subdomain\tvisible_len\tnonempty_lines\turl\tpreview"]
        for sub, n, lines, url, preview in sorted(reservoirs[b], key=lambda r: (r[1], r[0], r[3])):
            lines_out.append(f"{sub}\t{n}\t{lines}\t{url}\t{preview.replace(chr(9), ' ')}")
        (out_dir / name).write_text("\n".join(lines_out) + "\n", encoding="utf-8")
        band_summary.append({"band": f"{b[0]}:{b[1]}" + (f":{b[2]}" if b[2] else ""), "pages_in_band": band_seen[b],
                             "rows_written": len(reservoirs[b]), "file": name})

    # A page that was only read must look exactly as it did before. This catches an accidental write by anything this run touched.
    changed = [str(p) for p, sig in sigs.items() if stat_signature(p) != sig]
    recheck_summary = None
    if rechecks:
        keys = ("sampled", "missing_file", "identical", "new_shorter_10pct", "new_longer_10pct")
        recheck_summary = {k: sum(r.get(k, 0) for r in rechecks.values()) for k in keys}
        recheck_summary["subdomains_without_map"] = sum(1 for r in rechecks.values() if r.get("missing_map"))
        recheck_summary["per_subdomain"] = {s: rechecks[s] for s in WATCH if s in rechecks}

    summary = {
        "corpus": str(corpus), "subdomains": len(subs), "unparsable_jsonl_lines": bad_lines,
        "overall": overall, "watch": watch, "recheck": recheck_summary, "flags": flags_summary, "size": size_summary,
        "bands": band_summary,
        "files_read": len(sigs), "corpus_files_changed_during_run": changed,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"html pages: {n_all}   subdomains: {len(subs)}   files read: {len(sigs)}   changed during run: {len(changed)}")
    print("percentiles:", overall["percentiles"])
    for t in THRESHOLDS:
        b = overall["below"][str(t)]
        print(f"  below {t:>3} chars: {b['count']:>7}  ({b['share'] * 100:6.3f}%)")
    print(json.dumps({"html_pages": n_all, "p5": overall["percentiles"]["p5"], "p50": overall["percentiles"]["p50"],
                      "below_50_share": overall["below"]["50"]["share"], "corpus_files_changed": len(changed)}))


if __name__ == "__main__":
    main()
