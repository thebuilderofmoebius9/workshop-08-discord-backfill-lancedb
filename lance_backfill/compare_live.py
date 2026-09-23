"""Live per-query comparison against the workshop-05 SQLite/FTS5 index.

Three numbers for one query, computed on the same 3,000 rows:
  ground_truth  plain substring LIKE — how many messages actually contain it
  old_fts5      what the old app's `MATCH` query returns
  lance_*       what this index returns per mode

ponytail: LIKE as ground truth is exact for substrings and blind to synonyms.
That is the honest ceiling — it measures literal recall, not semantic recall.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

CAP = 1000  # stop counting past this; the UI only needs an order of magnitude


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def old_index_counts(db_path: Path, query: str) -> dict[str, int | None]:
    """(ground truth via LIKE, hits via FTS5 MATCH). None = the engine errored."""
    con = _connect(db_path)
    try:
        like = f"%{' '.join(query.replace(chr(0x200b), '').lower().split())}%"
        truth = con.execute(
            "SELECT count(*) c FROM messages WHERE content_searchable LIKE ?", (like,)
        ).fetchone()["c"]
        try:
            fts = con.execute(
                "SELECT count(*) c FROM messages_fts WHERE messages_fts MATCH ?", (query,)
            ).fetchone()["c"]
        except sqlite3.DatabaseError:
            fts = None
        return {"ground_truth": truth, "old_fts5": fts}
    finally:
        con.close()


def lance_literal_count(table, query: str) -> int:
    """Same LIKE ground truth, but read off the Lance table, as a parity check."""
    needle = query.lower()
    contents = table.to_arrow()["content"].to_pylist()
    return sum(1 for c in contents if needle in (c or "").lower())
