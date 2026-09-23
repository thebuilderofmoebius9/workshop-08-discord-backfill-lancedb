"""Search UI: one stdlib HTTP server, one page, three views.

ponytail: http.server + a template string. No FastAPI, no npm, no build step.
Add a framework when this needs auth or more than a handful of routes.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from collections import Counter, deque
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .compare_live import old_index_counts
from .pipeline import EMBED_MODEL, SEARCHERS, open_table, status

TRACE: deque = deque(maxlen=200)          # in-memory ring for the UI
TRACE_LOG: Path | None = None             # append-only JSONL, survives restart
OLD_DB: Path | None = None                # workshop-05 index, for live compare

PAGE = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discord Backfill · LanceDB</title>
<style>
:root{--rail:#1b1d21;--side:#2b2d31;--chat:#313338;--card:#383a40;--line:#3f4147;
--fg:#dbdee1;--dim:#949ba4;--link:#00a8fc;--v:#c792ea;--f:#ffcb6b;--ok:#23a559;--bad:#f23f43}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;background:var(--chat);color:var(--fg);
font:15px/1.45 "gg sans",ui-sans-serif,"Noto Sans Thai",system-ui,sans-serif}
.rail{width:72px;background:var(--rail);display:flex;flex-direction:column;align-items:center;padding:12px 0;gap:8px}
.orb{width:48px;height:48px;border-radius:16px;background:#5865f2;display:grid;place-items:center;font-size:22px}
.side{width:240px;background:var(--side);display:flex;flex-direction:column}
.side h2{font-size:15px;margin:0;padding:16px 14px;border-bottom:1px solid #1f2023;font-weight:600}
.nav{padding:8px}
.nav a{display:block;padding:7px 10px;border-radius:5px;color:var(--dim);text-decoration:none;font-size:15px;cursor:pointer}
.nav a:hover{background:#35373c;color:var(--fg)}
.nav a.on{background:#404249;color:#fff}
.side .foot{margin-top:auto;padding:10px 14px;font-size:11.5px;color:var(--dim);border-top:1px solid #1f2023}
main{flex:1;display:flex;flex-direction:column;min-width:0}
.top{height:48px;display:flex;align-items:center;gap:10px;padding:0 16px;border-bottom:1px solid #26272b;flex-shrink:0}
.top .hash{color:var(--dim);font-size:20px}
.top b{font-size:15px}
.bar{padding:12px 16px;display:flex;gap:8px;border-bottom:1px solid #26272b;flex-wrap:wrap}
input[type=search]{flex:1;min-width:220px;padding:9px 12px;background:#1e1f22;border:none;border-radius:6px;color:var(--fg);font-size:14px}
select,button{padding:9px 12px;background:#1e1f22;border:none;border-radius:6px;color:var(--fg);font-size:14px;cursor:pointer}
button{background:#5865f2;color:#fff;font-weight:500}
.scroll{flex:1;overflow-y:auto;padding:14px 16px}
.msg{display:flex;gap:12px;padding:8px 8px;border-radius:6px}
.msg:hover{background:#2e3035}
.av{width:40px;height:40px;border-radius:50%;flex-shrink:0;display:grid;place-items:center;font-weight:600;color:#fff;font-size:15px}
.who{font-weight:600;color:#f2f3f5}
.bot{background:#5865f2;color:#fff;font-size:10px;padding:1px 4px;border-radius:3px;margin-left:5px;vertical-align:1px}
.ts{color:var(--dim);font-size:12px;margin-left:8px}
.body{white-space:pre-wrap;word-break:break-word;max-height:11em;overflow:hidden}
.tags{margin-left:8px;display:inline-flex;gap:5px}
.tag{font-size:10.5px;border:1px solid var(--line);border-radius:999px;padding:0 7px;color:var(--dim)}
.tag.vector{color:var(--v);border-color:#5b4b73}.tag.fts{color:var(--f);border-color:#6e5f37}
.meter{display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 12px;font-size:12.5px;color:var(--dim)}
.meter b{color:var(--fg)}
.pill{background:#2b2d31;border:1px solid var(--line);border-radius:6px;padding:5px 10px}
.pill.bad b{color:var(--bad)}.pill.ok b{color:var(--ok)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #2b2d31;vertical-align:top}
th{color:var(--dim);font-weight:500}
td.num{text-align:right;font-variant-numeric:tabular-nums}
code{background:#1e1f22;padding:1px 5px;border-radius:4px;font-size:12.5px}
.empty{color:var(--dim);padding:26px 4px}
h3{font-size:14px;color:var(--dim);margin:20px 0 8px;text-transform:uppercase;letter-spacing:.4px}
h3:first-child{margin-top:4px}
</style></head><body>
<div class="rail"><div class="orb">⚛</div></div>
<div class="side">
  <h2>Discord Backfill</h2>
  <div class="nav">
    <a id="n-chat" class="on" onclick="go('chat')"># free-for-all</a>
    <a id="n-stats" onclick="go('stats')">📊 stats</a>
    <a id="n-trace" onclick="go('trace')">🧾 query trace log</a>
  </div>
  <div class="foot" id="foot">…</div>
</div>
<main>
  <div class="top"><span class="hash">#</span><b id="title">free-for-all</b></div>
  <div class="bar" id="bar">
    <input type="search" id="q" placeholder="ค้นข้อความ… (ไทย/อังกฤษ)" autofocus>
    <select id="mode">
      <option value="hybrid">hybrid (RRF)</option>
      <option value="vector">vector (bge-m3)</option>
      <option value="fts">full-text</option>
    </select>
    <button onclick="run()">ค้นหา</button>
  </div>
  <div class="scroll" id="out"><div class="empty">พิมพ์คำค้นแล้วกดค้นหา — ทุกคำค้นจะถูกบันทึกลงหน้า query trace log</div></div>
</main>
<script>
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const HUE=s=>{let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))%360;return h};
const out=document.getElementById('out');
let view='chat';

fetch('/api/status').then(r=>r.json()).then(s=>{
  foot.innerHTML=`<b>${s.rows.toLocaleString()}</b> ข้อความ · ${(s.bytes/1048576).toFixed(1)} MB<br>${s.embed_model} · ${s.dim}d`;
});

function go(v){
  view=v;
  for(const k of ['chat','stats','trace'])document.getElementById('n-'+k).className=(k===v?'on':'');
  bar.style.display = v==='chat' ? 'flex' : 'none';
  title.textContent = v==='chat'?'free-for-all':(v==='stats'?'stats':'query trace log');
  document.querySelector('.hash').textContent = v==='chat'?'#':'';
  if(v==='stats')stats(); else if(v==='trace')trace(); else out.innerHTML='<div class="empty">พิมพ์คำค้นแล้วกดค้นหา</div>';
}

async function run(){
  if(!q.value.trim())return;
  out.innerHTML='<div class="empty">ค้นหา…</div>';
  const r=await (await fetch(`/api/search?q=${encodeURIComponent(q.value)}&mode=${mode.value}&limit=25`)).json();
  const c=r.compare||{};
  const miss = c.ground_truth ? Math.round(100*(c.old_fts5??0)/c.ground_truth) : null;
  out.innerHTML=`<div class="meter">
    <span class="pill">LanceDB (${r.mode}) <b>${r.count}</b> · <b>${r.ms}</b> ms</span>
    ${c.ground_truth!=null?`<span class="pill">มีอยู่จริง (LIKE) <b>${c.ground_truth}</b></span>
    <span class="pill ${miss<100?'bad':'ok'}">แอปเก่า SQLite-FTS5 <b>${c.old_fts5??'error'}</b>${miss!=null?` (${miss}%)`:''}</span>`:''}
  </div>` + (r.rows.length? r.rows.map(x=>{
    const who=x.author_name||'?';
    return `<div class="msg"><div class="av" style="background:hsl(${HUE(who)} 45% 42%)">${esc(who[0]||'?')}</div>
      <div style="min-width:0"><div><span class="who">${esc(who)}</span><span class="bot">APP</span>
      <span class="ts">${esc((x.created_at||'').slice(0,16).replace('T',' '))}</span>
      <span class="tags"><span class="tag">score ${x.score??'-'}</span>
      ${(x.found_by||[]).map(s=>`<span class="tag ${s}">${s}</span>`).join('')}</span></div>
      <div class="body">${esc(x.content)}</div></div></div>`;}).join('')
    : '<div class="empty">ไม่พบผลลัพธ์</div>');
}
q.addEventListener('keydown',e=>{if(e.key==='Enter')run()});

async function stats(){
  const s=await (await fetch('/api/stats')).json();
  const row=(k,v)=>`<tr><td>${k}</td><td class="num">${v}</td></tr>`;
  out.innerHTML=`<h3>index</h3><table>
    ${row('ข้อความทั้งหมด',s.rows.toLocaleString())}
    ${row('ขนาดบนดิสก์',(s.bytes/1048576).toFixed(2)+' MB')}
    ${row('โมเดล embedding',`<code>${s.embed_model}</code> · ${s.dim}d`)}
    ${row('full-text index',s.fts_rows!=null?s.fts_rows.toLocaleString()+' rows':'—')}
    ${row('ข้อความที่ถูกแก้ (edited)',s.edited.toLocaleString())}
    ${row('ไฟล์แนบ',s.attachments.toLocaleString())}
    ${row('ถูก redact ตอน ingest',s.redactions.toLocaleString())}
    ${row('ช่วงเวลา',esc(s.first_at)+' → '+esc(s.last_at))}
    ${row('ห้อง',s.channels.map(esc).join(', '))}
  </table>
  <h3>ผู้พูดสูงสุด 15 อันดับ</h3><table><tr><th>ชื่อ</th><th class="num">ข้อความ</th></tr>
    ${s.top_authors.map(([a,n])=>`<tr><td>${esc(a)}</td><td class="num">${n}</td></tr>`).join('')}</table>
  <h3>คำค้นที่ยิงไปแล้ว</h3><table>${row('จำนวน query ใน session นี้',s.queries)}</table>`;
}

async function trace(){
  const t=await (await fetch('/api/trace')).json();
  out.innerHTML = t.length? `<table>
    <tr><th>เวลา</th><th>คำค้น</th><th>mode</th><th class="num">LanceDB</th>
    <th class="num">มีจริง(LIKE)</th><th class="num">FTS5 เก่า</th><th class="num">ms</th></tr>
    ${t.slice().reverse().map(r=>`<tr><td>${esc(r.at.slice(11,19))}</td><td>${esc(r.query)}</td>
      <td><code>${esc(r.mode)}</code></td><td class="num">${r.count}</td>
      <td class="num">${r.ground_truth??'—'}</td><td class="num">${r.old_fts5??'—'}</td>
      <td class="num">${r.ms}</td></tr>`).join('')}</table>`
    : '<div class="empty">ยังไม่มีคำค้นในบันทึก</div>';
}
</script></body></html>
"""


