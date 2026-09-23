"""One runnable check per non-trivial path: redaction, ingest, RRF fusion."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lance_backfill.pipeline import iter_messages, redact, search_hybrid  # noqa: E402
from lance_backfill.compare_live import old_index_counts  # noqa: E402

EXPORT = {
    "guild": {"id": "1", "name": "G"},
    "channels": [
        {
            "id": "10",
            "name": "c",
            "messages": [
                {"id": "100", "author_id": "a", "author_name": "A", "content": "token = hunter2supersecret",
                 "created_at": "2026-09-01T00:00:00+00:00", "edited_at": None, "attachments": [], "events": []},
                {"id": "101", "author_id": "b", "author_name": "B", "content": "สวัสดีครับ",
                 "created_at": "2026-09-01T00:01:00+00:00", "edited_at": "2026-09-01T00:02:00+00:00",
                 "attachments": [{"id": "x"}], "events": []},
            ],
        }
    ],
}


def test_redact():
    safe, hits = redact("ghp_" + "a" * 30 + " and password: letmein99")
    assert hits == 2 and "ghp_" not in safe and "letmein99" not in safe


def test_iter_messages():
    rows = iter_messages(EXPORT)
    assert [r["message_id"] for r in rows] == ["100", "101"]
    assert rows[0]["redactions"] == 1 and "hunter2supersecret" not in rows[0]["content"]
    assert rows[1]["edited"] is True and rows[1]["attachments"] == 1
    assert rows[1]["created_ts"] > 0


class FakeTable:
    """Two disjoint result lists so RRF ordering is unambiguous."""
    fts = [{"message_id": "A", "content": "a"}, {"message_id": "B", "content": "b"}]
    vec = [{"message_id": "B", "content": "b"}, {"message_id": "C", "content": "c"}]


def test_hybrid_rrf(monkeypatch=None):
    import lance_backfill.pipeline as p

    p.search_fts = lambda t, q, l: [dict(r, rank=i + 1) for i, r in enumerate(FakeTable.fts)]
    p.search_vector = lambda t, q, l: [dict(r, rank=i + 1) for i, r in enumerate(FakeTable.vec)]
    rows = p.search_hybrid(None, "q", limit=3)
    # B is in both lists -> must win; every row carries its provenance
    assert rows[0]["message_id"] == "B"
    assert sorted(rows[0]["found_by"]) == ["fts", "vector"]
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_old_index_counts():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "old.sqlite"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE messages (content_searchable TEXT NOT NULL);
            CREATE VIRTUAL TABLE messages_fts USING fts5(content_searchable);
        """)
        rows = [("ค้นหาข้อความเก่าในห้องแชท",), ("ค้นหาข้อความ",), ("unrelated",)]
        con.executemany("INSERT INTO messages VALUES (?)", rows)
        con.executemany("INSERT INTO messages_fts(content_searchable) VALUES (?)", rows)
        con.commit()
        con.close()

        # FTS5's tokenization is stricter than substring LIKE for this Thai text.
        assert old_index_counts(db, "ค้นหาข้อความ") == {"ground_truth": 2, "old_fts5": 1}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all tests passed")
