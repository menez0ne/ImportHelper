"""Willhaben (AT): ricerca auto per parola chiave, dati in __NEXT_DATA__ (searchResult)."""
from __future__ import annotations

from typing import Iterator
from urllib.parse import urlencode

from ..http import Http
from ..models import Listing
from .common import country_code, is_model, next_data, query_text, to_int

BASE = "https://www.willhaben.at/iad/gebrauchtwagen/auto/gebrauchtwagenboerse"
IMG = "https://cache.willhaben.at/mmo/"
ROWS = 90


def parse(html: str, search: dict) -> tuple[list[Listing], int]:
    sr = next_data(html).get("props", {}).get("pageProps", {}).get("searchResult") or {}
    out = []
    for ad in (sr.get("advertSummaryList") or {}).get("advertSummary") or []:
        a = {x["name"]: (x.get("values") or [""])[0] for x in (ad.get("attributes") or {}).get("attribute") or []}
        title = a.get("HEADING") or ad.get("description") or ""
        if not is_model(title, search):
            continue
        images = [IMG + p for p in (a.get("ALL_IMAGE_URLS") or "").split(";") if p]
        cond = (a.get("CONDITION_RESOLVED") or "").lower()
        out.append(Listing(
            source="willhaben",
            source_id=str(ad.get("id")),
            search=search["name"],
            url="https://www.willhaben.at/iad/" + (a.get("SEO_URL") or f"object?adId={ad.get('id')}"),
            title=title,
            make=search["make"].title(),
            model=search["model"].upper() if len(search["model"]) <= 4 else search["model"].replace("-", " ").title(),
            version=title,
            year=to_int(a.get("YEAR_MODEL")),
            km=to_int(a.get("MILEAGE")),
            price=float(a["PRICE"]) if a.get("PRICE") else None,
            currency="EUR",
            country=country_code(a.get("COUNTRY"), "AT"),
            city=a.get("LOCATION") or a.get("STATE") or "",
            seller="Privato" if a.get("ISPRIVATE") == "1" else "",
            seller_type="private" if a.get("ISPRIVATE") == "1" else "dealer",
            condition="new" if "neu" in cond and "unfall" not in cond else "used",
            fuel=a.get("ENGINE/FUEL_RESOLVED") or "",
            power_kw=to_int(a.get("ENGINE/EFFECT")),
            photos=images,
        ))
    found, rows = int(sr.get("rowsFound") or 0), int(sr.get("rowsRequested") or ROWS)
    return out, -(-found // rows)


def fetch(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    page, pages = 1, 1
    while page <= min(pages, cfg.get("max_pages", 5)):
        q = {"keyword": query_text(search), "rows": ROWS, "page": page}
        r = http.get(f"{BASE}?{urlencode(q)}")
        if r is None:
            break
        listings, pages = parse(r.text, search)
        yield from listings
        print(f"  pagina {page}/{max(pages, 1)}", flush=True)
        page += 1
