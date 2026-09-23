# workshop-08 — Discord backfill on LanceDB (+ web UI)

Atom's submission. Same job as [workshop-05](https://github.com/the-oracle-keeps-the-human-human/workshop-05-backfill-midterm)
(Discord export → searchable index), swapped storage: **SQLite/FTS5 → LanceDB**
(vector + full-text in one table), plus a search UI and a head-to-head harness
against the old app.

```text
Discord REST → export JSON → JSONL mirror → LanceDB table (bge-m3 1024d + FTS)
                                   ↓
                     fts | vector | hybrid(RRF) → web UI
```

## Why bother — the one number

On 3,000 real `#free-for-all` messages, **4 of 10 test queries return zero rows
on the old SQLite/FTS5 index** — every one of them a paraphrase, Thai or
English. `MATCH` ANDs all tokens, so a question nobody typed verbatim matches
nothing. Vector search fixes exactly those (`โมเดลฝังเวกเตอร์ภาษาไทย`:
p@10 0.0 → 1.0) and loses on literal token lookup (`pull request`: 0.4 → 0.1),
which is why hybrid RRF is the default and all three modes stay exposed.
Mean p@10: old 0.51 · lance-fts 0.71 · vector 0.68 · **hybrid 0.74**.
Full numbers, timings and the reproduce command: `artifacts/COMPARISON.md`.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install lancedb pyarrow
ollama pull bge-m3                      # embeddings, local

# 1. pull real messages (reuses workshop-05's fetcher, already redacting secrets)
export DISCORD_BOT_TOKEN=...
python -m discord_backfill.cli fetch-discord --channel-id ... --guild-id ... \
  --limit 3000 --redact --output data/export.json

# 2. index
.venv/bin/python -m lance_backfill.cli backfill --input data/export.json \
  --db out/lance --mirror out/mirror

# 3. search
.venv/bin/python -m lance_backfill.cli search "ความจำ" --db out/lance --mode hybrid
.venv/bin/python -m lance_backfill.cli status --db out/lance

# 4. web UI  →  http://127.0.0.1:8099
#    --old-db enables per-query LIKE ground truth + old FTS5 comparison
#    --trace-log persists the query trace across server restarts
.venv/bin/python -m lance_backfill.cli web --db out/lance \
  --old-db /tmp/ws08data/old/old-3k.sqlite \
  --trace-log artifacts/query-trace.jsonl --port 8099

# 5. head-to-head vs the SQLite app
.venv/bin/python compare.py --old-repo ../workshop-05-backfill-midterm \
  --old-db old.sqlite --lance-db out/lance --out artifacts/comparison.json
```

## Layout

- `lance_backfill/pipeline.py` — ingest, redact, embed, index, parity, 3 searchers
- `lance_backfill/web.py` — the UI (stdlib `http.server`, one page, no build step)
- UI views: Discord-style chat/search, index `stats`, and persisted `query trace log`
- Every search shows the three-way evidence card: `LIKE ground truth` · old `SQLite/FTS5` · `LanceDB (selected mode)`
- `compare.py` — 10 queries × 4 engines → precision@10, latency, index size
- `tests/test_pipeline.py` — `python tests/test_pipeline.py`, no framework
- `artifacts/` — comparison report + UI screenshots

## Kept from workshop-05

Raw JSONL mirror before indexing, secret redaction before storage, and a parity
gate (raw ids == indexed ids) that fails the run rather than reporting a
half-index.

## Not built

Incremental/resumable backfill (watermark cursor), attachment indexing, and an
ANN index — 3k rows brute-force in single-digit ms, `create_index()` when the
corpus grows past ~100k. Reranking is plain RRF, no cross-encoder.
