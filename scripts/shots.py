"""Screenshot built apps: start each project's own server, fill it with sample data through its real API, and take a headless-Chrome screenshot.

    backend\.venv\Scripts\python.exe scripts\shots.py workspace\<project> [workspace\<other> ...] [--out workspace\_shots] [--open]

--open also shoots the detail view of the first item of a feed layout (the open post with its comments). Used for the chip regression run and the judge run:
the screenshots show what a judge sees, with data in the app.
"""
import argparse
import json
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

from preview import CHROME, seed_value  # noqa: E402
from app.schemas import ArchitectOutput  # noqa: E402


def call(base: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def seed(base: str, d: ArchitectOutput) -> None:
    if d.resources:
        parent = next(r for r in d.resources if not r.parent)
        child = next((r for r in d.resources if r.parent), None)
        for i in range(4):
            _, row = call(base, "POST", f"/api/{parent.name}", {f.name: seed_value(f, i) for f in parent.fields})
            for a in parent.actions:
                for _ in range((i * 3 + 2) % 7):
                    call(base, "POST", f"/api/{parent.name}/{row['id']}/{a.name}")
            for k in range(3 - i % 3 if child else 0):
                call(base, "POST", f"/api/{parent.name}/{row['id']}/{child.name}", {f.name: seed_value(f, k + i) for f in child.fields})
        return
    post = next((e for e in d.endpoints if e.method == "POST" and "{" not in e.path and e.request_fields), None)
    if post is not None:
        for i in range(4):
            fields = {f.name: seed_value(f, i) for f in post.request_fields}
            if {"a", "b", "operation"} <= set(fields):  # a calculator
                fields.update(a=12 + i, b=3 + i, operation=["add", "subtract", "multiply", "divide"][i % 4])
            call(base, "POST", post.path, fields)


def shoot(project: Path, out: Path, opened: bool) -> str:
    d = ArchitectOutput.model_validate_json((project / ".q" / "design.json").read_text(encoding="utf-8"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**__import__("os").environ, "APP_DB": str(project / "shots.db")}
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
        look = d.look.model_dump() if d.look else {}
        name = project.name + ("-open" if opened else "")
        target = out / f"{name}.png"
        out.mkdir(parents=True, exist_ok=True)
        hook = ""
        url = base + "/"
        if opened:
            url += "#open"
            # the page cannot be changed from outside: open the first post by a tiny page that loads the app and clicks the comments button
            wrapper = project / "static" / "_shot.html"
            html = (project / "static" / "index.html").read_text(encoding="utf-8").replace("</body>", "<script>setTimeout(() => { const b = document.querySelector('.btn-comments'); if (b) b.click(); }, 600);</script></body>")
            wrapper.write_text(html, encoding="utf-8")
            url = base + "/static/_shot.html"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1100,1500", "--virtual-time-budget=6000", f"--screenshot={target}", url],
                       capture_output=True, timeout=120)
        if opened:
            (project / "static" / "_shot.html").unlink(missing_ok=True)
        return f"{project.name}: theme={look.get('theme')} layout={look.get('layout')} -> {target}"
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        (project / "shots.db").unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="+")
    ap.add_argument("--out", default=str(ROOT / "workspace" / "_shots"))
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()
    for p in args.projects:
        print(shoot(Path(p).resolve(), Path(args.out), args.open), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
