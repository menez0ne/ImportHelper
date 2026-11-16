"""Server locale: http://localhost:8765  (python -m importhelper.server)

- "/"            la pagina con i dati aggiornati e il modulo "Cerca un'auto"
- "/api/..."     ricerche, avanzamento della raccolta, marche e modelli

Risponde solo da questo PC (127.0.0.1). Una raccolta alla volta, in un thread a
parte; le altre richieste aspettano in coda. Le richieste che cambiano qualcosa
devono avere l'intestazione "X-ImportHelper: 1" (le altre pagine web non possono
mandarla), così nessun sito esterno può far partire ricerche.
"""
from __future__ import annotations

import io
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import __main__ as app
from .db import Database
from .searches import SearchStore, is_saved, make_search
from .site import build as build_site
from .site import data_version, merge_duplicates, render
from .taxonomy import Taxonomy

HOST, PORT = "127.0.0.1", 8765
ROOT = app.ROOT
LOCK = ROOT / "data" / "raccolta.lock"
PAGE_RE = re.compile(r"pagina (\d+)\s*/\s*(\d+)|(\d+)/(\d+) risultati letti")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Collector:
    """Coda delle raccolte, eseguite una alla volta. Lo stato si legge con status()."""

    def __init__(self, run_search: Callable | None = None):
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.queued: list[str] = []
        self.running: dict | None = None
        self.last: dict | None = None
        self.run_search = run_search or self._run_search
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "Collector":
        self.thread.start()
        return self

    # ---------- coda ----------
    def enqueue(self, name: str) -> bool:
        with self.lock:
            if name in self.queued or (self.running and self.running["search"] == name):
                return False
            self.queued.append(name)
        self.q.put(name)
        return True

    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps({"running": self.running, "queue": list(self.queued), "last": self.last}))

    # ---------- avanzamento ----------
    def progress(self, event: str, **kw) -> None:
        with self.lock:
            run = self.running
            if not run:
                return
            src = next((s for s in run["sources"] if s["source"] == kw.get("source")), None)
            if src is None:
                return
            if event == "source_start":
                src.update(state="running", detail="in corso")
            elif event == "source_done":
                src.update(state="done", found=kw.get("found", 0), kept=kw.get("kept", 0),
                           detail="nessun annuncio trovato" if not kw.get("found") else "")
                run["kept_total"] = sum(s.get("kept", 0) for s in run["sources"])
            elif event == "source_skipped":
                src.update(state="skipped", detail="fonte disattivata")
            elif event == "source_error":
                src.update(state="error", detail="errore: " + kw.get("error", "")[:120])

    def page_line(self, line: str) -> None:
        """Le fonti stampano "pagina 2/5" o "100/230 risultati letti": li mostriamo nel sito."""
        m = PAGE_RE.search(line)
        if not m:
            return
        with self.lock:
            run = self.running
            if run:
                src = next((s for s in run["sources"] if s["state"] == "running"), None)
                if src:
                    a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                    src["detail"] = f"pagina {a} di {b}" if m.group(1) else f"{a} di {b} risultati letti"

    # ---------- esecuzione ----------
    def _loop(self) -> None:
        while True:
            name = self.q.get()
            search = next((s for s in app.load_config()["searches"] if s["name"] == name), None)
            # tolta dalla coda e messa "in corso" nello stesso momento: lo stato non sembra mai fermo per sbaglio
            with self.lock:
                if name in self.queued:
                    self.queued.remove(name)
                if search is None:
                    continue
                self.running = {"search": name, "started": now_iso(), "kept_total": 0,
                                "sources": [{"source": s, "state": "waiting", "detail": "in attesa", "found": 0, "kept": 0}
                                            for s in search.get("sources", [])]}
            error = None
            try:
                _wait_for_other_collection()
                LOCK.write_text(str(os.getpid()))
                try:
                    self.run_search(search, self.progress)
                finally:
                    LOCK.unlink(missing_ok=True)
            except Exception as e:
                traceback.print_exc()
                error = str(e)
            with self.lock:
                kept = self.running["kept_total"] if self.running else 0
                self.last = {"search": name, "finished": now_iso(), "kept": kept, "error": error}
                self.running = None

    @staticmethod
    def _run_search(search: dict, progress: Callable) -> None:
        cfg = app.load_config()
        db = Database(ROOT / cfg["database"])
        try:
            saved = is_saved(search)
            db.record_new = saved and db.count() > 0
            app.collect(cfg, db, [search], progress)
            if not saved:
                db.drop_events(search["name"])          # le ricerche temporanee non danno notifiche
            app.store().touch(search["name"], cfg["config_searches"])
            app.cleanup_temporary(app.load_config(), db)
            build_site(db, app.load_config(), ROOT / "site")
        finally:
            db.conn.close()


def _wait_for_other_collection() -> None:
    """Se la raccolta delle 3 ore gira in un altro processo, aspetta che finisca."""
    while LOCK.exists() and time.time() - LOCK.stat().st_mtime < 2 * 3600:
        time.sleep(5)


class _Tee(io.TextIOBase):
    """Scrive l'output nel registro e passa le righe "pagina x/y" al Collector."""

    def __init__(self, path: Path, collector: Collector):
        self.f = path.open("a", encoding="utf-8")
        self.collector = collector

    def write(self, s: str) -> int:
        self.f.write(s)
        self.f.flush()
        for line in s.splitlines():
            self.collector.page_line(line)
        return len(s)


