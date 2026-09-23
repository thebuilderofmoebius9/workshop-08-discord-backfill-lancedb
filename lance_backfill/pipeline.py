"""Discord backfill -> LanceDB (vector + full-text), with RRF hybrid search.

Reads the SAME export JSON the workshop-05 SQLite app reads, so both indexes
can be measured on identical input.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import lancedb
import pyarrow as pa

OLLAMA_URL = "http://127.0.0.1:11434/api/embed"
EMBED_MODEL = "bge-m3"          # multilingual; Thai+English in one space
EMBED_DIM = 1024
TABLE = "messages"

# ponytail: same 6 patterns as the workshop-05 app; the export is already
# redacted upstream, this is the belt to that suspenders.
SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
]


def redact(text: str) -> tuple[str, int]:
    hits = 0
    for pattern in SECRET_PATTERNS:
        text, n = pattern.subn("[REDACTED]", text)
        hits += n
    return text, hits


def iter_messages(export: dict[str, Any]) -> list[dict[str, Any]]:
    guild = export["guild"]
    rows: list[dict[str, Any]] = []
    for channel in export["channels"]:
        for msg in channel.get("messages", []):
            content, hits = redact(msg.get("content") or "")
            rows.append(
                {
                    "message_id": str(msg["id"]),
                    "guild_id": str(guild["id"]),
                    "guild_name": guild.get("name") or "",
                    "channel_id": str(channel["id"]),
                    "channel_name": channel.get("name") or "",
                    "author_id": str(msg.get("author_id") or ""),
                    "author_name": msg.get("author_name") or "",
                    "content": content,
                    "created_at": msg.get("created_at") or "",
                    "created_ts": _epoch(msg.get("created_at")),
                    "edited": bool(msg.get("edited_at")),
                    "attachments": len(msg.get("attachments") or []),
                    "redactions": hits,
                }
            )
    return rows


def _epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def embed(texts: list[str], *, batch: int = 32, progress: bool = False) -> list[list[float]]:
    """Ollama /api/embed. Empty strings get a zero vector, never a model call."""
    out: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]
    todo = [i for i, t in enumerate(texts) if t.strip()]
    for start in range(0, len(todo), batch):
        idx = todo[start : start + batch]
        payload = json.dumps({"model": EMBED_MODEL, "input": [texts[i][:4000] for i in idx]}).encode()
        req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            vectors = json.loads(resp.read())["embeddings"]
        for i, vec in zip(idx, vectors):
            out[i] = vec
        if progress:
            print(f"embed {min(start + batch, len(todo))}/{len(todo)}", flush=True)
    zero = [0.0] * EMBED_DIM
    return [v if v is not None else zero for v in out]


SCHEMA = pa.schema(
    [
        pa.field("message_id", pa.string()),
        pa.field("guild_id", pa.string()),
        pa.field("guild_name", pa.string()),
        pa.field("channel_id", pa.string()),
        pa.field("channel_name", pa.string()),
        pa.field("author_id", pa.string()),
        pa.field("author_name", pa.string()),
        pa.field("content", pa.string()),
        pa.field("created_at", pa.string()),
        pa.field("created_ts", pa.float64()),
        pa.field("edited", pa.bool_()),
        pa.field("attachments", pa.int32()),
        pa.field("redactions", pa.int32()),
        pa.field("vector", pa.list_(pa.float32(), EMBED_DIM)),
    ]
)


@dataclass(frozen=True)
class Stats:
    messages: int
    embed_seconds: float
    index_seconds: float
    parity_ok: bool
    raw_ids: int
    table_ids: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"parity_ok": self.parity_ok}


def backfill(input_path: Path, db_path: Path, mirror_dir: Path | None = None) -> dict[str, Any]:
    export = json.loads(Path(input_path).read_text())
    rows = iter_messages(export)

    if mirror_dir:  # raw JSONL mirror — same evidence rule as workshop-05
        mirror_dir = Path(mirror_dir)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        with (mirror_dir / "messages.jsonl").open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    t0 = time.perf_counter()
    vectors = embed([f"{r['author_name']}: {r['content']}" for r in rows], progress=True)
    embed_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    db = lancedb.connect(str(db_path))
    if TABLE in db.table_names():
        db.drop_table(TABLE)
    table = db.create_table(TABLE, data=[r | {"vector": v} for r, v in zip(rows, vectors)], schema=SCHEMA)
    table.create_fts_index("content", replace=True, use_tantivy=False)
    index_seconds = time.perf_counter() - t0

    raw_ids = {r["message_id"] for r in rows}
    table_ids = set(table.to_arrow()["message_id"].to_pylist())
    stats = Stats(
        messages=len(rows),
        embed_seconds=round(embed_seconds, 3),
        index_seconds=round(index_seconds, 3),
        parity_ok=raw_ids == table_ids,
        raw_ids=len(raw_ids),
        table_ids=len(table_ids),
    )
    return stats.as_dict() | {"db": str(db_path), "at": datetime.now(timezone.utc).isoformat()}


def open_table(db_path: Path):
    return lancedb.connect(str(db_path)).open_table(TABLE)


FIELDS = ["message_id", "author_name", "content", "created_at", "channel_name"]


def search_fts(table, query: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        rows = table.search(query, query_type="fts").select(FIELDS).limit(limit).to_list()
    except Exception:
        return []
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["score"] = row.pop("_score", None)
    return [{k: v for k, v in r.items() if k != "vector"} for r in rows]


def search_vector(table, query: str, limit: int = 10) -> list[dict[str, Any]]:
    vector = embed([query])[0]
    rows = table.search(vector).select(FIELDS).limit(limit).to_list()
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["score"] = round(1 - row.pop("_distance", 1.0), 4)
    return [{k: v for k, v in r.items() if k != "vector"} for r in rows]


def search_hybrid(table, query: str, limit: int = 10, k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal-rank fusion of the two lists above.

    ponytail: plain RRF, no learned reranker. Swap in a cross-encoder only if
    the fused ordering is measurably wrong.
    """
    pools = (search_fts(table, query, limit * 2), search_vector(table, query, limit * 2))
    fused: dict[str, dict[str, Any]] = {}
    for source, rows in zip(("fts", "vector"), pools):
        for row in rows:
            entry = fused.setdefault(row["message_id"], row | {"rrf": 0.0, "found_by": []})
            entry["rrf"] += 1 / (k + row["rank"])
            entry["found_by"].append(source)
    ordered = sorted(fused.values(), key=lambda r: -r["rrf"])[:limit]
    for rank, row in enumerate(ordered, 1):
        row["rank"] = rank
        row["score"] = round(row.pop("rrf"), 5)
    return ordered


SEARCHERS = {"fts": search_fts, "vector": search_vector, "hybrid": search_hybrid}


def search(db_path: Path, query: str, mode: str = "hybrid", limit: int = 10) -> list[dict[str, Any]]:
    return SEARCHERS[mode](open_table(db_path), query, limit)


def status(db_path: Path) -> dict[str, Any]:
    table = open_table(db_path)
    size = sum(f.stat().st_size for f in Path(db_path).rglob("*") if f.is_file())
    return {
        "db": str(db_path),
        "rows": table.count_rows(),
        "bytes": size,
        "indices": [str(i) for i in table.list_indices()],
        "embed_model": EMBED_MODEL,
        "dim": EMBED_DIM,
    }
