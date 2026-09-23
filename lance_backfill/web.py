"""Search UI: one stdlib HTTP server, one page, three search modes.

ponytail: http.server + a template string. No FastAPI, no build step, no npm.
Add a framework when this needs auth or more than one route.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import SEARCHERS, open_table, status

PAGE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discord Backfill · LanceDB</title>
<style>
:root{--bg:#0e1015;--panel:#171a21;--line:#262b36;--fg:#e7e9ee;--dim:#8b93a5;--accent:#7cc4ff;--v:#c792ea;--f:#ffcb6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 ui-sans-serif,"Noto Sans Thai",system-ui,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:17px;margin:0;letter-spacing:.3px}
.stat{color:var(--dim);font-size:12.5px}
main{max-width:1000px;margin:0 auto;padding:24px}
form{display:flex;gap:8px;flex-wrap:wrap}
input[type=search]{flex:1;min-width:260px;padding:11px 14px;background:var(--panel);border:1px solid var(--line);border-radius:8px;color:var(--fg);font-size:15px}
select,button{padding:11px 14px;background:var(--panel);border:1px solid var(--line);border-radius:8px;color:var(--fg);font-size:14px;cursor:pointer}
button{background:#1f2a38;border-color:#31465e;color:var(--accent)}
#meta{color:var(--dim);font-size:12.5px;margin:14px 0 8px}
.row{border:1px solid var(--line);background:var(--panel);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.head{display:flex;gap:10px;align-items:baseline;font-size:12.5px;color:var(--dim);margin-bottom:6px;flex-wrap:wrap}
.who{color:var(--accent);font-weight:600}
.badge{border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-size:11px}
.badge.vector{color:var(--v)}.badge.fts{color:var(--f)}
.body{white-space:pre-wrap;word-break:break-word;font-size:14px;max-height:9.5em;overflow:hidden}
.empty{color:var(--dim);padding:24px 0}
</style></head><body>
<header><h1>⚛ Discord Backfill · LanceDB</h1><span class="stat" id="stat">…</span></header>
<main>
<form id="f">
  <input type="search" id="q" placeholder="ค้นข้อความ… (ไทย/อังกฤษ)" autofocus>
  <select id="mode">
    <option value="hybrid">hybrid (RRF)</option>
    <option value="vector">vector (bge-m3)</option>
    <option value="fts">full-text</option>
  </select>
  <button>ค้นหา</button>
</form>
<div id="meta"></div>
<div id="out"></div>
</main>
<script>
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
fetch('/api/status').then(r=>r.json()).then(s=>{
  stat.textContent=`${s.rows.toLocaleString()} messages · ${(s.bytes/1048576).toFixed(1)} MB · ${s.embed_model} ${s.dim}d`;});
f.onsubmit=async e=>{
  e.preventDefault(); if(!q.value.trim())return;
  meta.textContent='ค้นหา…'; out.innerHTML='';
  const r=await (await fetch(`/api/search?q=${encodeURIComponent(q.value)}&mode=${mode.value}&limit=20`)).json();
  meta.textContent=`${r.count} ผลลัพธ์ · ${r.ms} ms · mode=${r.mode}`;
  out.innerHTML = r.rows.length ? r.rows.map(x=>`<div class="row"><div class="head">
      <span class="who">${esc(x.author_name||'?')}</span>
      <span>${esc((x.created_at||'').slice(0,16).replace('T',' '))}</span>
      <span class="badge">score ${x.score??'-'}</span>
      ${(x.found_by||[]).map(s=>`<span class="badge ${s}">${s}</span>`).join('')}
    </div><div class="body">${esc(x.content||'')}</div></div>`).join('')
    : '<div class="empty">ไม่พบผลลัพธ์</div>';
};
</script></body></html>
"""


@lru_cache(maxsize=1)
def _table(db_path: str):
    return open_table(Path(db_path))


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8099) -> None:
    db = str(db_path)
    _table(db)  # fail fast if the index is missing

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, body: bytes, content_type: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == "/":
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if url.path == "/api/status":
                return self._send(json.dumps(status(Path(db))).encode(), "application/json")
            if url.path == "/api/search":
                q = (query.get("q") or [""])[0]
                mode = (query.get("mode") or ["hybrid"])[0]
                if mode not in SEARCHERS:
                    return self._send(b'{"error":"bad mode"}', "application/json", 400)
                limit = max(1, min(50, int((query.get("limit") or ["20"])[0])))
                t0 = time.perf_counter()
                rows = SEARCHERS[mode](_table(db), q, limit) if q.strip() else []
                payload = {
                    "mode": mode,
                    "query": q,
                    "count": len(rows),
                    "ms": round((time.perf_counter() - t0) * 1000, 1),
                    "rows": rows,
                }
                return self._send(json.dumps(payload, ensure_ascii=False).encode(), "application/json")
            self._send(b"not found", "text/plain", 404)

        def log_message(self, *args) -> None:  # quiet
            pass

    print(f"serving http://{host}:{port} on {db}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
