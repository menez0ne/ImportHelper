"""Funzioni comuni alle fonti: numeri, testo, Paesi, marca/modello."""
from __future__ import annotations

import json
import re
from typing import Optional

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# nomi dei Paesi come li scrivono i siti -> codice ISO
COUNTRY_CODES = {
    "nederland": "NL", "netherlands": "NL", "pays-bas": "NL", "niederlande": "NL",
    "belgië": "BE", "belgie": "BE", "belgique": "BE", "belgium": "BE", "belgien": "BE",
    "duitsland": "DE", "allemagne": "DE", "deutschland": "DE", "germany": "DE",
    "frankrijk": "FR", "france": "FR", "frankreich": "FR",
    "luxemburg": "LU", "luxembourg": "LU",
    "österreich": "AT", "oostenrijk": "AT", "autriche": "AT", "austria": "AT",
    "spanje": "ES", "espagne": "ES", "italië": "IT", "italie": "IT", "italien": "IT",
    "schweiz": "CH", "zwitserland": "CH", "suisse": "CH", "polska": "PL",
}


def to_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    s = str(value).strip()
    if re.fullmatch(r"\d+\.\d+", s):          # "9500.0"
        return int(round(float(s)))
    digits = re.sub(r"[^\d]", "", s)          # "65000 km", "€ 9.500"
    return int(digits) if digits else None


def country_code(name: str, default: str) -> str:
    return COUNTRY_CODES.get((name or "").strip().lower(), default)


def next_data(html: str) -> dict:
    m = NEXT_DATA_RE.search(html)
    return json.loads(m.group(1)) if m else {}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def query_text(search: dict) -> str:
    """Testo da cercare sui siti con ricerca libera: "audi rs5", "tesla model s"."""
    if search.get("query"):
        return search["query"]
    # le parole obbligatorie (es. "plaid") restringono la ricerca: meno risultati inutili
    words = [search["make"], search["model"], *search.get("must_contain", [])]
    return " ".join(words).replace("-", " ")


def is_model(text: str, search: dict) -> bool:
    """Le ricerche a testo libero restituiscono anche altre auto: teniamo solo marca+modello giusti."""
    t = _norm(text)
    return _norm(search["make"]) in t and _norm(search["model"]) in t


def source_param(search: dict, source: str, key: str, default: str) -> str:
    """Valore specifico di una fonte, se in config.json c'è "source_ids": {"otomoto": {"model": "..."}}."""
    return ((search.get("source_ids") or {}).get(source) or {}).get(key, default)
