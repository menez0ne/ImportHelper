"""Ricerche dal sito e API del server locale, con una raccolta finta (nessuna richiesta ai siti)."""
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from importhelper import __main__ as app
from importhelper import server
from importhelper.db import Database
from importhelper.models import Listing
from importhelper.searches import SearchStore, is_saved, make_search, slug

REAL_ROOT = Path(__file__).resolve().parent.parent


class SearchTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual([slug(x) for x in ("Mercedes-Benz", "Model S", "Citroën", " 911 ")],
                         ["mercedes-benz", "model-s", "citroen", "911"])

    def test_make_search(self):
        s = make_search({"make": "Porsche", "model": "911", "year_min": "2026", "year_max": "2022",
                         "must_contain": "gt3, ", "price_min_eur": "50000"})
        self.assertEqual(s["name"], "Porsche 911 GT3 2022–2026")
        self.assertEqual((s["make"], s["model"], s["year_min"], s["year_max"]), ("porsche", "911", 2022, 2026))
        self.assertEqual((s["must_contain"], s["price_min_eur"]), (["gt3"], 50000))
        self.assertIn("noleggio", s["exclude_words"])          # parole da escludere di default
        self.assertEqual(make_search({"make": "Tesla", "model": "Model S", "must_contain": ["plaid"]})["name"],
                         "Tesla Model S Plaid")
        with self.assertRaises(ValueError):
            make_search({"make": "Audi", "model": ""})
        with self.assertRaises(ValueError):
            make_search({"make": "Audi", "model": "RS5", "year_min": "20"})

    def test_make_search_km(self):
        s = make_search({"make": "Audi", "model": "RS5", "km_min": "80000", "km_max": "10000"})
        self.assertEqual((s["km_min"], s["km_max"]), (10000, 80000))
        self.assertEqual(s["name"], "Audi RS5 10.000–80.000 km")
        self.assertEqual(make_search({"make": "Audi", "model": "RS5", "km_max": "50000"})["name"],
                         "Audi RS5 fino a 50.000 km")
        self.assertEqual(make_search({"make": "Audi", "model": "RS5", "year_min": 2024, "km_min": 5000})["name"],
                         "Audi RS5 dal 2024 da 5.000 km")
        s = make_search({"make": "Audi", "model": "RS5", "km_min": "0", "km_max": ""})
        self.assertEqual((s["km_min"], s["km_max"], s["name"]), (None, None, "Audi RS5"))
        with self.assertRaises(ValueError):
            make_search({"make": "Audi", "model": "RS5", "km_max": "tanti"})

    def test_store(self):
        with tempfile.TemporaryDirectory() as d:
            store = SearchStore(Path(d) / "s.json")
            config = [{"name": "Audi RS5 2026"}]
            store.add(make_search({"make": "Porsche", "model": "911"}), config)   # temporanea
            self.assertEqual([s["name"] for s in store.merged(config)], ["Audi RS5 2026", "Porsche 911"])
            self.assertFalse(is_saved(store.find("Porsche 911", config)))
            self.assertTrue(is_saved(store.find("Audi RS5 2026", config)))      # config.json = salvata
            # la stessa ricerca di nuovo, questa volta "salva": riusa quella esistente e la salva
            again = store.add(make_search({"make": "porsche", "model": "911", "save": True}), config)
            self.assertTrue(again["saved"])
            self.assertEqual(len(store.merged(config)), 2)
            # "Non salvare più" su una ricerca di config.json
            self.assertTrue(store.set_saved("Audi RS5 2026", False, config))
            self.assertFalse(is_saved(store.find("Audi RS5 2026", config)))
            self.assertEqual(store.expired(config), [])                         # non ancora scaduta
            self.assertEqual(store.expired(config, days=-1), ["Audi RS5 2026"])  # "dopo 7 giorni"
            self.assertTrue(store.remove("Audi RS5 2026", config))
            self.assertTrue(store.remove("Porsche 911", config))
            self.assertEqual(store.merged(config), [])


