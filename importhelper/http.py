"""Client HTTP con pause tra le richieste e ripetizione in caso di errore."""
from __future__ import annotations

import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


class Http:
    def __init__(self, delay: float = 3.0):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last = 0.0

    def get(self, url: str, **kw) -> requests.Response | None:
        for attempt in range(3):
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                r = self.session.get(url, timeout=30, **kw)
            except requests.RequestException as e:
                print(f"  errore di rete ({e}), riprovo...")
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503):
                time.sleep(10 * (attempt + 1))
                continue
            print(f"  risposta {r.status_code} da {url[:100]}")
            return None
        return None
