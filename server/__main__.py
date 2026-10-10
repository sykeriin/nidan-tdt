"""One command to run the digital twin: API + the React drawing-sheet UI on one port.

    python -m server              # build web/ if there is no build yet, serve on http://127.0.0.1:8000, open it
    python -m server --build      # rebuild web/ first (after frontend changes)
    python -m server --no-browser --port 8000 --host 0.0.0.0

Needs Node.js only to build; once web/dist exists it runs offline with Python alone.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def build_web() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("web/dist is missing and npm is not installed: install Node.js, or copy a built web/dist here.")
    if not (WEB / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=WEB, check=True)
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server", description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--build", action="store_true", help="rebuild the web app first")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.build or not (WEB / "dist" / "index.html").is_file():
        build_web()
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host}:{a.port}/"
    if not a.no_browser:
        threading.Timer(2.0, webbrowser.open, args=(url,)).start()
    print(f"Digital twin: {url}   (API docs: {url}docs)")
    uvicorn.run("server.app:app", host=a.host, port=a.port)


if __name__ == "__main__":
    main()
