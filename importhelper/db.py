"""Database SQLite: salva gli annunci e la cronologia dei prezzi."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    search TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    make TEXT, model TEXT, version TEXT,
    year INTEGER, first_registration TEXT,
    km INTEGER,
    price REAL, currency TEXT, price_eur REAL,
    country TEXT, city TEXT,
    seller TEXT, seller_type TEXT,
    condition TEXT, fuel TEXT, power_kw INTEGER,
    photos TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS price_history (
    listing_id TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    price REAL, currency TEXT, price_eur REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    type TEXT NOT NULL,             -- new | price_drop | price_up | removed
    listing_id TEXT NOT NULL,
    old_price_eur REAL,
    new_price_eur REAL
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_listings_search ON listings(search);
CREATE INDEX IF NOT EXISTS idx_history_listing ON price_history(listing_id);
"""

FIELDS = [
    "source", "source_id", "search", "url", "title", "make", "model", "version",
    "year", "first_registration", "km", "price", "currency", "price_eur",
    "country", "city", "seller", "seller_type", "condition", "fuel", "power_kw",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute("PRAGMA busy_timeout = 30000")   # server e raccolta possono scrivere insieme
        self._migrate_ids()
        # False durante il primo giro: centinaia di "nuovi annunci" non sono una notizia
        self.record_new = True
        self._backfill_events()

    def _migrate_ids(self) -> None:
        """Vecchi id "fonte:numero" -> "fonte:numero@ricerca" (una volta sola)."""
        from .models import listing_id
        rows = self.conn.execute("SELECT id, source, source_id, search FROM listings WHERE id NOT LIKE '%@%'").fetchall()
        if not rows:
            return
        with self.conn:
            for r in rows:
                new = listing_id(r["source"], r["source_id"], r["search"])
                self.conn.execute("UPDATE listings SET id = ? WHERE id = ?", (new, r["id"]))
                self.conn.execute("UPDATE price_history SET listing_id = ? WHERE listing_id = ?", (new, r["id"]))
                self.conn.execute("UPDATE events SET listing_id = ? WHERE listing_id = ?", (new, r["id"]))

    def _backfill_events(self) -> None:
        """Se la tabella eventi è vuota, ricrea ribassi/rialzi dalla cronologia dei prezzi."""
        if self.conn.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            return
        prev: dict[str, float] = {}
        for h in self.conn.execute(
            "SELECT listing_id, seen_at, price_eur FROM price_history ORDER BY listing_id, seen_at"
        ).fetchall():
            old = prev.get(h["listing_id"])
            if old is not None and h["price_eur"] is not None and h["price_eur"] != old:
                kind = "price_drop" if h["price_eur"] < old else "price_up"
                self.add_event(h["seen_at"], kind, h["listing_id"], old, h["price_eur"])
            if h["price_eur"] is not None:
                prev[h["listing_id"]] = h["price_eur"]
        self.conn.commit()

    def add_event(self, at: str, kind: str, listing_id: str, old=None, new=None) -> None:
        self.conn.execute(
            "INSERT INTO events (created_at, type, listing_id, old_price_eur, new_price_eur) VALUES (?, ?, ?, ?, ?)",
            (at, kind, listing_id, old, new),
        )

    def events(self, since: str = "") -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE created_at >= ? ORDER BY created_at DESC, id DESC", (since,)
        ).fetchall()

    def upsert(self, l: Listing, seen_at: str) -> str:
        """Salva un annuncio. Ritorna "new", "price_drop", "price_up" o "same"."""
        row = self.conn.execute(
            "SELECT price, price_eur FROM listings WHERE id = ?", (l.id,)
        ).fetchone()
        values = {f: getattr(l, f) for f in FIELDS}
        values["photos"] = json.dumps(l.photos)

        if row is None:
            cols = ["id", *values, "first_seen", "last_seen", "active"]
            self.conn.execute(
                f"INSERT INTO listings ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [l.id, *values.values(), seen_at, seen_at, 1],
            )
            self._history(l, seen_at)
            status = "new"
            if self.record_new:
                self.add_event(seen_at, "new", l.id, None, l.price_eur)
        else:
            sets = ", ".join(f"{k} = ?" for k in values)
            self.conn.execute(
                f"UPDATE listings SET {sets}, last_seen = ?, active = 1 WHERE id = ?",
                [*values.values(), seen_at, l.id],
            )
            old = row["price"]
            l.old_price_eur = row["price_eur"]
            if l.price is not None and old is not None and l.price != old:
                self._history(l, seen_at)
                status = "price_drop" if l.price < old else "price_up"
                self.add_event(seen_at, status, l.id, row["price_eur"], l.price_eur)
            else:
                status = "same"
        return status

    def _history(self, l: Listing, seen_at: str) -> None:
        self.conn.execute(
            "INSERT INTO price_history (listing_id, seen_at, price, currency, price_eur) VALUES (?, ?, ?, ?, ?)",
            (l.id, seen_at, l.price, l.currency, l.price_eur),
        )

    def mark_inactive(self, source: str, search: str, run_started: str) -> int:
        """Segna come non più attivi gli annunci non visti in questo giro."""
        where = "source = ? AND search = ? AND last_seen < ? AND active = 1"
        args = (source, search, run_started)
        gone = self.conn.execute(f"SELECT id, price_eur FROM listings WHERE {where}", args).fetchall()
        at = now()
        for g in gone:
            self.add_event(at, "removed", g["id"], g["price_eur"], None)
        self.conn.execute(f"UPDATE listings SET active = 0 WHERE {where}", args)
        return len(gone)

    def deactivate_below(self, search: str, min_eur: float) -> int:
        """Nasconde gli annunci già salvati con prezzo in euro sotto il minimo."""
        cur = self.conn.execute(
            "UPDATE listings SET active = 0 WHERE search = ? AND price_eur < ? AND active = 1",
            (search, min_eur),
        )
        return cur.rowcount

    def deactivate_ids(self, ids: list[str]) -> int:
        n = 0
        for i in ids:
            n += self.conn.execute("UPDATE listings SET active = 0 WHERE id = ? AND active = 1", (i,)).rowcount
        return n

    def purge_search(self, search: str) -> int:
        """Cancella annunci, storico prezzi e notifiche di una ricerca (ricerca eliminata o scaduta)."""
        ids = [r[0] for r in self.conn.execute("SELECT id FROM listings WHERE search = ?", (search,))]
        with self.conn:
            for table, col in (("events", "listing_id"), ("price_history", "listing_id"), ("listings", "id")):
                self.conn.executemany(f"DELETE FROM {table} WHERE {col} = ?", [(i,) for i in ids])
        return len(ids)

    def drop_events(self, search: str) -> None:
        """Le ricerche temporanee non generano notifiche."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM events WHERE listing_id IN (SELECT id FROM listings WHERE search = ?)", (search,))

    def count_for(self, source: str, search: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM listings WHERE source = ? AND search = ?", (source, search)
        ).fetchone()[0]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]

    def get(self, ids: list[str]) -> list[sqlite3.Row]:
        if not ids:
            return []
        q = f"SELECT * FROM listings WHERE id IN ({', '.join('?' * len(ids))})"
        return self.conn.execute(q, ids).fetchall()

    def all(self, active_only: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM listings"
        if active_only:
            q += " WHERE active = 1"
        return self.conn.execute(q + " ORDER BY search, price_eur").fetchall()

    def commit(self) -> None:
        self.conn.commit()
