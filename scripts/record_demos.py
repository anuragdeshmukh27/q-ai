"""Record the demo set with the final engine, check each recording and keep only good ones.

    backend\.venv\Scripts\python.exe scripts\record_demos.py [name ...] [--tries 3]

Every recording is built through the real server (scripts/record.py). A recording is kept only if the build passed AND it shows what its card
promises (QA bug fix, approvals, an Ask-employee change, metrics, a running app); otherwise it is deleted and the run is repeated.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from goals import CHIPS, FLAGSHIP  # noqa: E402

GOAL = {label: goal for label, goal in CHIPS}
ASK_TEXT = "Add a progress bar at the top showing how many todos are done"  # the exact line of the optional live step in docs/DEMO_SCRIPT.md

DEMOS = {
    "calculator-fault": dict(goal=GOAL["calculator with history"], title="Calculator with history", app="Calculator", feature="QA bug fix",
                             args=["--inject-fault"]),
    "todo-approvals": dict(goal=GOAL["todo app"], title="Todo app with priorities", app="Todo app", feature="Approvals",
                           args=["--mode", "assisted"]),
    "ask-employee": dict(goal=GOAL["todo app"], title="Todo app, then a request", app="Todo app", feature="Ask employee",
                         args=["--ask", "frontend=" + ASK_TEXT]),
    "notes-search": dict(goal=GOAL["notes app"], title="Notes with search", app="Notes app", feature="Clean fast run", args=[]),
    "contact-book": dict(goal=GOAL["contact book"], title="Contact book", app="Contact book", feature="Search and groups", args=[]),
    "inventory": dict(goal=GOAL["inventory list"], title="Inventory list", app="Inventory", feature="Stock status", args=[]),
    "reddit-replica": dict(goal=GOAL["reddit replica"], title="Reddit replica", app="Forum", feature="Posts, comments and votes", args=[]),
    "instagram": dict(goal="Build Instagram", title="Instagram (small version)", app="Instagram", feature="A famous app by name", args=[]),
    "flagship": dict(goal=FLAGSHIP, title="College tech fest manager: 4 modules", app="Tech fest manager", feature="4 linked modules", args=[]),
}


def events(name: str) -> list[dict]:
    return [json.loads(l) for l in (ROOT / "recordings" / name / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def judge(name: str) -> list[str]:
    """What is wrong with this recording (empty list = keep it)."""
    d = ROOT / "recordings" / name
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["no recording was saved"]
    ev = events(name)
    types = [e["type"] for e in ev]
    bad = []
    if not meta.get("ok"):
        bad.append("the build did not pass")
    if not meta.get("snapshot"):
        bad.append("no snapshot")
    for need in ("metrics", "app_running", "spec_ready", "architecture_ready", "merge_result", "test_result"):
        if need not in types:
            bad.append(f"no {need} event")
    repaired = sum(1 for e in ev if e["type"] == "contract_repair" and e.get("ok"))
    if name == "flagship":  # eight engineer tasks on a 7B: a step the contract repair finished is part of the story (and says so on the card), a person stepping in is not
        escalations = sum(1 for e in ev if e["type"] == "escalation")
        if escalations > repaired:
            bad.append(f"{escalations} escalations but only {repaired} contract repairs (a person had to step in)")
        errors = [e for e in ev if e["type"] == "error" and not str(e.get("message", "")).startswith("model returned invalid output")]
    else:
        if any(e["type"] == "escalation" for e in ev):
            bad.append("an escalation (a person had to step in)")
        errors = [e for e in ev if e["type"] == "error"]
    if errors:
        bad.append("an error event: " + str(errors[0].get("message", ""))[:80])
    last_state = {}
    for e in ev:
        if e["type"] == "agent_state":
            last_state[e["agent"]] = e["state"]
    stuck = [a for a, st in last_state.items() if st in ("waiting_human", "error", "loading_model")]
    if stuck:
        bad.append("still waiting or in error at the end: " + ", ".join(stuck))
    if name == "calculator-fault" and not ({"fault_injected", "bug_filed", "bug_fixed"} <= set(types)):
        bad.append("the injected fault was not caught and fixed")
    if name == "notes-search" and not any(e["type"] == "file_changed" and e["path"] == "static/index.html" and 'id="search"' in e.get("diff", "") for e in ev):
        bad.append("the page has no search box")
    if name == "todo-approvals":
        asked = [e for e in ev if e["type"] == "approval_needed"]
        if len(asked) < 5:
            bad.append(f"only {len(asked)} approvals")
    if name == "ask-employee":
        if not any(e["type"] == "message_sent" and e.get("from") == "human" and e.get("to") == "frontend" and ASK_TEXT in e.get("text", "") for e in ev):
            bad.append("the Ask-employee message is missing")
        if types.count("project_done") < 2 or "project_resumed" not in types:
            bad.append("the request was not run after the build")
        else:
            after = ev[types.index("project_resumed"):]
            edits = [e for e in after if e["type"] == "file_changed" and e.get("agent") == "frontend" and e["path"].startswith("static/")]
            html = " ".join(e.get("diff", "") for e in edits if e["path"] == "static/index.html").lower()
            js = " ".join(e.get("diff", "") for e in edits if e["path"] == "static/app.js").lower()
            if not edits:
                bad.append("Meera did not change the page")
            elif "progress" not in html:
                bad.append("the page has no progress bar in index.html")
            elif "progress" not in js:
                bad.append("app.js never fills the progress bar (a bar that never moves)")
    if name == "reddit-replica":
        spec = next((e for e in ev if e["type"] == "spec_ready"), {})
        if not any(e["type"] == "look_chosen" and e.get("layout") in ("feed", "shell") for e in ev):
            bad.append("not a feed or shell layout")
        if "comments" not in spec.get("text", "").lower():
            bad.append("the spec has no comments")
    if name == "flagship":
        design = {}
        try:
            design = json.loads(next(e for e in ev if e["type"] == "file_changed" and e["path"] == ".q/design.json").get("diff", "{}"))
        except (StopIteration, ValueError):
            pass
        stats = meta.get("stats", {})
        if stats.get("modules") != 4 or stats.get("tables") != 4:
            bad.append(f"not four modules and tables: {stats}")
        if not any(e["type"] == "look_chosen" and e.get("layout") == "shell" for e in ev):
            bad.append("not the shell layout")
        del design
    if name == "instagram":
        spec = next((e for e in ev if e["type"] == "spec_ready"), {})
        if not spec.get("not_included"):
            bad.append("no 'Not in this version' list")
    return bad


def one(name: str, tries: int) -> bool:
    cfg = DEMOS[name]
    for attempt in range(1, tries + 1):
        shutil.rmtree(ROOT / "recordings" / name, ignore_errors=True)
        log = ROOT / "workspace" / "_logs" / f"record-{name}-{attempt}.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        print(f"== {name}: attempt {attempt}/{tries}", flush=True)
        t0 = time.time()
        with open(log, "w", encoding="utf-8") as f:
            cmd = [sys.executable, str(ROOT / "scripts" / "record.py"), cfg["goal"], "--name", name, "--title", cfg["title"], "--app", cfg["app"],
                   "--feature", cfg["feature"], *cfg["args"]]
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
        bad = judge(name)
        print(f"   {time.time() - t0:.0f}s -> {'KEEP' if not bad else 'DISCARD: ' + '; '.join(bad)}", flush=True)
        if not bad:
            return True
        kept = ROOT / "workspace" / "_logs" / "discarded" / f"{name}-{attempt}"  # events only, to see why it was judged bad
        shutil.rmtree(kept, ignore_errors=True)
        kept.mkdir(parents=True, exist_ok=True)
        for f in ("events.jsonl", "meta.json"):
            if (ROOT / "recordings" / name / f).is_file():
                shutil.copy(ROOT / "recordings" / name / f, kept / f)
        shutil.rmtree(ROOT / "recordings" / name, ignore_errors=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--tries", type=int, default=3)
    a = ap.parse_args()
    names = a.names or list(DEMOS)
    results = {n: one(n, a.tries) for n in names}
    print(json.dumps(results), flush=True)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
