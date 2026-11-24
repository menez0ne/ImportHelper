"""Descrizione del venditore e traduzione in italiano.

La descrizione non c'è nelle pagine dei risultati: la leggiamo dalla pagina
dell'annuncio la prima volta che se ne apre la scheda, e la salviamo nel
database (tabella "descriptions") insieme alla traduzione. Le volte dopo la
scheda la mostra subito, senza richieste ai siti.

Traduzione: DeepL se in data/deepl.txt c'è una chiave "DeepL API Free"
(gratis fino a 500.000 caratteri al mese), altrimenti Google Traduttore
(gratuito, senza chiave). Tutti e due riconoscono da soli la lingua del testo.
Se il traduttore non risponde si mostra il testo originale e la traduzione si
riprova alla prossima apertura. Se Google risponde "troppe richieste" (429)
non gli chiediamo niente per 30 minuti, per non allungare il blocco.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from .db import now
from .http import HEADERS, Http

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
DEEPL_KEY_FILE = Path(__file__).resolve().parent.parent / "data" / "deepl.txt"
GOOGLE_PAUSE = 30 * 60    # secondi senza chiedere a Google dopo un "troppe richieste"
MAX_CHARS = 8000          # le descrizioni più lunghe vengono tagliate
CHUNK = 1800              # caratteri per richiesta di traduzione

LANGUAGES = {
    "it": "italiano", "de": "tedesco", "nl": "olandese", "fr": "francese", "en": "inglese",
    "pl": "polacco", "sv": "svedese", "no": "norvegese", "nb": "norvegese", "nn": "norvegese",
    "da": "danese", "es": "spagnolo", "pt": "portoghese", "cs": "ceco", "fi": "finlandese",
    "hu": "ungherese", "ro": "rumeno", "sk": "slovacco", "sl": "sloveno", "hr": "croato",
    "lt": "lituano", "lv": "lettone", "et": "estone", "el": "greco", "bg": "bulgaro",
    "lb": "lussemburghese", "ca": "catalano",
}

# titoli della sezione "Descrizione" nelle lingue dei siti
HEADINGS = ("Beskrivelse|Beskrivning|Beschreibung|Fahrzeugbeschreibung|Beschrijving|Omschrijving|Description|"
            "Descrizione|Descripción|Opis|Kuvaus|Popis")

_google_paused_until = 0.0


class TranslatorBusy(Exception):
    """Il traduttore ha risposto "troppe richieste": si riprova più tardi."""


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS descriptions (
    key TEXT PRIMARY KEY,           -- fonte:id dell'annuncio (uguale per tutte le ricerche)
    url TEXT,
    text TEXT,                      -- testo originale ("" = l'annuncio non ha descrizione)
    lang TEXT,                      -- lingua riconosciuta, es. "de"
    translation TEXT,               -- traduzione in italiano (NULL se non serve o non riuscita)
    fetched_at TEXT,
    translator TEXT                 -- chi ha tradotto: "DeepL" o "Google Traduttore"
);
"""


# ---------- estrazione dalla pagina dell'annuncio ----------

def clean(text: str) -> str:
    """HTML -> testo semplice, con gli a capo al posto di <br>, <p>, <li>."""
    t = str(text or "")
    t = re.sub(r"(?i)<br\s*/?>|</?p(?:\s[^>]*)?>|</div>|</li>|</h\d>", "\n", t)
    t = re.sub(r"(?i)<li[^>]*>", "• ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t).replace("\xa0", " ").replace("\r", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS].rsplit(" ", 1)[0] + " […]"
    return t


def _walk(obj, out: list[str]) -> None:
    """Raccoglie i testi delle chiavi "description" (e simili) in un JSON qualsiasi."""
    if isinstance(obj, dict):
        # willhaben: {"name": "DESCRIPTION", "values": ["..."]}
        if str(obj.get("name", "")).upper() in ("DESCRIPTION", "BODY_DYN") and isinstance(obj.get("values"), list):
            out.extend(v for v in obj["values"] if isinstance(v, str))
        for k, v in obj.items():
            if isinstance(v, str) and "description" in k.lower() and "meta" not in k.lower():
                out.append(v)
            else:
                _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)


