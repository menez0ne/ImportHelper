"""Blocket (SE, SEK) e Finn (NO, NOK): stessa piattaforma "mobility".

La pagina /mobility/search/car?q=... contiene i risultati in un blocco
data-react-query-state (JSON in base64), chiave "docs".
"""
from __future__ import annotations

import base64
import json
import re
from typing import Iterator
from urllib.parse import urlencode

from ..http import Http
from ..models import Listing
from .common import is_model, query_text, to_int

STATE_RE = re.compile(r"data-react-query-state>([^<]+)<")
MILE_KM = 10   # "mil" scandinavo = 10 km


def _search(html: str) -> dict:
    m = STATE_RE.search(html)
    if not m:
        return {}
    state = json.loads(base64.b64decode(m.group(1)))
    for q in state.get("queries") or []:
        data = (q.get("state") or {}).get("data")
        if isinstance(data, dict) and "docs" in data:
            return data
    return {}


def parse(html: str, search: dict, source: str, country: str) -> tuple[list[Listing], int]:
    data = _search(html)
    out = []
    for d in data.get("docs") or []:
        title = d.get("heading") or ""
        if not is_model(f"{d.get('make') or title} {d.get('model') or title}", search):
            continue
        km = to_int(d.get("mileage"))
        if km is not None and d.get("mileage_unit") == "SCANDINAVIAN_MILE":
            km *= MILE_KM
        price = d.get("price") or {}
        dealer = d.get("dealer_segment") not in (None, "Privat")
        out.append(Listing(
            source=source,
            source_id=str(d.get("id")),
            search=search["name"],
            url=d.get("canonical_url") or "",
            title=f"{d.get('make', '')} {d.get('model', '')}".strip() or title,
            make=d.get("make") or "",
            model=d.get("model") or "",
            version=d.get("model_specification") or title,
            year=to_int(d.get("year")),
            km=km,
            price=float(price["amount"]) if price.get("amount") else None,
            currency=price.get("currency_code") or ("SEK" if country == "SE" else "NOK"),
            country=country,
            city=d.get("location") or "",
            seller=d.get("organisation_name") or "",
            seller_type="dealer" if dealer else "private",
            condition="used",
            fuel=d.get("fuel") or "",
            photos=d.get("image_urls") or ([d["image"]["url"]] if d.get("image") else []),
        ))
    paging = (data.get("metadata") or {}).get("paging") or {}
    return out, int(paging.get("last") or 1)


def _fetch(search: dict, cfg: dict, http: Http, source: str, country: str) -> Iterator[Listing]:
    page, pages = 1, 1
    while page <= min(pages, cfg.get("max_pages", 5)):
        q = {"q": query_text(search)}
        if page > 1:
            q["page"] = page
        r = http.get(f"{cfg['domain'].rstrip('/')}/mobility/search/car?{urlencode(q)}")
        if r is None:
            break
        listings, pages = parse(r.text, search, source, country)
        yield from listings
        print(f"  pagina {page}/{pages}", flush=True)
        page += 1


def fetch_blocket(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    return _fetch(search, cfg, http, "blocket", "SE")


def fetch_finn(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    return _fetch(search, cfg, http, "finn", "NO")
