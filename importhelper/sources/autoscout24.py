"""AutoScout24: copre DE, AT, BE, ES, FR, IT, LU, NL.

Le pagine dei risultati contengono un blocco JSON (__NEXT_DATA__) con tutti
i dati degli annunci: lo leggiamo invece di analizzare l'HTML.
"""
from __future__ import annotations

import json
import re
from typing import Iterator, Optional
from urllib.parse import urlencode

from ..http import Http
from ..models import Listing

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
CURRENCY_SYMBOLS = {"€": "EUR", "CHF": "CHF", "£": "GBP", "zł": "PLN", "Kč": "CZK", "kr": "SEK"}


def _int(value) -> Optional[int]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def _year(first_reg: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", first_reg or "")
    return int(m.group(0)) if m else None


def _currency(formatted: str) -> str:
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in (formatted or ""):
            return code
    return "EUR"


def _big_photo(url: str) -> str:
    # le miniature finiscono con /250x188.webp: chiediamo una versione grande
    return re.sub(r"/\d+x\d+\.(webp|jpg|jpeg)$", r"/1280x960.\1", url)


def _power_kw(item: dict, vehicle: dict, tracking: dict) -> Optional[int]:
    if tracking.get("power") or vehicle.get("powerInKw"):
        return _int(tracking.get("power") or vehicle.get("powerInKw"))
    # oggi la potenza sta in vehicleDetails ("750 kW (1.020 CV)") o in motorTypeName ("E 750 kW")
    texts = [d.get("data", "") for d in item.get("vehicleDetails") or [] if isinstance(d, dict)]
    texts.append(vehicle.get("motorTypeName") or "")
    for t in texts:
        m = re.search(r"(\d[\d.]*)\s*kW", t or "")
        if m:
            return _int(m.group(1))
    return None


def parse_page(html: str, search_name: str, domain: str) -> tuple[list[Listing], int]:
    """Ritorna (annunci, numero di pagine totali)."""
    m = NEXT_DATA_RE.search(html)
    if not m:
        return [], 0
    data = json.loads(m.group(1))
    props = data.get("props", {}).get("pageProps", {})
    raw_listings = props.get("listings") or []
    pages = props.get("numberOfPages") or 1

    out = []
    for item in raw_listings:
        vehicle = item.get("vehicle", {}) or {}
        tracking = item.get("tracking", {}) or {}
        location = item.get("location", {}) or {}
        seller = item.get("seller", {}) or {}
        price_info = item.get("price", {}) or {}

        first_reg = tracking.get("firstRegistration") or ""
        if first_reg in ("new", "neu"):
            first_reg = ""
        first_reg = first_reg.replace("-", "/")

        url = item.get("url", "")
        if url.startswith("/"):
            url = domain.rstrip("/") + url

        make = vehicle.get("make", "")
        model = vehicle.get("model", "")
        version = vehicle.get("modelVersionInput", "") or vehicle.get("variant", "")
        offer = (vehicle.get("offerType") or "").upper()

        out.append(Listing(
            source="autoscout24",
            source_id=str(item.get("id")),
            search=search_name,
            url=url,
            title=" ".join(x for x in (make, model, version) if x),
            make=make,
            model=model,
            version=version,
            year=_year(first_reg) or _int(vehicle.get("modelYear")),
            first_registration=first_reg,
            km=_int(tracking.get("mileage") or vehicle.get("mileageInKm")),
            price=_int(price_info.get("priceRaw")) or _int(tracking.get("price"))
            or _int(price_info.get("priceFormatted")),
            currency=_currency(price_info.get("priceFormatted", "")),
            country=(location.get("countryCode") or "").upper(),
            city=location.get("city", "") or "",
            seller=seller.get("companyName") or seller.get("contactName") or "",
            seller_type="dealer" if (seller.get("type") or "").lower() == "dealer" else "private",
            condition="new" if offer == "N" else "used",
            fuel=vehicle.get("fuel", "") or "",
            power_kw=_power_kw(item, vehicle, tracking),
            photos=[_big_photo(p) for p in (item.get("images") or []) if isinstance(p, str)],
        ))
    return out, int(pages)


def search_urls(search: dict, cfg: dict, page: int) -> list[str]:
    """Due ricerche: auto usate dall'anno minimo in poi, e auto nuove."""
    base = f"{cfg['domain'].rstrip('/')}/lst/{search['make']}/{search['model']}"
    common = {
        "atype": "C",
        "cy": ",".join(cfg["countries"]),
        "sort": "age",
        "desc": "1",
        "page": str(page),
    }
    used = {**common, "ustate": "U,D", "fregfrom": str(search.get("year_min") or "")}
    new = {**common, "ustate": "N"}
    return [f"{base}?{urlencode(used)}", f"{base}?{urlencode(new)}"]


def fetch(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    seen: set[str] = set()
    for kind in (0, 1):  # 0 = usate, 1 = nuove
        page, pages = 1, 1
        while page <= min(pages, cfg.get("max_pages", 20)):
            url = search_urls(search, cfg, page)[kind]
            r = http.get(url)
            if r is None:
                break
            listings, pages = parse_page(r.text, search["name"], cfg["domain"])
            if not listings:
                break
            for l in listings:
                if l.source_id not in seen:
                    seen.add(l.source_id)
                    yield l
            label = "usate" if kind == 0 else "nuove"
            total = min(pages, cfg.get("max_pages", 20))
            print(f"  {label} pagina {page}/{total} ({len(seen)} annunci finora)", flush=True)
            page += 1
