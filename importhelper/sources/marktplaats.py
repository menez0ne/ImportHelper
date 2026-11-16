"""Marktplaats (NL) e 2dehands (BE): stesso gruppo, stessa API JSON usata dalle loro pagine.

GET <domain>/lrp/api/search?query=audi rs5&l1CategoryId=91&limit=100&offset=0
"""
from __future__ import annotations

from typing import Iterator
from urllib.parse import urlencode

from ..http import Http
from ..models import Listing
from .common import country_code, is_model, query_text, to_int

CARS_CATEGORY = 91   # "Auto's" su entrambi i siti
PAGE = 100


def _attrs(item: dict) -> dict:
    return {a.get("key"): a.get("value") for a in item.get("attributes") or []}


def _country(loc: dict, site_country: str) -> str:
    if loc.get("countryName"):
        return country_code(loc["countryName"], site_country)
    if loc.get("abroad"):  # venditore dell'altro sito del gruppo (NL su 2dehands, BE su Marktplaats)
        return "NL" if site_country == "BE" else "BE"
    return site_country


def parse(data: dict, search: dict, cfg: dict, source: str) -> list[Listing]:
    out = []
    domain = cfg["domain"].rstrip("/")
    for item in data.get("listings") or []:
        a = _attrs(item)
        title = item.get("title") or ""
        # Il campo "modello" del sito vale più del titolo ("RS4 Avant & Cabrio RS5 Cabrio" è una RS4),
        # ma alcuni venditori mettono la nuova RS5 sotto "A5": in quel caso basta il titolo,
        # purché ci siano anno e km (gli annunci senza sono ricambi o richieste).
        by_field = is_model(f"{search['make']} {a.get('model', '')}", search)
        by_title = is_model(title, search) and a.get("constructionYear") and a.get("mileage")
        if not (by_field or by_title):
            continue
        price = (item.get("priceInfo") or {}).get("priceCents")
        loc = item.get("location") or {}
        seller = item.get("sellerInformation") or {}
        photos = ["https:" + u.replace("$_82", "$_85") if u.startswith("//") else u for u in item.get("imageUrls") or []]
        out.append(Listing(
            source=source,
            source_id=str(item.get("itemId")),
            search=search["name"],
            url=domain + (item.get("vipUrl") or ""),
            title=title,
            make=search["make"].title(),
            model=a.get("model") or "",
            version=title,
            year=to_int(a.get("constructionYear")),
            km=to_int(a.get("mileage")),
            price=price / 100 if price else None,
            currency="EUR",
            country=_country(loc, cfg["country"]),
            city=loc.get("cityName") or "",
            seller=seller.get("sellerName") or "",
            seller_type="dealer" if seller.get("showSoiUrl") or seller.get("isVerified") else "private",
            condition="used",
            fuel=a.get("fuel") or "",
            photos=photos,
        ))
    return out


def fetch(search: dict, cfg: dict, http: Http, source: str = "marktplaats") -> Iterator[Listing]:
    offset, total = 0, 1
    while offset < total and offset < cfg.get("max_results", 500):
        q = {"query": query_text(search), "l1CategoryId": CARS_CATEGORY, "limit": PAGE, "offset": offset}
        r = http.get(f"{cfg['domain'].rstrip('/')}/lrp/api/search?{urlencode(q)}")
        if r is None:
            break
        data = r.json()
        total = int(data.get("totalResultCount") or 0)
        yield from parse(data, search, cfg, source)
        offset += PAGE
        print(f"  {min(offset, total)}/{total} risultati letti", flush=True)


def fetch_2dehands(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    return fetch(search, cfg, http, "2dehands")
