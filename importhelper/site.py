"""Sito statico: python -m importhelper site  ->  site/index.html

Un'unica pagina con i dati incorporati come JSON: elenco degli annunci attivi
con filtri, una scheda per ogni annuncio (#/annuncio/<id>) e la sezione
Notifiche (#/notifiche) con nuovi annunci, variazioni di prezzo e annunci
spariti negli ultimi 90 giorni. Non serve un server.
"""
from __future__ import annotations

import json
import re
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database
from .searches import is_saved

TEMPLATE = Path(__file__).with_name("site_template.html")
EVENT_DAYS = 90


def _listing(r, history: dict) -> dict:
    d = dict(r)
    d["photos"] = json.loads(d.get("photos") or "[]")
    d["history"] = history.get(d["id"], [])
    d["active"] = bool(d.get("active"))
    return d


SOURCE_PRIORITY = ["autoscout24", "marktplaats", "2dehands", "willhaben", "otomoto", "blocket", "finn"]


def _same_car(a: dict, b: dict) -> bool:
    """Stessa auto su due siti: stessa ricerca, Paese, città e anno; km ±1% e prezzo ±2%."""
    if a["source"] == b["source"] or a["search"] != b["search"] or a["country"] != b["country"]:
        return False
    if a.get("year") != b.get("year") or None in (a.get("km"), b.get("km"), a.get("price_eur"), b.get("price_eur")):
        return False
    # le auto nuove hanno tutte pochi km e prezzi simili: se la città è nota deve coincidere
    city = lambda x: re.sub(r"[^a-z]", "", (x.get("city") or "").lower())
    if city(a) and city(b) and city(a) != city(b):
        return False
    km_ok = abs(a["km"] - b["km"]) <= max(0.01 * max(a["km"], b["km"]), 50)
    price_ok = abs(a["price_eur"] - b["price_eur"]) <= 0.02 * max(a["price_eur"], b["price_eur"])
    return km_ok and price_ok


def merge_duplicates(listings: list[dict]) -> int:
    """Segna i doppioni: il principale riceve "also" (gli altri siti), i doppioni "dup_of"."""
    rank = lambda l: (SOURCE_PRIORITY.index(l["source"]) if l["source"] in SOURCE_PRIORITY else 99, l["id"])
    active = sorted((l for l in listings if l.get("active")), key=rank)
    merged = 0
    for i, main in enumerate(active):
        if main.get("dup_of"):
            continue
        for other in active[i + 1:]:
            if other.get("dup_of") or any(x["source"] == other["source"] for x in main.get("also", [])):
                continue
            if _same_car(main, other):
                other["dup_of"] = main["id"]
                main.setdefault("also", []).append(
                    {"id": other["id"], "source": other["source"], "url": other["url"], "price_eur": other["price_eur"]})
                merged += 1
    return merged


def _payload(db: Database, cfg: dict, quiet: bool = False) -> dict:
    history: dict[str, list] = {}
    for h in db.conn.execute(
        "SELECT listing_id, seen_at, price, currency, price_eur FROM price_history ORDER BY seen_at"
    ):
        history.setdefault(h["listing_id"], []).append(
            {"at": h["seen_at"], "price": h["price"], "currency": h["currency"], "eur": h["price_eur"]}
        )
    since = (datetime.now(timezone.utc) - timedelta(days=EVENT_DAYS)).isoformat(timespec="seconds")
    events = [dict(e) for e in db.events(since)]
    listings = {r["id"]: _listing(r, history) for r in db.all()}
    # annunci non più attivi ma citati nelle notifiche: servono per la loro scheda
    missing = list({e["listing_id"] for e in events} - listings.keys())
    for r in db.get(missing):
        listings[r["id"]] = _listing(r, history)
    temp = {s["name"] for s in cfg["searches"] if not is_saved(s)}
    for l in listings.values():
        l["temp"] = l["search"] in temp      # visibili solo aprendo quella ricerca
    events = [e for e in events if e["listing_id"] in listings and not listings[e["listing_id"]]["temp"]]
    merged = merge_duplicates(list(listings.values()))
    if merged and not quiet:
        print(f"Doppioni tra siti diversi uniti in un'unica scheda: {merged}")
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "searches": [s["name"] for s in cfg["searches"] if is_saved(s)],
        "temp_searches": [s["name"] for s in cfg["searches"] if not is_saved(s)],
        "listings": list(listings.values()),
        "events": events,
    }


def data_version(db: Database, cfg: dict) -> str:
    """Cambia ogni volta che cambiano annunci, notifiche o ricerche: la pagina aperta si ricarica."""
    r = db.conn.execute("SELECT COUNT(*), SUM(active), MAX(last_seen) FROM listings").fetchone()
    e = db.conn.execute("SELECT COUNT(*), MAX(id) FROM events").fetchone()
    names = "|".join(f"{s['name']}:{int(is_saved(s))}" for s in cfg["searches"])
    return f"{r[0]}-{r[1]}-{r[2]}-{e[0]}-{e[1]}-{zlib.crc32(names.encode())}"


def render(db: Database, cfg: dict, server: bool = False, quiet: bool = False) -> str:
    """La pagina completa. server=True mostra anche "Cerca un'auto" (serve il server locale)."""
    payload = _payload(db, cfg, quiet)
    payload["server"] = server
    payload["version"] = data_version(db, cfg)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/{}", data)


def build(db: Database, cfg: dict, out_dir: Path) -> Path:
    """Versione statica (site/index.html): si apre anche senza server, ma senza la ricerca."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render(db, cfg), encoding="utf-8")
    tmp.replace(path)
    return path
