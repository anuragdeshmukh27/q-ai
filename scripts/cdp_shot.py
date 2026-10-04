r"""Screenshot the Q web app after clicking things, with headless Chrome driven over the DevTools protocol (no extra packages: `websockets` ships with uvicorn[standard]).

    backend\.venv\Scripts\python.exe scripts\cdp_shot.py http://localhost:5173 --click "Leaderboard" --click "Team vs single agent" --out workspace\_shots\lb.png

--click TEXT clicks the first button (or tab) whose visible text contains TEXT, in order. --wait SECONDS pauses after each click (default 1.2).
--eval JS prints the result of a JavaScript expression after the clicks (for assertions in a script).
"""
import argparse
import base64
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from preview import CHROME  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--click", action="append", default=[])
    ap.add_argument("--wait", type=float, default=1.2)
    ap.add_argument("--out", default=str(ROOT / "workspace" / "_shots" / "cdp.png"))
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--eval", dest="expr")
    args = ap.parse_args()
    w, h = (int(x) for x in args.size.split("x"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    profile = tempfile.mkdtemp(prefix="q-cdp-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                               f"--window-size={w},{h}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        for _ in range(60):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read())
                target = next(t for t in tabs if t.get("type") == "page")
                break
            except (OSError, StopIteration):
                time.sleep(0.5)
        if target is None:
            print("Chrome did not start")
            return 1
        with connect(target["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024) as ws:
            n = 0

            def call(method: str, **params):
                nonlocal n
                n += 1
                ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == n:
                        return msg.get("result", {})

            def js(expr: str):
                r = call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                return r.get("result", {}).get("value")

            call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
            call("Page.navigate", url=args.url)
            time.sleep(3)
            for text in args.click:
                ok = js("((t) => { const els = [...document.querySelectorAll('button,[role=tab]')].filter(e => e.innerText && e.innerText.trim().includes(t)); "
                        "if (!els.length) return false; els[0].click(); return true })(" + json.dumps(text) + ")")
                print(f"click {text!r}: {'ok' if ok else 'NOT FOUND'}")
                time.sleep(args.wait)
            if args.expr:
                print(json.dumps(js(args.expr), ensure_ascii=False))
            shot = call("Page.captureScreenshot", format="png")
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(shot["data"]))
            print(f"saved {out}")
        return 0
    finally:
        chrome.terminate()
        try:
            chrome.wait(10)
        except subprocess.TimeoutExpired:
            chrome.kill()


if __name__ == "__main__":
    raise SystemExit(main())