# ---------- HTTP ----------

def search_summary(db: Database, cfg: dict, collector: Collector) -> list[dict]:
    status = collector.status()
    busy = {status["running"]["search"]} if status["running"] else set()
    rows = {r["search"]: r for r in db.conn.execute(
        "SELECT search, MAX(last_seen) AS last_seen FROM listings GROUP BY search")}
    # stessi numeri dell'elenco del sito: la stessa auto su più siti conta una volta
    active = [dict(r) for r in db.conn.execute("SELECT * FROM listings WHERE active = 1")]
    merge_duplicates(active)
    cards: dict[str, int] = {}
    for l in active:
        if not l.get("dup_of"):
            cards[l["search"]] = cards.get(l["search"], 0) + 1
    out = []
    for s in cfg["searches"]:
        r = rows.get(s["name"])
        out.append({
            "name": s["name"], "make": s["make"], "model": s["model"],
            "year_min": s.get("year_min"), "year_max": s.get("year_max"),
            "km_min": s.get("km_min"), "km_max": s.get("km_max"),
            "must_contain": s.get("must_contain", []), "price_min_eur": s.get("price_min_eur"),
            "saved": is_saved(s), "from_config": s.get("saved") is None and s.get("created") is None,
            "created": s.get("created"), "last_run": s.get("last_run"),
            "active": cards.get(s["name"], 0),
            "last_update": r["last_seen"] if r else None,
            "state": "running" if s["name"] in busy else ("queued" if s["name"] in status["queue"] else "idle"),
        })
    return out


def make_handler(collector: Collector, taxonomy: Taxonomy | None = None):
    tax = taxonomy or Taxonomy(ROOT / "data" / "taxonomy")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ImportHelper"

        def log_message(self, fmt, *args):  # niente log di ogni richiesta
            pass

        # ---- risposte ----
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, msg: str, code: int = 400) -> None:
            self._json({"error": msg}, code)

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("localhost", "127.0.0.1")

        def _db(self):
            cfg = app.load_config()
            return cfg, Database(ROOT / cfg["database"])

        # ---- GET ----
        def do_GET(self):
            if not self._host_ok():
                return self._error("Host non permesso", 403)
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                cfg, db = self._db()
                try:
                    html = render(db, cfg, server=True, quiet=True)
                finally:
                    db.conn.close()
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if url.path == "/api/status":
                return self._json(collector.status())
            if url.path == "/api/version":
                cfg, db = self._db()
                try:
                    return self._json({"version": data_version(db, cfg)})
                finally:
                    db.conn.close()
            if url.path == "/api/searches":
                cfg, db = self._db()
                try:
                    return self._json(search_summary(db, cfg, collector))
                finally:
                    db.conn.close()
            if url.path == "/api/makes":
                return self._json(tax.makes())
            if url.path == "/api/models":
                make = (parse_qs(url.query).get("make") or [""])[0]
                return self._json(tax.models(make))
            return self._error("Pagina non trovata", 404)

        # ---- POST ----
        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-ImportHelper") != "1":
                return self._error("Richiesta non permessa", 403)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                return self._error("Dati non validi")
            path = urlparse(self.path).path
            cfg = app.load_config()
            store = app.store()
            if path == "/api/searches":
                try:
                    search = store.add(make_search(body), cfg["config_searches"])
                except ValueError as e:
                    return self._error(str(e))
                collector.enqueue(search["name"])
                return self._json({"search": search, "status": collector.status()}, 201)
            if path == "/api/searches/save":
                name = body.get("name", "")
                if not store.set_saved(name, bool(body.get("saved", True)), cfg["config_searches"]):
                    return self._error("Ricerca non trovata", 404)
                return self._json({"name": name, "saved": bool(body.get("saved", True))})
            if path == "/api/searches/refresh":
                name = body.get("name", "")
                if not any(s["name"] == name for s in cfg["searches"]):
                    return self._error("Ricerca non trovata", 404)
                collector.enqueue(name)
                return self._json(collector.status())
            if path == "/api/searches/delete":
                name = body.get("name", "")
                if not store.remove(name, cfg["config_searches"]):
                    return self._error("Ricerca non trovata", 404)
                db = Database(ROOT / cfg["database"])
                try:
                    n = db.purge_search(name)
                    build_site(db, app.load_config(), ROOT / "site")
                finally:
                    db.conn.close()
                return self._json({"deleted": name, "listings_removed": n})
            if path == "/api/refresh-all":
                # la raccolta delle 3 ore: solo le ricerche salvate
                added = [s["name"] for s in cfg["searches"] if is_saved(s) and collector.enqueue(s["name"])]
                return self._json({"queued": added})
            return self._error("Pagina non trovata", 404)

    return Handler


def main() -> None:
    collector = Collector()
    log = ROOT / "data" / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = _Tee(log, collector)
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), make_handler(collector))
    except OSError:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} porta {PORT} occupata: il server è già acceso.")
        return
    cfg = app.load_config()
    db = Database(ROOT / cfg["database"])
    try:
        for name in app.cleanup_temporary(cfg, db):
            print(f"Ricerca temporanea scaduta e cancellata: {name}")
    finally:
        db.conn.close()
    collector.start()
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} server acceso su http://localhost:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
