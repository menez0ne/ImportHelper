"""Inventario ufficiale Tesla (auto usate e nuove) per ogni Paese europeo.

Usa la stessa API JSON che chiama la pagina tesla.com/<paese>/inventory.
Tesla a volte blocca le richieste automatiche (errore 403): in quel caso
la fonte viene saltata senza fermare il resto.
"""
from __future__ import annotations

import json
from typing import Iterator, Optional
from urllib.parse import quote

from ..http import Http
from ..models import Listing

API = "https://www.tesla.com/inventory/api/v4/inventory-results?query="

LOCALES = {
    "DE": "de_DE", "AT": "de_AT", "CH": "de_CH", "FR": "fr_FR", "BE": "nl_BE",
    "NL": "nl_NL", "LU": "fr_LU", "IT": "it_IT", "ES": "es_ES", "PT": "pt_PT",
    "IE": "en_IE", "GB": "en_GB", "SE": "sv_SE", "NO": "no_NO", "DK": "da_DK",
    "FI": "fi_FI", "PL": "pl_PL", "CZ": "cs_CZ",
}
MILES_TO_KM = 1.609344


def build_query(model: str, market: str, condition: str, offset: int) -> str:
    locale = LOCALES[market]
    q = {
        "query": {
            "model": model,
            "condition": condition,
            "options": {},
            "arrangeby": "Price",
            "order": "asc",
            "market": market,
            "language": locale.split("_")[0],
            "super_region": "europe",
            "lng": "", "lat": "", "zip": "", "range": 0, "region": "",
        },
        "offset": offset,
        "count": 50,
        "outsideOffset": 0,
        "outsideSearch": False,
    }
    return API + quote(json.dumps(q, separators=(",", ":")))


def _photos(item: dict) -> list[str]:
    photos = []
    for p in item.get("VehiclePhotos") or []:
        url = p.get("imageUrl") if isinstance(p, dict) else p
        if isinstance(url, str):
            photos.append(url)
    return photos


def _km(item: dict) -> Optional[int]:
    odo = item.get("Odometer")
    if odo is None:
        return None
    odo = float(odo)
    if str(item.get("OdometerType", "")).upper().startswith("MI"):
        odo *= MILES_TO_KM
    return int(round(odo))


def parse_results(data: dict, search_name: str, model: str, market: str, condition: str) -> list[Listing]:
    results = data.get("results")
    if isinstance(results, dict):  # a volte: {"exact": [...], "approximate": [...]}
        results = results.get("exact", [])
    out = []
    for item in results or []:
        vin = item.get("VIN")
        if not vin:
            continue
        trim = item.get("TrimName") or ""
        locale = LOCALES[market]
        url = f"https://www.tesla.com/{locale}/{model}/order/{vin}"
        if condition == "used":
            url += "?titleStatus=used"
        price = item.get("InventoryPrice") or item.get("Price") or item.get("PurchasePrice")
        out.append(Listing(
            source="tesla",
            source_id=vin,
            search=search_name,
            url=url,
            title=f"Tesla {trim}".strip() if "tesla" not in trim.lower() else trim,
            make="Tesla",
            model={"ms": "Model S", "mx": "Model X"}.get(model, model),
            version=trim,
            year=int(item["Year"]) if item.get("Year") else None,
            km=_km(item),
            price=float(price) if price else None,
            currency=item.get("CurrencyCode") or "EUR",
            country=(item.get("CountryCode") or market).upper(),
            city=item.get("City") or item.get("MetroName") or "",
            seller="Tesla",
            seller_type="dealer",
            condition=condition,
            fuel="Elettrica",
            photos=_photos(item),
        ))
    return out


def fetch(search: dict, cfg: dict, http: Http) -> Iterator[Listing]:
    model = search["tesla_model"]
    for market in cfg["markets"]:
        for condition in cfg.get("conditions", ["used"]):
            offset = 0
            while True:
                r = http.get(build_query(model, market, condition, offset),
                             headers={"Accept": "application/json"})
                if r is None:
                    break
                try:
                    data = r.json()
                except ValueError:
                    print(f"  Tesla {market}: risposta non valida (probabile blocco anti-bot)")
                    break
                listings = parse_results(data, search["name"], model, market, condition)
                yield from listings
                total = int(data.get("total_matches_found") or 0)
                offset += 50
                if not listings or offset >= total:
                    break
