"""Icona "ImportHelper": accende il server se serve e apre il sito nel browser.

pythonw -m importhelper.open
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

URL = "http://localhost:8765/"
ROOT = Path(__file__).resolve().parent.parent


def server_up(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(URL + "api/status", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def start_server() -> None:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen([str(pythonw), "-m", "importhelper.server"], cwd=str(ROOT), creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    if not server_up():
        start_server()
        for _ in range(40):
            time.sleep(0.5)
            if server_up():
                break
    if server_up():
        webbrowser.open(URL)
    else:  # il server non parte: apriamo almeno la versione statica
        webbrowser.open((ROOT / "site" / "index.html").as_uri())


if __name__ == "__main__":
    main()
