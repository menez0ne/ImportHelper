"""Uso:
    python -m importhelper            raccoglie gli annunci da tutte le fonti
    python -m importhelper list       mostra gli annunci attivi salvati
    python -m importhelper export     salva gli annunci attivi in data/annunci.csv
    python -m importhelper site       crea il sito statico in site/index.html
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from .currency import Converter
from .db import Database, now
from .http import Http
from .models import Listing, below_min_price, excluded_word, matches
from .searches import SearchStore, is_saved
from .site import build as build_site
from .sources import autoscout24, marktplaats, otomoto, schibsted, tesla, willhaben

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "autoscout24": autoscout24.fetch,
    "marktplaats": marktplaats.fetch,
    "2dehands": marktplaats.fetch_2dehands,
    "otomoto": otomoto.fetch,
    "willhaben": willhaben.fetch,
    "blocket": schibsted.fetch_blocket,
    "finn": schibsted.fetch_finn,
    "tesla": tesla.fetch,
}


def load_config() -> dict:
    """config.json più le ricerche create dal sito (data/searches.json)."""
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg["config_searches"] = cfg["searches"]
    cfg["searches"] = SearchStore(ROOT / "data" / "searches.json").merged(cfg["searches"])
    return cfg


def store() -> SearchStore:
    return SearchStore(ROOT / "data" / "searches.json")


def cleanup_temporary(cfg: dict, db: Database) -> list[str]:
    """Cancella le ricerche temporanee mai salvate e non usate da 7 giorni, con i loro annunci."""
    st = store()
    gone = st.expired(cfg["config_searches"])
    for name in gone:
        st.remove(name, cfg["config_searches"])
        db.purge_search(name)
    return gone


def _noop(*args, **kw) -> None:
    pass


def collect(cfg: dict, db: Database, searches: list[dict] | None = None, on_progress=_noop) -> dict[str, list]:
    """Raccoglie le ricerche indicate (di default tutte). on_progress(evento, **dati) per il sito."""
    print("Raccolta annunci in corso, ci vogliono alcuni minuti...", flush=True)
    fx = Converter(ROOT / "data" / "fx.json")
    events: dict[str, list] = {"new": [], "price_drop": [], "price_up": []}
    record_new = db.record_new
    for search in searches if searches is not None else cfg["searches"]:
        for source_name in search.get("sources", []):
            if source_name not in SOURCES or not cfg.get(source_name, {}).get("enabled", True):
                on_progress("source_skipped", search=search["name"], source=source_name)
                continue
            fetch, scfg = SOURCES[source_name], cfg[source_name]
            print(f"[{source_name}] {search['name']}...", flush=True)
            on_progress("source_start", search=search["name"], source=source_name)
            # prima volta che un sito viene letto per questa ricerca: i suoi annunci non sono "novità"
            db.record_new = record_new and db.count_for(source_name, search["name"]) > 0
            started = now()
            found = kept = too_cheap = excluded = 0
            try:
                for listing in fetch(search, scfg, Http(scfg.get("delay_seconds", 3))):
                    found += 1
                    if not matches(listing, search):
                        continue
                    if excluded_word(listing, search):
                        excluded += 1
                        continue
                    kept += 1
                    listing.price_eur = fx.to_eur(listing.price, listing.currency)
                    if below_min_price(listing, search):
                        kept -= 1
                        too_cheap += 1
                        continue
                    status = db.upsert(listing, now())
                    if status in events:
                        events[status].append(listing)
                gone = db.mark_inactive(source_name, search["name"], started) if found else 0
                db.commit()
                print(f"  {found} trovati, {kept} corrispondenti, {too_cheap} sotto il prezzo minimo, {excluded} esclusi (noleggio/leasing), {gone} non più online")
                on_progress("source_done", search=search["name"], source=source_name, found=found, kept=kept)
            except Exception as e:  # una fonte rotta non deve fermare le altre
                db.commit()
                print(f"  ERRORE: {e}")
                on_progress("source_error", search=search["name"], source=source_name, error=str(e))
        if search.get("exclude_words"):
            ids = [r["id"] for r in db.all() if r["search"] == search["name"] and excluded_word(
                Listing(source="", source_id="", search="", url="", title=r["title"] or "", version=r["version"] or ""), search)]
            hidden = db.deactivate_ids(ids)
            db.commit()
            if hidden:
                print(f"  {hidden} annunci già salvati nascosti per parole escluse")
        if search.get("price_min_eur"):
            hidden = db.deactivate_below(search["name"], search["price_min_eur"])
            db.commit()
            if hidden:
                print(f"  {hidden} annunci già salvati nascosti perché sotto {search['price_min_eur']} €")
    db.record_new = record_new
    return events


def show(db: Database) -> None:
    rows = db.all()
    current = None
    for r in rows:
        if r["search"] != current:
            current = r["search"]
            print(f"\n== {current} ==")
        price = f"{r['price_eur']:,.0f} €".replace(",", ".") if r["price_eur"] else "n.d."
        km = f"{r['km']:,} km".replace(",", ".") if r["km"] is not None else "n.d."
        print(f"{price:>12} | {km:>11} | {r['year'] or '':4} | {r['country']:2} | {r['title'][:40]:40} | {r['url']}")
    print(f"\nTotale annunci attivi: {len(rows)}")


def export(db: Database) -> Path:
    path = ROOT / "data" / "annunci.csv"
    rows = db.all()
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if rows:
            w.writerow(rows[0].keys())
            w.writerows([tuple(r) for r in rows])
    return path


def main() -> None:
    cfg = load_config()
    db = Database(ROOT / cfg["database"])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "list":
        show(db)
    elif cmd == "export":
        print(f"Salvato in {export(db)}")
    elif cmd == "site":
        print(f"Sito creato: {build_site(db, cfg, ROOT / 'site')}")
    else:
        db.record_new = db.count() > 0
        if not db.record_new:
            print("Primo giro: gli annunci trovati non vengono segnalati come novità.")
        for name in cleanup_temporary(cfg, db):
            print(f"Ricerca temporanea scaduta e cancellata: {name}")
        cfg = load_config()
        # solo le ricerche salvate si aggiornano da sole; le temporanee girano solo quando le lanci dal sito
        events = collect(cfg, db, [s for s in cfg["searches"] if is_saved(s)])
        print(f"\nNuovi: {len(events['new'])} | Ribassi: {len(events['price_drop'])} | Rialzi: {len(events['price_up'])}")
        for l in events["new"]:
            print(f"  NUOVO  {l.title} | {l.country} | {l.km} km | {l.price_eur} € | {l.url}")
        for l in events["price_drop"]:
            print(f"  RIBASSO  {l.title} | {l.price_eur} € | {l.url}")
        print(f"\nSito aggiornato: {build_site(db, cfg, ROOT / 'site')}")


if __name__ == "__main__":
    main()
