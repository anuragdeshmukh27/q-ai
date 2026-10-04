"""Preview a generated page without building anything: the page and script Q would generate for a design, served with an in-memory API and sample data,
then a headless-Chrome screenshot. Used to look at the themes and layouts (no model, no GPU).

    backend\.venv\Scripts\python.exe scripts\preview.py "Build Instagram" --out shots\insta.png [--open] [--theme food] [--layout cards]
    backend\.venv\Scripts\python.exe scripts\preview.py workspace\<project> --goal "Build an expense tracker" --out shots\expense.png
    backend\.venv\Scripts\python.exe scripts\preview.py --serve workspace\<project>        (keep the server running to look at it in a browser)

A platform name (see app/platforms.py) is turned into its spec and design by the same rules the engine uses; a project folder uses its `.q/design.json`.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.look import choose_look  # noqa: E402
from app.platforms import match_platform  # noqa: E402
from app.relations import synthesize_design  # noqa: E402
from app.schemas import ArchitectOutput, SpecOutput, normalize_spec, required_text  # noqa: E402
from app.uistub import page_stub, script_stub  # noqa: E402

SKELETON = ROOT / "backend" / "app" / "presets" / "fastapi_vanilla" / "skeleton" / "static"
CHROME = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), "chrome")
WORDS = {"title": ["Best pizza in town", "Why I stopped using spreadsheets", "Weekend hike photos", "Ask me anything"], "author": ["meera", "arjun", "kavya", "rohan"],
         "name": ["Aarav Sharma", "Meera Iyer", "Rohan Das", "Kavya Nair"], "content": ["Honestly the best thing I tried this week. Highly recommend giving it a go.", "Short and sweet: it works."],
         "description": ["A small note about this one.", "Handy and well made."], "comment": ["Loved it, would come back.", "Decent, but a bit slow."], "text": ["Just shipped something new!", "Anyone else up this early?"],
         "caption": ["Golden hour at the pier", "Monday mood", "Fresh out of the oven"]}


def seed_value(f, i: int):
    if f.options:
        return f.options[i % len(f.options)]
    if f.type == "boolean":
        return i % 2 == 0
    if f.type in ("number", "integer"):
        return 3 + i % 3 if re.search(r"rating|stars?", f.name) else (round(14.5 + 22 * i, 2) if f.type == "number" else 4 + 7 * i)
    if "date" in f.name or f.name.endswith("_on") or "check_" in f.name:
        return f"2026-10-{10 + i:02d}"
    if "email" in f.name:
        return f"user{i}@example.com"
    if "phone" in f.name:
        return f"+91 98765 4{i:04d}"
    pool = WORDS.get(f.name) or WORDS.get(next((k for k in WORDS if k in f.name), ""), [])
    return pool[i % len(pool)] if pool else f"{f.name.replace('_', ' ').capitalize()} {i + 1}"


class Api:
    """An in-memory stand-in for the generated backend: enough to show every layout with data."""

    def __init__(self, design: ArchitectOutput):
        self.d, self.tables, self.next = design, {}, {}
        self.resources = {r.name: r for r in design.resources}
        self.single = None if design.resources else next((e for e in design.endpoints if e.method == "GET" and "{" not in e.path and any(f.type == "array" for f in e.response_fields)), None)

    def add(self, table: str, fields, body: dict, extra=None):
        for f in fields:
            if f.name in body and isinstance(body[f.name], str) and required_text(f) and not body[f.name].strip():
                return 400, {"detail": f.name.replace("_", " ").capitalize() + " is required"}
        self.next[table] = self.next.get(table, 0) + 1
        ago = time.gmtime(time.time() - 60 * (7 * self.next[table] ** 2))
        row = {"id": self.next[table], **(extra or {}), **{k: v for k, v in body.items()}, "created_at": time.strftime("%Y-%m-%d %H:%M:%S", ago)}
        if table in self.resources:
            row.update({c: 0 for c in self.resources[table].counters})
        self.tables.setdefault(table, []).append(row)
        return 201, row

    def seed(self):
        if self.resources:
            for p in [r for r in self.resources.values() if not r.parent]:
                for i in range(4):
                    _, row = self.add(p.name, p.fields, {f.name: seed_value(f, i) for f in p.fields})
                    for c in p.counters:
                        row[c] = (i * 5 + 3) % 11
                    for ch in [r for r in self.resources.values() if r.parent == p.name]:
                        for k in range(3 - i % 3):
                            _, crow = self.add(ch.name, ch.fields, {f.name: seed_value(f, k + i) for f in ch.fields}, {ch.fk: row["id"]})
                            for c in ch.counters:
                                crow[c] = (k * 2 + i) % 5
            return
        post = next((e for e in self.d.endpoints if e.method == "POST" and "{" not in e.path and e.request_fields), None)
        if post is None:
            return
        for i in range(5):
            self.add(self.single.path, post.request_fields, {f.name: seed_value(f, i) for f in post.request_fields})

    def handle(self, method: str, path: str, query: dict, body: dict):
        parts = [p for p in path.split("/") if p][1:]  # drop "api"
        if self.resources:
            return self.handle_rel(method, parts, query, body)
        base = self.single.path
        tail = [p for p in path.split("/") if p][len(base.strip("/").split("/")):]
        rows = self.tables.setdefault(base, [])
        key = next(f.name for f in self.single.response_fields if f.type == "array")
        post = next(e for e in self.d.endpoints if e.method == "POST" and "{" not in e.path and e.request_fields)
        if not tail:
            if method == "GET":
                return 200, {key: list(reversed(rows))}
            if method == "DELETE":
                rows.clear()
                return 200, {"cleared": True}
            status, row = self.add(base, post.request_fields, body)
            if status == 201 and {"a", "b", "operation", "result"} <= {f.name for f in post.response_fields} | set(body):
                a, b, op = body["a"], body["b"], str(body["operation"])
                row["result"] = {"add": a + b, "subtract": a - b, "multiply": a * b, "divide": a / b if b else 0}.get(op, a + b)
            return status, row
        item = next((r for r in rows if str(r["id"]) == tail[0]), None)
        if item is None:
            return 404, {"detail": "Not found"}
        if method == "DELETE":
            rows.remove(item)
            return 200, {"deleted": True}
        item.update(body)
        return 200, item

    def handle_rel(self, method, parts, query, body):
        name = parts[0]
        r = self.resources.get(name)
        if r is None:
            return 404, {"detail": "Not found"}
        rows = self.tables.setdefault(name, [])
        if len(parts) == 1:  # /api/posts
            if method == "GET":
                items = sorted(rows, key=lambda x: x["id"], reverse=True)
                if query.get("sort") == "top" and r.counters:
                    items = sorted(items, key=lambda x: x[r.counters[0]] - (x[r.counters[1]] if len(r.counters) > 1 else 0), reverse=True)
                return 200, {"items": items}
            return self.add(name, r.fields, body)
        if parts[1].isdigit() and len(parts) == 3 and parts[2] not in {a.name for a in r.actions}:  # /api/posts/1/comments
            child = self.resources.get(parts[2])
            parent_rows = self.tables.get(name, [])
            if child is None or not any(str(x["id"]) == parts[1] for x in parent_rows):
                return 404, {"detail": "Not found"}
            if method == "GET":
                items = [x for x in self.tables.get(child.name, []) if str(x[child.fk]) == parts[1]]
                return 200, {"items": sorted(items, key=lambda x: x["id"], reverse=True)}
            return self.add(child.name, child.fields, body, {child.fk: int(parts[1])})
        item = next((x for x in rows if str(x["id"]) == parts[1]), None)
        if item is None:
            return 404, {"detail": "Not found"}
        if len(parts) == 3:  # an action
            action = next(a for a in r.actions if a.name == parts[2])
            item[action.field] = item[action.field] + 1 if action.kind == "increment" else 1 - int(item[action.field])
            return 200, item
        if method == "DELETE":
            rows.remove(item)
            return 200, {"deleted": True}
        item.update(body)
        return 200, item


def make_handler(api: Api, web: Path, hash_script: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status, data, ctype="application/json"):
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def route(self, method):
            from urllib.parse import parse_qsl, urlparse

            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                status, data = api.handle(method, u.path, dict(parse_qsl(u.query)), body)
                return self.send(status, data)
            name = "index.html" if u.path == "/" else u.path.removeprefix("/static/")
            f = web / name
            if not f.is_file():
                return self.send(404, b"not found", "text/plain")
            raw = f.read_bytes()
            if name == "index.html":
                raw = raw.replace(b"</body>", hash_script.encode() + b"</body>")
            ctype = {"html": "text/html", "css": "text/css", "js": "text/javascript"}.get(f.suffix[1:], "application/octet-stream")
            self.send(200, raw, ctype + "; charset=utf-8")

        do_GET = lambda self: self.route("GET")  # noqa: E731
        do_POST = lambda self: self.route("POST")  # noqa: E731
        do_PUT = lambda self: self.route("PUT")  # noqa: E731
        do_DELETE = lambda self: self.route("DELETE")  # noqa: E731

    return H


def load(target: str, goal: str):
    path = Path(target)
    if path.is_dir():
        design = ArchitectOutput.model_validate_json((path / ".q" / "design.json").read_text(encoding="utf-8"))
        spec = None
        md = path / ".q" / "spec.md"
        if md.exists():
            lines = md.read_text(encoding="utf-8").splitlines()
            left = re.search(r"Not in this version: ([^\n]*?)\.?$", "\n".join(lines), re.M)
            spec = SpecOutput(title=lines[0].lstrip("# ").strip(), summary=lines[2].strip() if len(lines) > 2 else "",
                              not_included=[x.strip() for x in left.group(1).split(",")] if left else [])
        return design, spec, goal or path.name
    spec = match_platform(target)
    if spec is None:
        raise SystemExit(f"{target!r} is neither a project folder nor a known platform name")
    return synthesize_design(normalize_spec(spec, target)), spec, target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--goal", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--theme")
    ap.add_argument("--layout")
    ap.add_argument("--open", action="store_true", help="feed layouts: open the first post (the detail view)")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--size", default="1100,1500")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    design, spec, goal = load(args.target, args.goal)
    design.look = choose_look(goal, spec, design)
    if args.theme:
        design.look.theme = args.theme
    if args.layout:
        design.look.layout = args.layout
    web = Path(tempfile.mkdtemp(prefix="q_preview_"))
    title = spec.title if spec else ""
    (web / "index.html").write_text(page_stub(design, title), encoding="utf-8")
    (web / "app.js").write_text(script_stub(design, title), encoding="utf-8")
    (web / "style.css").write_text("", encoding="utf-8")
    for n in ("ui-kit.css", "ui-kit.js"):
        shutil.copy(SKELETON / n, web / n)
    api = Api(design)
    api.seed()
    hook = "<script>if (location.hash === '#open') setTimeout(() => { const b = document.querySelector('.btn-comments'); if (b) b.click(); }, 400);</script>" if args.open else ""
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(api, web, hook))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/" + ("#open" if args.open else "")
    print(f"theme={design.look.theme} layout={design.look.layout} icon={design.look.icon} subtitle={design.look.subtitle!r} left_out={design.look.not_included}")
    if args.serve:
        print(url)
        while True:
            time.sleep(1)
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        w, h = args.size.split(",")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}", "--virtual-time-budget=5000",
                        f"--screenshot={out}", url], capture_output=True, timeout=90)
        print("screenshot:", out, out.exists())
    server.shutdown()
    shutil.rmtree(web, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
