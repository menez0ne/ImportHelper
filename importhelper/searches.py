"""Ricerche: quelle di config.json più quelle create dal sito (data/searches.json).

Una ricerca fatta dal sito è "temporanea" finché non la salvi: gira una volta,
non rientra nella raccolta delle 3 ore, non crea notifiche e dopo 7 giorni
viene cancellata con i suoi annunci. Quelle salvate (e quelle di config.json)
si aggiornano da sole e generano notifiche.

Ogni ricerca è generica: marca e modello come "slug" di AutoScout24 (porsche / 911,
tesla / model-s); le fonti a testo libero cercano "marca modello parole-obbligatorie".
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_EXCLUDE = ["noleggio", "LOA", "LLD", "lungo termine", "rental", "Miete"]
TEMP_DAYS = 7
DEFAULT_SOURCES = ["autoscout24", "marktplaats", "2dehands", "otomoto", "willhaben", "blocket", "finn"]


def slug(text: str) -> str:
    """"Mercedes-Benz" -> "mercedes-benz", "Model S" -> "model-s", "Citroën" -> "citroen"."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _words(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    return [w.strip() for w in value or [] if w and w.strip()]


def _year(value):
    if value in (None, ""):
        return None
    y = int(value)
    if not 1950 <= y <= 2100:
        raise ValueError(f"anno non valido: {value}")
    return y


def make_search(form: dict) -> dict:
    """Crea una ricerca dai campi del modulo del sito. Solleva ValueError se mancano dati."""
    make_label = (form.get("make") or "").strip()
    model_label = (form.get("model") or "").strip()
    if not make_label or not model_label:
        raise ValueError("Scrivi marca e modello.")
    y1, y2 = _year(form.get("year_min")), _year(form.get("year_max"))
    if y1 and y2 and y1 > y2:
        y1, y2 = y2, y1
    must = _words(form.get("must_contain"))
    exclude = _words(form["exclude_words"]) if "exclude_words" in form else list(DEFAULT_EXCLUDE)
    price_min = form.get("price_min_eur")
    years = f"{y1}–{y2}" if y1 and y2 else (f"dal {y1}" if y1 else (f"fino al {y2}" if y2 else ""))
    nice = lambda w: w if not w.islower() else (w.upper() if any(c.isdigit() for c in w) else w.capitalize())
    name = " ".join(x for x in (make_label, model_label, " ".join(nice(w) for w in must), years) if x)
    return {
        "name": re.sub(r"\s+", " ", name).strip(),
        "make": slug(make_label),
        "model": slug(model_label),
        "make_label": make_label,
        "model_label": model_label,
        "year_min": y1,
        "year_max": y2,
        "must_contain": must,
        "exclude_words": exclude,
        "price_min_eur": int(price_min) if price_min not in (None, "") else None,
        "sources": list(form.get("sources") or DEFAULT_SOURCES),
        "saved": bool(form.get("save")),
        "created": _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_saved(search: dict) -> bool:
    """Le ricerche di config.json non hanno il campo: sono salvate."""
    return search.get("saved", True)


class SearchStore:
    """data/searches.json: {"searches": [...], "removed": [nomi di ricerche di config.json tolte dal sito]}"""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        return {"searches": data.get("searches", []), "removed": data.get("removed", [])}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def merged(self, config_searches: list[dict]) -> list[dict]:
        data = self._load()
        out = [s for s in config_searches if s["name"] not in data["removed"]]
        names = {s["name"] for s in out}
        out += [s for s in data["searches"] if s["name"] not in names]
        return out

    def find(self, name: str, config_searches: list[dict]) -> dict | None:
        return next((s for s in self.merged(config_searches) if s["name"].lower() == name.lower()), None)

    def add(self, search: dict, config_searches: list[dict]) -> dict:
        """Aggiunge la ricerca. Se esiste già la riusa (e la salva, se richiesto). Ritorna quella in uso."""
        existing = self.find(search["name"], config_searches)
        if existing:
            if search.get("saved") and not is_saved(existing):
                self.set_saved(existing["name"], True, config_searches)
                existing = self.find(search["name"], config_searches)
            return existing
        data = self._load()
        data["removed"] = [n for n in data["removed"] if n != search["name"]]
        data["searches"].append(search)
        self._save(data)
        return search

    def _update(self, name: str, config_searches: list[dict], **fields) -> bool:
        data = self._load()
        for s in data["searches"]:
            if s["name"] == name:
                s.update(fields)
                self._save(data)
                return True
        base = next((s for s in config_searches if s["name"] == name), None)
        if base is None:
            return False
        # ricerca di config.json: ne teniamo una copia modificata e nascondiamo l'originale
        data["searches"].append({**base, **fields})
        if name not in data["removed"]:
            data["removed"].append(name)
        self._save(data)
        return True

    def set_saved(self, name: str, saved: bool, config_searches: list[dict]) -> bool:
        # "Non salvare più": torna temporanea e i 7 giorni ripartono da adesso
        return self._update(name, config_searches, saved=saved, **({} if saved else {"last_run": _now()}))

    def touch(self, name: str, config_searches: list[dict]) -> None:
        search = self.find(name, config_searches)
        if search and search.get("saved") is not None:   # solo quelle create dal sito
            self._update(search["name"], config_searches, last_run=_now())

    def expired(self, config_searches: list[dict], days: int = TEMP_DAYS) -> list[str]:
        """Ricerche temporanee non usate da più di `days` giorni."""
        limit = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        return [s["name"] for s in self.merged(config_searches)
                if not is_saved(s) and (s.get("last_run") or s.get("created") or "") < limit]

    def remove(self, name: str, config_searches: list[dict]) -> bool:
        data = self._load()
        before = len(data["searches"])
        data["searches"] = [s for s in data["searches"] if s["name"] != name]
        found = len(data["searches"]) < before
        if any(s["name"] == name for s in config_searches) and name not in data["removed"]:
            data["removed"].append(name)
            found = True
        self._save(data)
        return found
