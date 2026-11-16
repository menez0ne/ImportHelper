"""Formato unico di un annuncio, indipendente dalla fonte."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    source: str                 # es. "autoscout24", "tesla"
    source_id: str              # id dell'annuncio sulla fonte
    search: str                 # nome della ricerca in config.json
    url: str
    title: str
    make: str = ""
    model: str = ""
    version: str = ""
    year: Optional[int] = None
    first_registration: str = ""    # "MM/AAAA" se noto
    km: Optional[int] = None
    price: Optional[float] = None
    currency: str = "EUR"
    price_eur: Optional[float] = None
    country: str = ""           # codice ISO a 2 lettere, es. "DE"
    city: str = ""
    seller: str = ""
    seller_type: str = ""       # "dealer" / "private"
    condition: str = ""         # "used" / "new"
    fuel: str = ""
    power_kw: Optional[int] = None
    photos: list[str] = field(default_factory=list)
    old_price_eur: Optional[float] = None   # prezzo precedente, solo per gli avvisi di ribasso

    @property
    def id(self) -> str:
        # la ricerca fa parte dell'id: lo stesso annuncio può stare in due ricerche diverse
        return listing_id(self.source, self.source_id, self.search)


def listing_id(source: str, source_id: str, search: str) -> str:
    from .searches import slug
    return f"{source}:{source_id}@{slug(search)}"


COUNTRY_NAMES = {
    "DE": "Germania", "AT": "Austria", "BE": "Belgio", "ES": "Spagna", "FR": "Francia",
    "IT": "Italia", "LU": "Lussemburgo", "NL": "Paesi Bassi", "CH": "Svizzera",
    "PT": "Portogallo", "IE": "Irlanda", "GB": "Regno Unito", "SE": "Svezia",
    "NO": "Norvegia", "DK": "Danimarca", "FI": "Finlandia", "PL": "Polonia",
    "CZ": "Repubblica Ceca",
}


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get((code or "").upper(), code or "Paese n.d.")


def below_min_price(listing: Listing, search: dict) -> bool:
    """True se il prezzo in euro è sotto "price_min_eur" (es. rate di leasing/noleggio)."""
    minimum = search.get("price_min_eur")
    return bool(minimum) and listing.price_eur is not None and listing.price_eur < minimum


def excluded_word(listing: Listing, search: dict) -> str:
    """Ritorna la prima parola di "exclude_words" presente (parola intera) in titolo/versione, o ""."""
    text = f"{listing.title} {listing.version}"
    for word in search.get("exclude_words", []):
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.I):
            return word
    return ""


def matches(listing: Listing, search: dict) -> bool:
    """Controlla anno e parole obbligatorie (es. "plaid")."""
    text = " ".join([listing.title, listing.model, listing.version, listing.url]).lower()
    for word in search.get("must_contain", []):
        if word.lower() not in text:
            return False
    if listing.year is not None:
        if search.get("year_min") and listing.year < search["year_min"]:
            return False
        if search.get("year_max") and listing.year > search["year_max"]:
            return False
    return True
