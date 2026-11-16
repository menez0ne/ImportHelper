"""Icona "ImportHelper": accende il server se serve e apre SEMPRE il sito nel browser.

pythonw -m importhelper.open

Con pythonw non c'è una console: eventuali errori finiscono in data/open.log
e, se il sito non si può aprire, compare una finestra di avviso.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

URL = "http://localhost:8765/"
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "open.log"


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def server_up(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/status", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def start_server() -> None:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(pythonw), "-m", "importhelper.server"], cwd=str(ROOT),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def open_in_browser(target: str) -> bool:
    """Apre l'indirizzo con il browser predefinito. Su Windows os.startfile è il modo più affidabile."""
    if os.name == "nt":
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        except OSError as e:
            log(f"os.startfile non riuscito: {e}")
    try:
        if webbrowser.open(target):
            return True
    except Exception as e:  # noqa: BLE001
        log(f"webbrowser non riuscito: {e}")
    if os.name == "nt":  # ultimo tentativo: lo stesso comando del Prompt dei comandi
        try:
            subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=0x08000000)
            return True
        except OSError as e:
            log(f"start non riuscito: {e}")
    return False


def alert(text: str) -> None:
    log(text)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "ImportHelper", 0x30)
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    try:
        if not server_up():
            start_server()
            for _ in range(120):  # fino a 60 secondi
                time.sleep(0.5)
                if server_up():
                    break
        if server_up():
            if not open_in_browser(URL):
                alert(f"Il sito è acceso ma non riesco ad aprire il browser.\nAprilo tu e vai su {URL}")
            return
        static = ROOT / "site" / "index.html"
        if static.exists() and open_in_browser(static.as_uri()):
            log("server non partito: aperta la versione statica del sito")
            return
        alert("Il sito di ImportHelper non è partito.\nRifai doppio clic su installa.bat e, se non basta, "
              "manda il file data\\server.log a chi ti ha passato ImportHelper.")
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        alert("Errore all'avvio di ImportHelper: dettagli in data\\open.log")


if __name__ == "__main__":
    main()
