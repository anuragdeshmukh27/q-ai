"""Summary of a recording: time, tests, stats, repairs, escalations, errors.   python scripts/rec_report.py <name>"""
import collections
import json
import sys
from pathlib import Path

d = Path(__file__).resolve().parents[1] / "recordings" / sys.argv[1]
meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
ev = [json.loads(x) for x in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
print({k: meta[k] for k in ("ok", "seconds", "events", "llm_calls", "models") if k in meta}, meta.get("stats"))
tests = [e for e in ev if e["type"] in ("test_result", "merge_result")]
print("last test:", {k: tests[-1].get(k) for k in ("summary", "passed", "total", "ok")} if tests else None)
c = collections.Counter(e["type"] for e in ev)
print({k: c[k] for k in ("error", "escalation", "contract_repair", "review_result", "bug_filed", "agent_thought")})
for e in ev:
    if e["type"] in ("contract_repair", "escalation", "bug_filed") or (e["type"] == "review_result" and e["verdict"] != "PASS"):
        print(" ", e["type"], e.get("agent", ""), e.get("task", "")[:60].replace("\n", " "), e.get("path", ""), e.get("reason", ""), e.get("verdict", ""), str(e.get("items", ""))[:120])
print("errors:", collections.Counter(str(e.get("message"))[:90] for e in ev if e["type"] == "error"))