def _json_blocks(page: str):
    for m in re.finditer(r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            yield json.loads(m.group(1))
        except ValueError:
            continue


def extract(page: str) -> str:
    """Il testo più lungo tra i campi "description" della pagina; "" se non c'è."""
    found: list[str] = []
    for data in _json_blocks(page):            # __NEXT_DATA__, JSON-LD e simili
        _walk(data, found)
    # altri dati incorporati (es. window.__CONFIG__ di Marktplaats)
    for m in re.finditer(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', page):
        try:
            found.append(json.loads('"' + m.group(1) + '"'))
        except ValueError:
            continue
    # HTML: un blocco con "description" nell'id, nella classe o in data-testid (Marktplaats, Otomoto)
    for m in re.finditer(r'<(div|section|p)[^>]*(?:id|class|data-testid)="[^"]*description[^"]*"[^>]*>(.*?)</\1>',
                         page, re.S | re.I):
        found.append(_strip_blocks(m.group(2)))
    # HTML: il testo dopo un titolo "Beskrivelse", "Beschreibung"... (Finn, Blocket)
    for m in re.finditer(rf'<h[1-6][^>]*>\s*(?:{HEADINGS})\s*</h[1-6]>(.*?)(?:</section>|<h[1-3][\s>])',
                         page, re.S | re.I):
        found.append(_strip_blocks(m.group(1)))
    # la descrizione breve per i motori di ricerca: solo se non c'è altro
    meta = re.search(r'<meta[^>]+(?:property|name)="(?:og:)?description"[^>]+content="([^"]*)"', page, re.I)
    meta_text = clean(meta.group(1)) if meta else ""
    texts = [clean(t) for t in found]
    texts = [t for t in texts if len(t) >= 20 and t != meta_text and not t.startswith(("http://", "https://"))]
    return max(texts, key=len) if texts else meta_text


def _strip_blocks(fragment: str) -> str:
    """Toglie titoli, script e stili da un pezzo di HTML: resta solo il testo dell'annuncio."""
    return re.sub(r"(?is)<(h[1-6]|script|style|button)[^>]*>.*?</\1>", "", fragment)


# ---------- traduzione ----------

def _chunks(text: str) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > CHUNK:                     # riga lunghissima: la spezziamo tra le parole
            if cur:
                parts.append(cur)
                cur = ""
            cut = line.rfind(" ", 0, CHUNK)
            cut = cut if cut > 0 else CHUNK
            parts.append(line[:cut])
            line = line[cut:].lstrip()
        if cur and len(cur) + len(line) + 1 > CHUNK:
            parts.append(cur)
            cur = ""
        cur = cur + "\n" + line if cur else line
    if cur:
        parts.append(cur)
    return [p for p in parts if p.strip()]


def deepl_key() -> str:
    """La chiave DeepL, se l'utente l'ha messa in data/deepl.txt (o nella variabile DEEPL_API_KEY)."""
    import os
    key = os.environ.get("DEEPL_API_KEY", "")
    if not key and DEEPL_KEY_FILE.exists():
        key = DEEPL_KEY_FILE.read_text(encoding="utf-8-sig").strip()
    return key


def translate_deepl(text: str, key: str, session: Optional[requests.Session] = None) -> tuple[str, Optional[str]]:
    s = session or requests.Session()
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"   # le chiavi gratuite finiscono con :fx
    r = s.post(f"https://{host}/v2/translate", json={"text": [text], "target_lang": "IT"},
               headers={"Authorization": f"DeepL-Auth-Key {key}"}, timeout=30)
    if r.status_code in (429, 456):          # troppe richieste / caratteri del mese finiti
        raise TranslatorBusy(f"DeepL: risposta {r.status_code}")
    if r.status_code != 200:
        raise requests.HTTPError(f"risposta {r.status_code} da DeepL")
    t = r.json()["translations"][0]
    lang = (t.get("detected_source_language") or "").lower()
    return (lang, None) if lang == "it" else (lang, t["text"].strip())


def translate_google(text: str, session: Optional[requests.Session] = None) -> tuple[str, Optional[str]]:
    global _google_paused_until
    if time.time() < _google_paused_until:
        raise TranslatorBusy("Google Traduttore in pausa dopo un 'troppe richieste'")
    s = session or requests.Session()
    lang, out = "", []
    for chunk in _chunks(text):
        r = s.post(TRANSLATE_URL, params={"client": "gtx", "sl": "auto", "tl": "it", "dt": "t"},
                   data={"q": chunk}, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20,
                   allow_redirects=False)       # troppe richieste: Google rimanda a una pagina di verifica
        if r.status_code in (302, 429):
            _google_paused_until = time.time() + GOOGLE_PAUSE
            raise TranslatorBusy(f"Google Traduttore: risposta {r.status_code} (troppe richieste), pausa di 30 minuti")
        if r.status_code != 200:
            raise requests.HTTPError(f"risposta {r.status_code} dal traduttore")
        data = r.json()
        lang = lang or (data[2] if len(data) > 2 and isinstance(data[2], str) else "")
        if lang == "it":
            return "it", None
        out.append("".join(seg[0] for seg in (data[0] or []) if seg and seg[0]))
    return lang or "", "\n".join(out).strip()


def translate(text: str, session: Optional[requests.Session] = None) -> tuple[str, Optional[str], str]:
    """Ritorna (lingua riconosciuta, traduzione, traduttore). Traduzione None se il testo è già in italiano.

    Prima DeepL (se c'è la chiave), poi Google. Se nessuno risponde rilancia l'ultimo errore.
    """
    key = deepl_key()
    if key:
        try:
            return (*translate_deepl(text, key, session), "DeepL")
        except (TranslatorBusy, requests.RequestException, ValueError, KeyError, IndexError) as e:
            print(f"  DeepL non disponibile ({e}), provo Google", flush=True)
    return (*translate_google(text, session), "Google Traduttore")


# ---------- cache ----------

def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _row(conn, key: str) -> Optional[dict]:
    r = conn.execute("SELECT * FROM descriptions WHERE key = ?", (key,)).fetchone()
    return dict(r) if r else None


def _result(row: dict, error: str = "") -> dict:
    lang = row.get("lang") or ""
    return {
        "text": row.get("text") or "",
        "lang": lang,
        "lang_name": LANGUAGES.get(lang, lang),
        "translation": row.get("translation"),
        "translated": bool(row.get("translation")),
        "translator": row.get("translator") or "Google Traduttore",   # le traduzioni salvate prima erano tutte di Google
        "needs_translation": bool(row.get("text")) and lang != "it",
        "error": error,
    }


def get(conn, listing: dict, http: Optional[Http] = None, session: Optional[requests.Session] = None) -> dict:
    """Descrizione (e traduzione) di un annuncio: dal database, altrimenti dal sito."""
    conn.executescript(SCHEMA)
    if "translator" not in {r[1] for r in conn.execute("PRAGMA table_info(descriptions)")}:
        # database creato prima di questa colonna: le traduzioni già salvate vengono da DeepL se c'è la chiave
        conn.execute("ALTER TABLE descriptions ADD COLUMN translator TEXT")
        conn.execute("UPDATE descriptions SET translator = ? WHERE translation IS NOT NULL",
                     ("DeepL" if deepl_key() else "Google Traduttore",))
        conn.commit()
    key = f"{listing['source']}:{listing['source_id']}"
    with _lock(key):
        row = _row(conn, key)
        if row is None:
            http = http or Http(delay=0)
            r = http.get(listing["url"])
            if r is None:
                return {"text": "", "lang": "", "lang_name": "", "translation": None, "translated": False,
                        "needs_translation": False, "error": "fetch"}
            row = {"key": key, "url": listing["url"], "text": extract(r.text), "lang": None,
                   "translation": None, "fetched_at": now()}
            conn.execute("INSERT OR REPLACE INTO descriptions (key, url, text, lang, translation, fetched_at) "
                         "VALUES (:key, :url, :text, :lang, :translation, :fetched_at)", row)
            conn.commit()
        if row["text"] and (row.get("lang") is None or (row["lang"] != "it" and not row.get("translation"))):
            try:
                row["lang"], row["translation"], row["translator"] = translate(row["text"], session)
            except TranslatorBusy as e:
                print(f"  traduzione rimandata per {key}: {e}", flush=True)
                return _result(row, "translate_busy")
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
                print(f"  traduzione non riuscita per {key}: {e}", flush=True)
                return _result(row, "translate")
            conn.execute("UPDATE descriptions SET lang = ?, translation = ?, translator = ? WHERE key = ?",
                         (row["lang"], row["translation"], row["translator"], key))
            conn.commit()
        return _result(row)
