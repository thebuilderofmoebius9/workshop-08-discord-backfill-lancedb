from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import backfill, search, status


def main() -> None:
    parser = argparse.ArgumentParser(prog="lance_backfill", description="Discord backfill on LanceDB")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backfill", help="ingest a Discord export JSON into LanceDB")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--mirror", type=Path)

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--mode", choices=["fts", "vector", "hybrid"], default="hybrid")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("status")
    p.add_argument("--db", required=True, type=Path)

    p = sub.add_parser("web", help="serve the search UI")
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--old-db", type=Path, help="workshop-05 SQLite index, for the live per-query compare")
    p.add_argument("--trace-log", type=Path, help="append every query here as JSONL")

    args = parser.parse_args()
    if args.command == "backfill":
        out = backfill(args.input, args.db, args.mirror)
    elif args.command == "search":
        out = search(args.db, args.query, args.mode, args.limit)
    elif args.command == "status":
        out = status(args.db)
    else:
        from .web import serve

        serve(args.db, args.host, args.port, args.old_db, args.trace_log)
        return
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
