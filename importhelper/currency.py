"""Conversione in euro con i cambi ufficiali giornalieri della BCE."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

import requests

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


class Converter:
    def __init__(self, cache_file: str | Path = "data/fx.json"):
        self.cache_file = Path(cache_file)
        self.rates: dict[str, float] = {"EUR": 1.0}
        self._load()

    def _load(self) -> None:
        today = date.today().isoformat()
        if self.cache_file.exists():
            cached = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if cached.get("fetched") == today:
                self.rates.update(cached["rates"])
                return
        try:
            xml = requests.get(ECB_URL, timeout=20).text
            rates = {c: float(r) for c, r in re.findall(r"currency='(\w{3})' rate='([\d.]+)'", xml)}
            if rates:
                self.rates.update(rates)
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(
                    json.dumps({"fetched": today, "rates": rates}, indent=2), encoding="utf-8"
                )
                return
        except requests.RequestException as e:
            print(f"[cambi] BCE non raggiungibile: {e}")
        # Se la BCE non risponde, usa l'ultimo cambio salvato.
        if self.cache_file.exists():
            self.rates.update(json.loads(self.cache_file.read_text(encoding="utf-8"))["rates"])

    def to_eur(self, amount: Optional[float], currency: str) -> Optional[float]:
        if amount is None:
            return None
        rate = self.rates.get((currency or "EUR").upper())
        if rate is None:
            return None
        return round(amount / rate, 2)
