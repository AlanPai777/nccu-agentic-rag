"""
rag/live/cache.py
Side-channel SQLite cache for live results. It is never written into the git-tracked
output/*/extracted_texts.jsonl, never merged into the corpus. gitignored (rag/live/_cache/).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from rag.live import config

_SCHEMA = """CREATE TABLE IF NOT EXISTS live (
  url TEXT PRIMARY KEY, kind TEXT, final_url TEXT, fetched_at REAL, expires_at REAL,
  status INTEGER, raw_hash TEXT, text_hash TEXT, text TEXT, pdf_path TEXT, tls_unverified INTEGER)"""


@dataclass
class CacheRow:
    url: str
    kind: str
    final_url: str
    fetched_at: float
    status: int
    raw_hash: str
    text_hash: str
    text: str
    pdf_path: str | None
    tls_unverified: bool


class LiveCache:
    def __init__(self, path: Path | str | None = None, clock=time.time):
        path = Path(path or config.CACHE_DB)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(_SCHEMA)
        self.purge_expired()

    def now(self) -> float:
        return self._clock()

    def get(self, url: str) -> CacheRow | None:
        with self._lock:
            r = self._db.execute(
                "SELECT url,kind,final_url,fetched_at,status,raw_hash,text_hash,text,pdf_path,tls_unverified "
                "FROM live WHERE url=? AND expires_at>?", (url, self._clock())).fetchone()
        return CacheRow(*r[:9], bool(r[9])) if r else None

    def put(self, row: CacheRow, ttl: float | None = None) -> None:
        ttl = config.TTL_SECONDS.get(row.kind, config.TTL_SECONDS["page"]) if ttl is None else ttl
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO live VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                row.url, row.kind, row.final_url, row.fetched_at, row.fetched_at + ttl, row.status,
                row.raw_hash, row.text_hash, row.text, row.pdf_path, int(row.tls_unverified)))
            self._db.commit()

    def purge_expired(self) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM live WHERE expires_at<=?", (self._clock(),)).rowcount
            self._db.commit()
        return n
