"""Head-to-head: workshop-05 SQLite/FTS5 app vs this LanceDB app.

Same export JSON, same queries, same box. Relevance is judged by a keyword
regex per query (stated in QUERIES) — a cheap judge, not human labelling; it is
there so precision@10 is reproducible, not to claim a benchmark.

  python compare.py --old-db ... --old-repo ... --lance-db ... --out report.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics
import sys
import time
from pathlib import Path

from lance_backfill.pipeline import SEARCHERS, open_table

# (query, relevance regex, note)
QUERIES = [
    ("ความจำ", r"ความจำ|memory|จำได้|remember", "ไทยล้วน มีคำนี้ตรง ๆ ในคลัง"),
    ("ฐานข้อมูล", r"ฐานข้อมูล|database|sqlite|lancedb|db\b", "ไทยล้วน + คำอังกฤษร่วมความหมาย"),
    ("หลักฐาน", r"หลักฐาน|proof|พิสูจน์|evidence", "ไทยล้วน"),
    ("ค้นหาข้อความเก่าในห้องแชท", r"ค้นหา|search|backfill|ข้อความเก่า|history", "ไทย paraphrase ไม่มีในคลังตรง ๆ"),
    ("โมเดลฝังเวกเตอร์ภาษาไทย", r"embed|bge|nomic|minilm|vector|เวกเตอร์", "ไทย paraphrase ศัพท์เทคนิค"),
    ("ตัวเลขสองฝั่งไม่ตรงกัน", r"parity|ไม่ตรง|mismatch|ต่างกัน|ไม่เท่า", "ไทย paraphrase เชิงความหมาย"),
    ("workshop", r"workshop", "อังกฤษ token ตรง"),
    ("lancedb", r"lance", "อังกฤษ token หายาก"),
    ("pull request", r"pull request|\bPR\b|merge", "อังกฤษ 2 token"),
    ("how do we prove it actually works", r"proof|prove|หลักฐาน|พิสูจน์|verify|ยืนยัน", "อังกฤษ paraphrase"),
]
LIMIT = 10


def load_old(repo: Path):
    spec = importlib.util.spec_from_file_location("old_pipeline", repo / "discord_backfill" / "pipeline.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["old_pipeline"] = module
    spec.loader.exec_module(module)
    return module


def timed(fn, *args):
    t0 = time.perf_counter()
    rows = fn(*args)
    return rows, round((time.perf_counter() - t0) * 1000, 1)


def score(rows: list[dict], pattern: str) -> dict:
    rx = re.compile(pattern, re.IGNORECASE)
    hits = [bool(rx.search(r.get("content") or "")) for r in rows]
    return {
        "returned": len(rows),
        "relevant": sum(hits),
        "precision_at_10": round(sum(hits) / LIMIT, 2),
        "first_relevant_rank": (hits.index(True) + 1) if any(hits) else None,
    }


def dir_bytes(path: Path) -> int:
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-repo", required=True, type=Path)
    ap.add_argument("--old-db", required=True, type=Path)
    ap.add_argument("--lance-db", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path("artifacts/comparison.json"))
    args = ap.parse_args()

    old = load_old(args.old_repo)
    table = open_table(args.lance_db)
    engines = {
        # the old app names the column content_safe; normalise so the judge sees the same field
        "old_sqlite_fts5": lambda q: [r | {"content": r.get("content_safe", "")} for r in old.search_messages(args.old_db, q, LIMIT)],
        "lance_fts": lambda q: SEARCHERS["fts"](table, q, LIMIT),
        "lance_vector": lambda q: SEARCHERS["vector"](table, q, LIMIT),
        "lance_hybrid": lambda q: SEARCHERS["hybrid"](table, q, LIMIT),
    }

    per_query = []
    for query, pattern, note in QUERIES:
        row = {"query": query, "note": note, "judge": pattern, "engines": {}}
        for name, fn in engines.items():
            rows, ms = timed(fn, query)
            row["engines"][name] = score(rows, pattern) | {"ms": ms, "top1": (rows[0]["content"][:90] if rows else None)}
        per_query.append(row)

    summary = {}
    for name in engines:
        stats = [q["engines"][name] for q in per_query]
        summary[name] = {
            "mean_precision_at_10": round(statistics.mean(s["precision_at_10"] for s in stats), 3),
            "queries_with_zero_results": sum(1 for s in stats if s["returned"] == 0),
            "mean_ms": round(statistics.mean(s["ms"] for s in stats), 1),
            "median_ms": round(statistics.median(s["ms"] for s in stats), 1),
        }

    report = {
        "dataset": {"messages": old.status(args.old_db)["messages"], "channel": "free-for-all"},
        "index_bytes": {"old_sqlite": dir_bytes(args.old_db), "lancedb": dir_bytes(args.lance_db)},
        "summary": summary,
        "per_query": per_query,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"summary": summary, "index_bytes": report["index_bytes"]}, ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
