"""Raccolta in background (usata dall'attività pianificata di Windows con pythonw.exe).

Nessuna finestra: tutto l'output va in data/ultimo_giro.log. Un file di blocco
evita due raccolte contemporanee (es. all'accesso e allo scatto delle 3 ore).
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "ultimo_giro.log"
LOCK = ROOT / "data" / "raccolta.lock"


def _ask_server() -> bool:
    """Se il server del sito è acceso, gli chiediamo di aggiornare tutte le ricerche (nella sua coda)."""
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:8765/api/refresh-all", data=b"{}", method="POST",
                                 headers={"X-ImportHelper": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def run() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if _ask_server():
        LOG.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: raccolta affidata al server del sito "
                       "(avanzamento in data/server.log)\n", encoding="utf-8")
        return
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 2 * 3600:
        return  # un'altra raccolta è in corso
    LOCK.write_text(str(os.getpid()))
    try:
        with LOG.open("w", encoding="utf-8") as log:
            sys.stdout = sys.stderr = log
            print(f"Inizio: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            sys.argv = [sys.argv[0]]
            try:
                from .__main__ import main
                main()
            except Exception:
                traceback.print_exc()
            print(f"Fine: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    run()
