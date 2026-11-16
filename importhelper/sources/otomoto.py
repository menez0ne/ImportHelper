"""Otomoto (PL, prezzi in PLN).

Le pagine dei risultati (otomoto.pl/osobowe/<marca>/<modello>) contengono in
__NEXT_DATA__ la cache GraphQL con la ricerca ("advertSearch").
"""
from __future__ import annotations

import json
from typing import Iterator, Optional

from ..http import Http
from ..models import Listing
from .common import is_model, next_data, source_param, to_int


def _search_data(html: str) -> Optional[dict]:
    state = next_data(html).get("props", {}).get("pageProps", {}).get("urqlState") or {}
    for entry in state.values():
        raw = entry.get("data") or ""
        if "advertSearch" in raw:
            return json.loads(raw).get("advertSearch")
    return None


def parse(html: str, search: dict) -> tuple[list[Listing], int]:
    """Ritorna (annunci, numero di pagine)."""
    data = _search_data(html)
    if not data:
        return [], 0
    out = []
    for edge in data.get("edges") or []:
        n = edge.get("node") or {}
        p = {x.get("key"): x for x in n.get("parameters") or []}
        val = lambda k: (p.get(k) or {}).get("value")
        disp = lambda k: (p.get(k) or {}).get("displayValue") or ""
        title = n.get("title") or ""
        if not is_model(f"{disp('make') or title} {disp('model') or title}", search):
            continue
        amount = ((n.get("price") or {}).get("amount") or {})
        thumb = (n.get("thumbnail") or {}).get("x2") or (n.get("thumbnail") or {}).get("x1")
        hp = to_int(val("engine_power"))      # cavalli (KM)
        loc = n.get("location") or {}
        version = " ".join(x for x in (disp("model"), disp("version"), n.get("shortDescription") or "") if x)
        out.append(Listing(
            source="otomoto",
            source_id=str(n.get("id")),
            search=search["name"],
            url=n.get("url") or "",
            title=title,
            make=disp("make"),
            model=disp("model"),
            version=version,
            year=to_int(val("year")),
            km=to_int(val("mileage")),
            price=float(amount["value"]) if amount.get("value") else None,
            currency=amount.get("currencyCode") or "PLN",
            country="PL",
            city=((loc.get("city") or {}).get("name") or ""),
            seller="",
            seller_type="dealer" if (n.get("seller") or {}).get("__typename") == "ProfessionalSeller" else "private",
            condition="new" if val("new_used") == "new" else "used",
            fuel=disp("fuel_type"),
            power_kw=round(hp / 1.35962) if hp else None,
            photos=[thumb.replace(";s=640x480", ";s=1280x960")] if thumb else [],
        ))
    page = data.get("pageInfo") or {}
    size = page.get("pageSize") or 32
    pages = -(-int(data.get("totalCount") or 0) // size)
    return out, pages


def fetch(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    make = source_param(search, "otomoto", "make", search["make"])
    model = source_param(search, "otomoto", "model", search["model"])
    base = f"https://www.otomoto.pl/osobowe/{make}/{model}"
    if search.get("year_min"):
        base += f"/od-{search['year_min']}"
    page, pages = 1, 1
    while page <= min(pages, cfg.get("max_pages", 10)):
        r = http.get(base + (f"?page={page}" if page > 1 else ""))
        if r is None:
            break
        listings, pages = parse(r.text, search)
        yield from listings
        print(f"  pagina {page}/{max(pages, 1)}", flush=True)
        if not listings:
            break
        page += 1
