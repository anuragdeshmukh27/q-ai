r"""Check an Ask-employee result in a real browser: does the todo app show a progress bar that matches its data?

    backend\.venv\Scripts\python.exe scripts\ask_check.py workspace\<todo project> [--out workspace\_shots]

Starts the project's own server, seeds four todos (shots.seed: two of them done), loads the page in headless Chrome, and reads the final DOM:
the page must have a progress bar (a <progress> or an element whose id or class says "progress") that shows 2 of 4 done (value/max, a width of 50% or the text
"2" and "4" / "50%"). Saves a screenshot. Exit code 0 only when the bar is there and right.
"""
import argparse
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from preview import CHROME  # noqa: E402
from shots import seed  # noqa: E402
from app.schemas import ArchitectOutput  # noqa: E402


def check_dom(dom: str, done: int = 2, total: int = 4) -> tuple[bool, str]:
    """(is there a real progress bar at the top of the page showing done of total, what was found).
    A bar is a <progress> with value and max, or an element whose class or id says "progress" with a filled part whose width is the share done; text alone is not a bar.
    "At the top" means before the first card (<section>) of the page."""
    share = 100 * done / total
    found, where = "", -1
    m = re.search(r"<progress\b[^>]*>", dom, re.I)
    if m:
        tag = m.group(0)
        v, mx = re.search(r'value="?([\d.]+)', tag), re.search(r'max="?([\d.]+)', tag)
        if v and mx and (float(v.group(1)) == done and float(mx.group(1)) == total or float(mx.group(1)) == 100 and abs(float(v.group(1)) - share) < 1):
            found, where = f"<progress {done}/{total}>", m.start()
        else:
            return False, f"a <progress> exists but shows {tag}"
    else:
        for el in re.finditer(r'<div\b[^>]*(?:class|id)="[^"]*(?:fill|bar|meter)[^"]*"[^>]*style="[^"]*width:\s*([\d.]+)%[^"]*"|<div\b[^>]*style="[^"]*width:\s*([\d.]+)%[^"]*"[^>]*(?:class|id)="[^"]*(?:fill|bar|meter)[^"]*"', dom, re.I):
            width = float(el.group(1) or el.group(2))
            if abs(width - share) < 1 and re.search(r"progress", dom[max(0, el.start() - 400):el.start()], re.I):
                found, where = f"a progress bar filled to {width:g}%", el.start()
                break
    if not found:
        return False, "no progress bar showing 2 of 4 (text alone is not a bar)"
    if not re.search(rf"\b{done} of {total} done\b", dom):
        return False, f"{found}, but its label does not read '{done} of {total} done'"
    first_card = dom.lower().find("<section")
    if first_card != -1 and where > first_card:
        return False, f"{found}, but it is below the first card, not at the top"
    return True, f"{found}, at the top"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--out", default=str(ROOT / "workspace" / "_shots"))
    args = ap.parse_args()
    project = Path(args.project).resolve()
    d = ArchitectOutput.model_validate_json((project / ".q" / "design.json").read_text(encoding="utf-8"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**__import__("os").environ, "APP_DB": str(project / "askcheck.db")}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--log-level", "warning"], cwd=project, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        seed(base, d)
        flags = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1100,1300", "--virtual-time-budget=6000"]
        dom = subprocess.run([*flags, "--dump-dom", base + "/"], capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace").stdout
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"{project.name}-ask.png"
        subprocess.run([*flags, f"--screenshot={target}", base + "/"], capture_output=True, timeout=120)
        ok, found = check_dom(dom)
        print(f"{'OK' if ok else 'NOT OK'}: {found} | screenshot {target}")
        return 0 if ok else 1
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        (project / "askcheck.db").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
