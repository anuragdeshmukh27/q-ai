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
from .scoring import CriterionResult, Facts, clock, event_text, note_matches, source_label
from .wording import Dropped, quote_matches

REPORT_VERSION = 1
QUOTE_CHARS = 200
_lock = threading.Lock()


class History:
    """The finished attempts of one scenario, oldest first: [{attempt, total, scores, project, finished_at, elapsed}]."""

    def __init__(self, base: Path, scenario_id: str, kind: str = "learner"):
        # an autoplay demo keeps its own file, so it never takes a number from the learner's attempts nor shows in their list
        self.path = Path(base) / ".q-attempts" / f"{scenario_id}{'-demo' if kind == 'demo' else ''}.json"

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


def criterion_summary(res: CriterionResult) -> str:
    """What the score of a criterion is made of, from its rules: what held and what did not (never from the score level alone)."""
    held = [f.label for f in res.findings if f.kind == "strength"]
    missed = [f.label for f in res.findings if f.kind == "gap"]
    if not missed:
        return "Everything held: " + ", ".join(held) + "."
    if not held:
        return "Nothing held. Missed: " + ", ".join(missed) + "."
    return "Held: " + ", ".join(held) + ". Missed: " + ", ".join(missed) + "."


def build_report(*, scenario, rubric: Rubric, attempt: int, project: str, facts: Facts, results: list[CriterionResult], names: dict[str, str],
                 history: list[dict] | None = None, finished_at: float | None = None, kind: str = "learner", variant: str = "") -> dict:
    """The report of one attempt. Every sentence of a point is its rule's; a point is shown only when its quote is in the entry it cites and every time, file and test count
    of its sentence is that entry's (a point that fails is dropped and recorded under `fairness.dropped`). The coach paragraph and the judges' lines are added by `attach_voices`."""
    dropped: list[Dropped] = []
    events = {e["id"]: e for e in facts.log}
    rows: list[dict] = []
    criteria: list[dict] = []
    for c, res in zip(rubric.criteria, results):
        ids: list[str] = []
        for f in res.findings:
            event_id = f.events[0]
            quote = _clip(event_text(events[event_id]))
            problem = None if quote_matches(quote, events[event_id]) else f"the quote is not in {event_id}"
            problem = problem or note_matches(f.text, events[event_id])
            if problem:
                dropped.append(Dropped(f.id, f.text, problem))
                continue
            row = {"id": f"R{len(rows) + 1:02d}", "criterion": c.id, "rule": f.rule, "kind": f.kind, "event": event_id, "events": f.events, "t": events[event_id]["t"],
                   "source": source_label(events[event_id]), "quote": quote, "note": f.text, "advice": f.advice if f.kind == "gap" else "", "verified": True, "worded_by": "rule"}
            rows.append(row)
            ids.append(row["id"])
        criteria.append({"id": c.id, "name": c.name, "judge": c.judge, "judge_name": names.get(c.judge, c.judge), "score": res.score, "max": rubric.points_per_criterion,
                         "descriptor": c.descriptors[str(res.score)], "summary": criterion_summary(res), "keep": c.keep, "rows": ids})
    total = sum(c["score"] for c in criteria) * rubric.weight
    gaps = [r for c in sorted(criteria, key=lambda c: c["score"]) for r in rows if r["criterion"] == c["id"] and r["kind"] == "gap" and r["advice"]]
    focus: list[str] = []
    for r in gaps:
        if r["advice"] not in focus:
            focus.append(r["advice"])
    accepted = facts.accepted
    rerun = facts.rerun
    prior = [a for a in (history or []) if a["attempt"] != attempt]
    record = {"attempt": attempt, **({"kind": "demo", "variant": variant} if kind == "demo" else {}), "total": total, "scores": {c["id"]: c["score"] for c in criteria}, "project": project,
              "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(finished_at or time.time())), "elapsed": accepted["t"] if accepted else facts.session[-1]["t"]}
    return {
        "version": REPORT_VERSION, "scenario": scenario.id, "title": scenario.title, "project": project, "attempt": attempt, "kind": kind, "variant": variant,
        "total": total, "max": rubric.max_total, "elapsed": record["elapsed"], "minutes": scenario.minutes, "finished_at": record["finished_at"],
        "rubric": {"id": rubric.id, "version": rubric.version}, "criteria": criteria, "rows": rows, "events": {i: events[i] for i in {e for r in rows for e in r["events"]}},
        "fairness": {"points": len(rows), "quoted": sum(1 for r in rows if r["quote"]), "matched": sum(1 for r in rows if r["verified"]), "dropped": [d.as_dict() for d in dropped],
                     "tests_rerun": {"ok": bool(rerun and rerun.get("ok")), "passed": rerun.get("passed", 0), "total": rerun.get("passed", 0) + rerun.get("failed", 0)} if rerun else None,
                     "rubric": f"v{rubric.version}", "voices": {"judges": "template", "coach": "template", "reason": ""}, "ai_rejected": []},
        "focus": focus[:3] or [f"Full marks already. Beat your time of {clock(record['elapsed'])}, or take these habits to the next scenario."],
        "coach": {"text": template_coach(total, rubric.max_total, criteria, rows, focus), "source": "template"},
        "judge_lines": {}, "attempts": [*prior, record], "files": {"md": f".q/reports/attempt-{attempt}.md", "json": f".q/reports/attempt-{attempt}.json"},
    }


def template_coach(total: int, top: int, criteria: list[dict], rows: list[dict], focus: list[str]) -> str:
    """The overall paragraph when the model does not write it: the score, the best and the weakest criterion and what to do first, from the findings only."""
    best = max(criteria, key=lambda c: c["score"])
    weak = min(criteria, key=lambda c: c["score"])
    lines = [f"You scored {total} out of {top}."]
    if best["score"] == weak["score"]:
        lines.append(f"Every criterion scored {best['score']} out of {best['max']}.")
    else:
        lines.append(f"{best['name']} was your strongest area ({best['score']}/{best['max']}) and {weak['name']} the weakest ({weak['score']}/{weak['max']}).")
    lines.append(f"First thing for the next attempt: {focus[0][0].lower() + focus[0][1:]}" if focus else "There is nothing to fix: beat your time or take these habits to the next scenario.")
    return " ".join(lines)


def attach_voices(report: dict, judge_lines: dict[str, dict], coach: dict, dropped: list[Dropped], reason: str = "") -> dict:
    """Add what the model said (when it passed the verifier) to the report: each judge's spoken line and the coach paragraph, with who wrote each. The AI texts the verifier rejected
    are listed apart (`fairness.ai_rejected`, with the reason): `fairness.dropped` is for the evidence points only."""
    report["judge_lines"] = judge_lines
    report["coach"] = coach
    report["fairness"]["ai_rejected"] = [d.as_dict() for d in dropped]
    sources = {v["source"] for v in judge_lines.values()}
    report["fairness"]["voices"] = {"judges": "model" if sources == {"model"} else "template" if "model" not in sources else "mixed", "coach": coach["source"], "reason": reason}
    return report


def render_markdown(report: dict, names: dict[str, str]) -> str:
    head = f"Demo run, {report.get('variant') or 'autoplay'} (attempt {report['attempt']} of the demos)" if report.get("kind") == "demo" else f"Attempt {report['attempt']}"
    lines = [f"# Debrief: {report['title']}", "", f"**{head}: {report['total']}/{report['max']}** · {clock(report['elapsed'])} on the clock · rubric {report['rubric']['id']}", ""]
    lines += [f"_{'AI coach' if report['coach']['source'] == 'model' else 'Summary'}:_ {report['coach']['text']}", ""]
    lines += ["| Criterion | Judge | Score |", "| --- | --- | --- |", *[f"| {c['name']} | {c['judge_name']} | {c['score']}/{c['max']} |" for c in report["criteria"]], ""]
    for c in report["criteria"]:
        lines += [f"## {c['name']} {c['score']}/{c['max']}", "", f"_{c['summary']}_", ""]
        for r in (x for x in report["rows"] if x["criterion"] == c["id"]):
            lines += [f"- **{r['kind'].upper()}** {clock(r['t'])} · {r['source']} · {r['event']}: “{r['quote']}”", f"  {r['note']}" + (f" Next attempt: {r['advice']}" if r["advice"] else "") + " [rule]"]
        lines.append("")
    f = report["fairness"]
    rerun = f["tests_rerun"]
    lines += ["## Fairness checks", "", f"- Points that quote a moment: {f['quoted']}/{f['points']}", f"- Quotes matched to the session log: {f['matched']}/{f['points']}",
              f"- Unbacked claims dropped: {len(f['dropped'])}", *[f"  - dropped: “{d['text']}” ({d['reason']})" for d in f["dropped"]],
              f"- AI lines not used: {len(f['ai_rejected'])}", *[f"  - {d['finding']}: “{d['text']}” ({d['reason']})" for d in f["ai_rejected"]],
              f"- Tests re-run, not guessed: {(str(rerun['passed']) + '/' + str(rerun['total'])) if rerun else 'could not be re-run'}",
              f"- Same rubric for every attempt: {f['rubric']}", f"- Judges' lines: {f['voices']['judges']}; coach paragraph: {f['voices']['coach']}" + (f" ({f['voices']['reason']})" if f["voices"]["reason"] else ""), ""]
    lines += ["## Focus for the next attempt", "", *[f"{i}. {x}" for i, x in enumerate(report["focus"], 1)], ""]
    lines += ["## Attempts", "", *[f"- Attempt {a['attempt']}: {a['total']}/{report['max']}" for a in report["attempts"]], ""]
    return "\n".join(lines)


def write_report(root: Path, report: dict, names: dict[str, str]) -> None:
    folder = Path(root) / ".q" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    n = report["attempt"]
    (folder / f"attempt-{n}.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    (folder / f"attempt-{n}.md").write_text(render_markdown(report, names), encoding="utf-8", newline="\n")
