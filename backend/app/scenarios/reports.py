"""The report of an attempt: the scores, the evidence rows, the fairness checks and the focus for the next attempt, as a dict (JSON) and as markdown.

`build_report` is pure: it takes the rubric, the facts, the scored findings and whatever the wording step produced, and checks every row once more before it is shown
(the quote must be in the entry it cites). The attempt history lives next to the projects, `<workspace>/.q-attempts/<scenario>.json`, because every attempt is a project
of its own and the numbers have to survive the project folders.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .rubric import Rubric
from .scoring import CriterionResult, Facts, SOURCES, clock, event_text
from .wording import Dropped, PointWording, quote_matches

REPORT_VERSION = 1
QUOTE_CHARS = 200
_lock = threading.Lock()


class History:
    """The finished attempts of one scenario, oldest first: [{attempt, total, scores, project, finished_at, elapsed}]."""

    def __init__(self, base: Path, scenario_id: str):
        self.path = Path(base) / ".q-attempts" / f"{scenario_id}.json"

    def attempts(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [a for a in data if isinstance(a, dict) and isinstance(a.get("attempt"), int)] if isinstance(data, list) else []

    def next_number(self) -> int:
        """The number of the attempt that starts now: one more than the finished ones."""
        return max((a["attempt"] for a in self.attempts()), default=0) + 1

    def add(self, record: dict) -> list[dict]:
        """Record a finished attempt (a second record for the same number replaces the first) and return the whole history."""
        with _lock:
            items = [a for a in self.attempts() if a["attempt"] != record["attempt"]] + [record]
            items.sort(key=lambda a: a["attempt"])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, indent=1), encoding="utf-8", newline="\n")
            os.replace(tmp, self.path)
            return items


def _clip(text: str, n: int = QUOTE_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def build_report(*, scenario, rubric: Rubric, attempt: int, project: str, facts: Facts, results: list[CriterionResult], names: dict[str, str],
                 wording: dict[str, PointWording] | None = None, dropped: list[Dropped] | None = None, wording_source: str = "template", wording_reason: str = "",
                 history: list[dict] | None = None, finished_at: float | None = None) -> dict:
    """The report of one attempt. `wording` is what survived the verifier (finding id -> point); every other point reads with the template wording."""
    wording = wording or {}
    dropped = list(dropped or [])
    events = {e["id"]: e for e in facts.log}
    rows: list[dict] = []
    criteria: list[dict] = []
    for c, res in zip(rubric.criteria, results):
        ids: list[str] = []
        for f in res.findings:
            w = wording.get(f.id)
            event_id = w.event if w else f.events[0]
            quote = w.quote if w else _clip(event_text(events[event_id]))
            if not quote_matches(quote, events[event_id]):  # a last check of every row that is shown
                dropped.append(Dropped(f.id, quote[:200], f"the quote is not in {event_id}"))
                w, event_id = None, f.events[0]
                quote = _clip(event_text(events[event_id]))
            if not quote_matches(quote, events[event_id]):
                dropped.append(Dropped(f.id, f.text, "no quotable moment"))
                continue
            row = {"id": f"R{len(rows) + 1:02d}", "criterion": c.id, "rule": f.rule, "kind": f.kind, "event": event_id, "events": f.events, "t": events[event_id]["t"],
                   "source": SOURCES.get(events[event_id]["kind"], "Session"), "quote": quote, "note": w.note if w else f.text,
                   "advice": (w.advice if w and w.advice else f.advice) if f.kind == "gap" else "", "verified": True, "worded_by": "model" if w else "template"}
            rows.append(row)
            ids.append(row["id"])
        criteria.append({"id": c.id, "name": c.name, "judge": c.judge, "judge_name": names.get(c.judge, c.judge), "score": res.score, "max": rubric.points_per_criterion,
                         "descriptor": c.descriptors[str(res.score)], "keep": c.keep, "rows": ids})
    total = sum(c["score"] for c in criteria) * rubric.weight
    gaps = [r for c in sorted(criteria, key=lambda c: c["score"]) for r in rows if r["criterion"] == c["id"] and r["kind"] == "gap" and r["advice"]]
    focus: list[str] = []
    for r in gaps:
        if r["advice"] not in focus:
            focus.append(r["advice"])
    accepted = facts.accepted
    rerun = facts.rerun
    prior = [a for a in (history or []) if a["attempt"] != attempt]
    record = {"attempt": attempt, "total": total, "scores": {c["id"]: c["score"] for c in criteria}, "project": project,
              "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(finished_at or time.time())), "elapsed": accepted["t"] if accepted else facts.log[-1]["t"]}
    return {
        "version": REPORT_VERSION, "scenario": scenario.id, "title": scenario.title, "project": project, "attempt": attempt,
        "total": total, "max": rubric.max_total, "elapsed": record["elapsed"], "minutes": scenario.minutes, "finished_at": record["finished_at"],
        "rubric": {"id": rubric.id, "version": rubric.version}, "criteria": criteria, "rows": rows, "events": {i: events[i] for i in {e for r in rows for e in r["events"]}},
        "fairness": {"points": len(rows), "quoted": sum(1 for r in rows if r["quote"]), "matched": sum(1 for r in rows if r["verified"]), "dropped": [d.as_dict() for d in dropped],
                     "tests_rerun": {"ok": bool(rerun and rerun.get("ok")), "passed": rerun.get("passed", 0), "total": rerun.get("passed", 0) + rerun.get("failed", 0)} if rerun else None,
                     "rubric": f"v{rubric.version}", "wording": {"source": wording_source, "reason": wording_reason, "model_points": sum(1 for r in rows if r["worded_by"] == "model")}},
        "focus": focus[:3] or [f"A full-marks run. Try to beat your time of {clock(record['elapsed'])}, or keep these habits in the next scenario."],
        "attempts": [*prior, record], "files": {"md": f".q/reports/attempt-{attempt}.md", "json": f".q/reports/attempt-{attempt}.json"},
    }


def render_markdown(report: dict, names: dict[str, str]) -> str:
    lines = [f"# Debrief: {report['title']}", "", f"**Attempt {report['attempt']}: {report['total']}/{report['max']}** · {clock(report['elapsed'])} on the clock · rubric {report['rubric']['id']}", ""]
    lines += ["| Criterion | Judge | Score |", "| --- | --- | --- |", *[f"| {c['name']} | {c['judge_name']} | {c['score']}/{c['max']} |" for c in report["criteria"]], ""]
    for c in report["criteria"]:
        lines += [f"## {c['name']} {c['score']}/{c['max']}", "", f"_{c['descriptor']}_", ""]
        for r in (x for x in report["rows"] if x["criterion"] == c["id"]):
            lines += [f"- **{r['kind'].upper()}** {clock(r['t'])} · {r['source']} · {r['event']}: “{r['quote']}”", f"  {r['note']}" + (f" Next attempt: {r['advice']}" if r["advice"] else "")]
        lines.append("")
    f = report["fairness"]
    rerun = f["tests_rerun"]
    lines += ["## Fairness checks", "", f"- Points that quote a moment: {f['quoted']}/{f['points']}", f"- Quotes matched to the session log: {f['matched']}/{f['points']}",
              f"- Claims dropped: {len(f['dropped'])}", *[f"  - dropped: “{d['text']}” ({d['reason']})" for d in f["dropped"]],
              f"- Tests re-run, not guessed: {(str(rerun['passed']) + '/' + str(rerun['total'])) if rerun else 'could not be re-run'}",
              f"- Same rubric for every attempt: {f['rubric']}", f"- Wording: {f['wording']['source']}" + (f" ({f['wording']['reason']})" if f["wording"]["reason"] else ""), ""]
    lines += ["## Focus for the next attempt", "", *[f"{i}. {x}" for i, x in enumerate(report["focus"], 1)], ""]
    lines += ["## Attempts", "", *[f"- Attempt {a['attempt']}: {a['total']}/{report['max']}" for a in report["attempts"]], ""]
    return "\n".join(lines)


def write_report(root: Path, report: dict, names: dict[str, str]) -> None:
    folder = Path(root) / ".q" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    n = report["attempt"]
    (folder / f"attempt-{n}.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    (folder / f"attempt-{n}.md").write_text(render_markdown(report, names), encoding="utf-8", newline="\n")
