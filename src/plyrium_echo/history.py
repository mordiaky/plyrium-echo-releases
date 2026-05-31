"""Local dictation history — every transcript, stored only on this machine.

A small SQLite database in the user data dir. Text only (no audio): tiny, fast,
searchable, and private — nothing ever leaves the machine. It's the safety net
for the #1 dictation failure ("I said it, but where did it go?"): you can always
find a past dictation and copy it again.

Thread-safe: the connection is opened with ``check_same_thread=False`` and every
access is serialized by a lock, because writes come from the transcribe thread
while reads come from the UI thread.
"""

from __future__ import annotations

import sqlite3
import threading
import time

from . import paths


class HistoryStore:
    def __init__(self, enabled: bool = True, max_entries: int = 500):
        self.enabled = enabled
        self.max_entries = max(0, int(max_entries))
        self._lock = threading.Lock()
        self._db_path = paths.data_dir() / "history.db"
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entries ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts REAL NOT NULL,"
            " text TEXT NOT NULL,"
            " raw TEXT,"
            " app TEXT,"
            " model TEXT,"
            " words INTEGER)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON entries(ts)")
        self._conn.commit()

    def add(self, text: str, raw: str = "", app: str = "", model: str = "",
            ts: float | None = None) -> None:
        if not self.enabled:
            return
        text = (text or "").strip()
        if not text:
            return
        ts = time.time() if ts is None else ts
        words = len(text.split())
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO entries (ts,text,raw,app,model,words) "
                    "VALUES (?,?,?,?,?,?)",
                    (ts, text, raw, app, model, words),
                )
                self._conn.commit()
                self._prune_locked()
        except Exception as exc:  # history must never break dictation
            print(f"[history] add failed: {exc}", flush=True)

    def _prune_locked(self) -> None:
        if self.max_entries <= 0:
            return
        self._conn.execute(
            "DELETE FROM entries WHERE id NOT IN "
            "(SELECT id FROM entries ORDER BY ts DESC LIMIT ?)",
            (self.max_entries,),
        )
        self._conn.commit()

    def list(self, search: str = "", limit: int = 1000) -> list[dict]:
        q = "SELECT id,ts,text,app,model,words FROM entries"
        args: list = []
        if search:
            q += " WHERE text LIKE ?"
            args.append(f"%{search}%")
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        try:
            with self._lock:
                rows = self._conn.execute(q, args).fetchall()
        except Exception:
            return []
        return [dict(id=r[0], ts=r[1], text=r[2], app=r[3], model=r[4], words=r[5])
                for r in rows]

    def get(self, eid: int) -> dict | None:
        try:
            with self._lock:
                r = self._conn.execute(
                    "SELECT id,ts,text,raw,app,model,words FROM entries WHERE id=?",
                    (eid,)).fetchone()
        except Exception:
            return None
        if not r:
            return None
        return dict(id=r[0], ts=r[1], text=r[2], raw=r[3], app=r[4],
                    model=r[5], words=r[6])

    def delete(self, eid: int) -> None:
        try:
            with self._lock:
                self._conn.execute("DELETE FROM entries WHERE id=?", (eid,))
                self._conn.commit()
        except Exception:
            pass

    def clear(self) -> None:
        try:
            with self._lock:
                self._conn.execute("DELETE FROM entries")
                self._conn.commit()
        except Exception:
            pass

    def stats(self) -> dict:
        try:
            with self._lock:
                n, words, first = self._conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(words),0), MIN(ts) FROM entries"
                ).fetchone()
        except Exception:
            n, words, first = 0, 0, None
        return {"entries": n or 0, "words": words or 0, "first_ts": first}