@lru_cache(maxsize=1)
def _table(db_path: str):
    return open_table(Path(db_path))


def _stats(db: str) -> dict:
    table = _table(db)
    arrow = table.to_arrow()
    authors = Counter(arrow["author_name"].to_pylist())
    created = sorted(x for x in arrow["created_at"].to_pylist() if x)
    base = status(Path(db))
    fts_rows = None
    for index in table.list_indices():
        fts_rows = getattr(index, "num_indexed_rows", None) or fts_rows
    return {
        "rows": base["rows"],
        "bytes": base["bytes"],
        "embed_model": base["embed_model"],
        "dim": base["dim"],
        "fts_rows": fts_rows,
        "edited": sum(arrow["edited"].to_pylist()),
        "attachments": sum(arrow["attachments"].to_pylist()),
        "redactions": sum(arrow["redactions"].to_pylist()),
        "first_at": (created[0] or "")[:16].replace("T", " "),
        "last_at": (created[-1] or "")[:16].replace("T", " "),
        "channels": sorted(set(arrow["channel_name"].to_pylist())),
        "top_authors": authors.most_common(15),
        "queries": len(TRACE),
    }


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8099,
          old_db: Path | None = None, trace_log: Path | None = None) -> None:
    global OLD_DB, TRACE_LOG
    OLD_DB, TRACE_LOG = old_db, trace_log
    db = str(db_path)
    _table(db)  # fail fast if the index is missing
    if TRACE_LOG and TRACE_LOG.exists():  # restore what earlier runs logged
        for line in TRACE_LOG.read_text().splitlines()[-TRACE.maxlen:]:
            try:
                TRACE.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, body: bytes, content_type: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, code: int = 200) -> None:
            self._send(json.dumps(payload, ensure_ascii=False).encode(), "application/json", code)

        def do_GET(self) -> None:  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            args = urllib.parse.parse_qs(url.query)
            if url.path == "/":
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if url.path == "/api/status":
                return self._json(status(Path(db)))
            if url.path == "/api/stats":
                return self._json(_stats(db))
            if url.path == "/api/trace":
                return self._json(list(TRACE))
            if url.path == "/api/search":
                return self._json(*self._search(args))
            self._send(b"not found", "text/plain", 404)

        def _search(self, args):
            query = (args.get("q") or [""])[0]
            mode = (args.get("mode") or ["hybrid"])[0]
            if mode not in SEARCHERS:
                return {"error": "bad mode"}, 400
            limit = max(1, min(50, int((args.get("limit") or ["25"])[0])))
            t0 = time.perf_counter()
            rows = SEARCHERS[mode](_table(db), query, limit) if query.strip() else []
            ms = round((time.perf_counter() - t0) * 1000, 1)
            compare = old_index_counts(OLD_DB, query) if (OLD_DB and query.strip()) else {}
            entry = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "query": query, "mode": mode, "count": len(rows), "lance_count": len(rows), "ms": ms,
                **{k: compare.get(k) for k in ("ground_truth", "old_fts5")},
            }
            if query.strip():
                TRACE.append(entry)
                if TRACE_LOG:  # append-only: the log outlives the process
                    with TRACE_LOG.open("a") as fh:
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return {"mode": mode, "query": query, "count": len(rows),
                    "ms": ms, "compare": compare, "rows": rows}, 200

        def log_message(self, *args) -> None:  # quiet
            pass

    print(f"serving http://{host}:{port} on {db}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