class ApiTests(unittest.TestCase):
    """Server vero su una porta libera, in una cartella temporanea."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # config.json vero più una ricerca fissa (nella repo config.json parte senza ricerche)
        cfg = json.loads((REAL_ROOT / "config.json").read_text(encoding="utf-8"))
        cfg["searches"] = [{"name": "Audi RS5 2026", "make": "audi", "model": "rs5", "year_min": 2026,
                            "year_max": 2026, "must_contain": [], "sources": ["autoscout24"]}]
        (self.tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (self.tmp / "data").mkdir()
        self._roots = (app.ROOT, server.ROOT, server.LOCK)
        app.ROOT = server.ROOT = self.tmp
        server.LOCK = self.tmp / "data" / "raccolta.lock"
        self.ran = []

        def fake_run(search, progress):
            self.ran.append(search["name"])
            for src in search["sources"]:
                progress("source_start", source=src)
                progress("source_done", source=src, found=3, kept=2 if src == "autoscout24" else 0)

        self.collector = server.Collector(fake_run).start()

        class Tax:
            makes = staticmethod(lambda: [{"label": "Porsche", "slug": "porsche"}])
            models = staticmethod(lambda make: [{"label": "911", "slug": "911"}] if make == "porsche" else [])

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.collector, Tax()))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        app.ROOT, server.ROOT, server.LOCK = self._roots
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, path, body=None, header=True):
        headers = {"Content-Type": "application/json"}
        if header:
            headers["X-ImportHelper"] = "1"
        req = urllib.request.Request(self.base + path, headers=headers, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null") if "json" in r.headers["Content-Type"] else r.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait_idle(self):
        for _ in range(100):
            st = self.call("/api/status")[1]
            if not st["running"] and not st["queue"]:
                return st
            time.sleep(0.05)
        self.fail("la raccolta non finisce")

    def test_create_search_and_progress(self):
        code, res = self.call("/api/searches", {"make": "Porsche", "model": "911", "year_min": 2022,
                                                "year_max": 2026, "must_contain": "gt3"})
        self.assertEqual(code, 201)
        self.assertEqual(res["search"]["name"], "Porsche 911 GT3 2022–2026")
        st = self.wait_idle()
        self.assertEqual(self.ran, ["Porsche 911 GT3 2022–2026"])
        self.assertEqual((st["last"]["search"], st["last"]["kept"]), ("Porsche 911 GT3 2022–2026", 2))
        names = [s["name"] for s in self.call("/api/searches")[1]]
        self.assertIn("Porsche 911 GT3 2022–2026", names)
        self.assertIn("Audi RS5 2026", names)                  # quelle di config.json restano
        # la stessa ricerca due volte: riusa quella che c'è e la rilancia
        code, res = self.call("/api/searches", {"make": "porsche", "model": "911", "year_min": 2022,
                                                "year_max": 2026, "must_contain": "gt3"})
        self.assertEqual((code, res["search"]["name"]), (201, "Porsche 911 GT3 2022–2026"))
        self.wait_idle()
        self.assertEqual(len(self.ran), 2)
        self.assertEqual(self.call("/api/searches", {"make": "Audi", "model": ""})[0], 400)

    def test_saved_and_temporary(self):
        self.call("/api/searches", {"make": "Porsche", "model": "911"})                 # temporanea
        self.call("/api/searches", {"make": "BMW", "model": "M3", "save": True})        # salvata
        self.wait_idle()
        by = {s["name"]: s for s in self.call("/api/searches")[1]}
        self.assertEqual((by["Porsche 911"]["saved"], by["BMW M3"]["saved"]), (False, True))
        # la raccolta delle 3 ore prende solo le salvate (e quelle di config.json)
        self.ran.clear()
        queued = self.call("/api/refresh-all", {})[1]["queued"]
        self.wait_idle()
        self.assertIn("BMW M3", queued)
        self.assertNotIn("Porsche 911", queued)
        # "Salva questa ricerca" e "Non salvare più"
        self.assertEqual(self.call("/api/searches/save", {"name": "Porsche 911", "saved": True})[0], 200)
        self.assertEqual(self.call("/api/searches/save", {"name": "BMW M3", "saved": False})[0], 200)
        by = {s["name"]: s for s in self.call("/api/searches")[1]}
        self.assertEqual((by["Porsche 911"]["saved"], by["BMW M3"]["saved"]), (True, False))
        self.assertEqual(self.call("/api/searches/save", {"name": "Nessuna"})[0], 404)

    def test_refresh_delete_and_protection(self):
        self.assertEqual(self.call("/api/searches", {"make": "Porsche", "model": "911"})[0], 201)
        self.wait_idle()
        self.assertEqual(self.call("/api/searches/refresh", {"name": "Porsche 911"})[0], 200)
        self.wait_idle()
        self.assertEqual(self.ran, ["Porsche 911", "Porsche 911"])
        self.assertEqual(self.call("/api/searches/refresh", {"name": "Nessuna"})[0], 404)
        # senza l'intestazione X-ImportHelper (es. da un altro sito) non si può fare nulla
        self.assertEqual(self.call("/api/searches/delete", {"name": "Porsche 911"}, header=False)[0], 403)
        db = Database(self.tmp / app.load_config()["database"])
        db.upsert(Listing(source="autoscout24", source_id="p1", search="Porsche 911", url="https://x", title="Porsche 911"), "2026-11-13")
        db.commit(); db.conn.close()
        before = self.call("/api/version")[1]["version"]
        code, res = self.call("/api/searches/delete", {"name": "Porsche 911"})
        self.assertEqual((code, res["listings_removed"]), (200, 1))   # "Elimina" cancella anche gli annunci
        # la pagina aperta se ne accorge (versione dei dati cambiata) e la ricerca non è più nei dati
        self.assertNotEqual(self.call("/api/version")[1]["version"], before)
        html = self.call("/")[1].decode("utf-8")
        self.assertNotIn('"search":"Porsche 911"', html)
        self.assertNotIn("Porsche 911", html.split('"searches":')[1].split("]")[0])
        self.assertNotIn("Porsche 911", [s["name"] for s in self.call("/api/searches")[1]])

    def test_temporary_cleanup_and_page(self):
        """Annunci di ricerche temporanee: niente notifiche, fuori dall'elenco, cancellati dopo 7 giorni."""
        self.call("/api/searches", {"make": "Porsche", "model": "911"})
        self.wait_idle()
        cfg = app.load_config()
        db = Database(self.tmp / cfg["database"])
        l = Listing(source="autoscout24", source_id="x1", search="Porsche 911", url="https://x", title="Porsche 911")
        db.upsert(l, "2026-11-13T10:00:00+00:00")
        db.drop_events("Porsche 911")
        db.commit()
        self.assertEqual(db.events(), [])
        from importhelper.site import _payload
        data = _payload(db, cfg, quiet=True)
        self.assertEqual(data["temp_searches"], ["Porsche 911"])
        self.assertNotIn("Porsche 911", data["searches"])     # non compare nel filtro "Modello" né nei conteggi
        self.assertTrue(next(x for x in data["listings"] if x["search"] == "Porsche 911")["temp"])
        # scadenza: con 7 giorni passati la ricerca e i suoi annunci spariscono
        app.store()._update("Porsche 911", cfg["config_searches"], last_run="2020-01-01T00:00:00+00:00")
        self.assertEqual(app.cleanup_temporary(app.load_config(), db), ["Porsche 911"])
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 0)
        db.conn.close()

    def test_pages(self):
        code, html = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(b'"server":true', html)
        self.assertEqual(self.call("/api/makes")[1][0]["slug"], "porsche")
        self.assertEqual(self.call("/api/models?make=porsche")[1][0]["label"], "911")
        self.assertEqual(self.call("/api/nulla")[0], 404)


if __name__ == "__main__":
    unittest.main()
