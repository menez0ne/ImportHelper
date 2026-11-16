"""Elenco marche e modelli per il suggerimento nel modulo "Cerca un'auto".

Viene dalle pagine di AutoScout24 (il blocco "taxonomy" in __NEXT_DATA__):
una richiesta per l'elenco delle marche e una per i modelli di ciascuna marca,
poi tutto resta in cache in data/taxonomy/ per 30 giorni.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .http import Http
from .searches import slug
from .sources.common import next_data

DOMAIN = "https://www.autoscout24.it"
MAX_AGE = 30 * 86400


class Taxonomy:
    def __init__(self, cache_dir: Path, http: Http | None = None):
        self.dir = Path(cache_dir)
        self.http = http or Http(3)

    def _cached(self, name: str):
        p = self.dir / name
        if p.exists() and time.time() - p.stat().st_mtime < MAX_AGE:
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def _store(self, name: str, data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _page(self, path: str) -> dict:
        r = self.http.get(DOMAIN + path)
        return next_data(r.text).get("props", {}).get("pageProps", {}).get("taxonomy", {}) if r else {}

    def makes(self) -> list[dict]:
        cached = self._cached("makes.json")
        if cached is not None:
            return cached
        tx = self._page("/lst")
        out = [{"label": m["label"], "slug": slug(m["label"]), "id": m["value"]} for m in tx.get("makesSorted") or []]
        if out:
            self._store("makes.json", out)
        return out

    def models(self, make: str) -> list[dict]:
        make = slug(make)
        if not make:
            return []
        name = f"models-{make}.json"
        cached = self._cached(name)
        if cached is not None:
            return cached
        tx = self._page(f"/lst/{make}")
        seen, out = set(), []
        for group in (tx.get("models") or {}).values():
            for m in group:
                label = m.get("label") or ""
                if label and label.lower() not in ("altro", "other", "andere") and slug(label) not in seen:
                    seen.add(slug(label))
                    out.append({"label": label, "slug": slug(label)})
        out.sort(key=lambda m: m["label"].lower())
        if out:
            self._store(name, out)
        return out
