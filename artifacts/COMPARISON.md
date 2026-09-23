# Comparison — workshop-05 SQLite/FTS5 vs workshop-08 LanceDB

Same box, same day, same input: **3,000 real messages** pulled from Oracle School
`#free-for-all` (channel `1512079809021214730`) with workshop-05's own
`fetch-discord --redact`, written once to `/tmp/ws08data/free-for-all-3k.json`
and fed to both indexes.

Relevance is judged by a per-query keyword regex (see `QUERIES` in `compare.py`),
so precision@10 is reproducible but **is not human labelling** — read it as a
signal, not a benchmark.

## Build

```text
old  workshop-05  SQLite + FTS5     2.89 s      35,262,464 B   parity ok 3000/3000
new  workshop-08  LanceDB + bge-m3  325.96 s    16,366,339 B   parity ok 3000/3000
                  (embed 325.96 s on CPU-class ollama + index/FTS 1.53 s)
```

The new index is **2.2× smaller** while also carrying 3,000 × 1024 float32
vectors (~12 MB of those 16 MB). SQLite is bigger because FTS5 keeps a second
copy of every message body.

Build cost is the honest trade: **113× slower to build** (5m26s vs 2.9s), all of
it embedding. That cost is paid once per message, not per query.

## Search quality

```text
engine             mean p@10  zero-result  mean ms  median ms
─────────────────────────────────────────────────────────────
old_sqlite_fts5         0.51            4      3.1        3.1
lance_fts               0.71            0     13.2       11.1
lance_vector            0.68            0    229.4      219.3
lance_hybrid            0.74            0    610.3      260.9
```

```text
query                             note                         old   fts   vec   hyb
────────────────────────────────────────────────────────────────────────────────────
ความจำ                            ไทยล้วน มีคำนี้ตรง ๆ ในคล    1.0   1.0   1.0   1.0
ฐานข้อมูล                         ไทยล้วน + คำอังกฤษร่วมควา    0.7   0.7   0.6   0.9
หลักฐาน                           ไทยล้วน                      1.0   1.0   0.4   0.8
ค้นหาข้อความเก่าในห้องแชท         ไทย paraphrase ไม่มีในคลั    0.0   0.7   0.6   0.6
โมเดลฝังเวกเตอร์ภาษาไทย           ไทย paraphrase ศัพท์เทคนิ    0.0   0.2   1.0   0.7
ตัวเลขสองฝั่งไม่ตรงกัน            ไทย paraphrase เชิงความหม    0.0   0.2   0.2   0.3
workshop                          อังกฤษ token ตรง             1.0   1.0   1.0   1.0
lancedb                           อังกฤษ token หายาก           1.0   1.0   1.0   1.0
pull request                      อังกฤษ 2 token               0.4   0.7   0.1   0.4
how do we prove it actually works อังกฤษ paraphrase            0.0   0.6   0.9   0.7
```

## What the numbers actually say

1. **The old app's real failure is multi-word queries, not Thai per se.**
   4 of 10 queries returned **zero rows** on FTS5 — `ค้นหาข้อความเก่าในห้องแชท`,
   `โมเดลฝังเวกเตอร์ภาษาไทย`, `ตัวเลขสองฝั่งไม่ตรงกัน`, and the English
   `how do we prove it actually works`. FTS5 `MATCH` ANDs every token; a
   paraphrase nobody typed verbatim matches nothing. Single Thai words
   (`ความจำ`, `หลักฐาน`) scored a clean 1.0 on the old index — the earlier
   "FTS5 can't do Thai" framing was too coarse, and this run corrects it.
2. **Vector search is what rescues paraphrase.** `โมเดลฝังเวกเตอร์ภาษาไทย`:
   old 0.0 → vector 1.0. `how do we prove it actually works`: old 0.0 → vector 0.9.
3. **Vector alone is worse at literal lookup.** `หลักฐาน` 1.0 → 0.4,
   `pull request` 0.4 → 0.1. It retrieves neighbours in meaning, not the token.
4. **Hybrid RRF is the best single default** (0.74 mean, no empty results) but
   never the best on every query — it trails pure vector on paraphrase and pure
   FTS on literals. Three modes stay exposed in the UI for that reason.
5. **Latency is the other trade.** FTS5 3.1 ms → LanceDB FTS 13.2 ms → vector
   229 ms → hybrid 610 ms mean. Almost all of the vector/hybrid cost is the
   ~200 ms ollama call that embeds the query, not LanceDB (3k rows is a
   brute-force scan in single-digit ms). Cache query embeddings or run the
   embedder on GPU and hybrid drops to roughly FTS latency + one scan.

## Reproduce

```bash
.venv/bin/python compare.py \
  --old-repo ../workshop-05-backfill-midterm \
  --old-db /tmp/ws08data/old/old-3k.sqlite \
  --lance-db out/lance --out artifacts/comparison.json
```

Raw per-query output, top-1 hit text and every timing: `artifacts/comparison.json`.
UI proof: `artifacts/ui-01-idle.png`, `ui-02-thai-hybrid.png`, `ui-03-thai-vector.png`.
