"""My progress: what the learner's real attempts add up to, across scenarios.

Only the learner's own history counts (`<workspace>/.q-attempts/<scenario>.json`); an autoplay demo keeps its own file (`<scenario>-demo.json`) and is never read here.
Everything is computed from the stored records (`History`) and, for the quoted gap, from the saved report of the attempt (`<project>/.q/reports/attempt-N.json`), so the page,
the endpoint and the exports all show the same numbers. No model is involved: the suggestion is a sentence built from the numbers.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .loader import list_scenarios
from .reports import History
from .rubric import load_rubric
from .scoring import clock

VERSION = 1
TREND_STEP = 0.5  # the latest score against the average of the earlier ones: this much or more is up or down
WEAK_BELOW = 3  # a last score under this on the weakest skill is worth retrying
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def catalog() -> list[dict]:
    """The scenarios Q ships, with the criteria of their rubrics: [{id, title, minutes, max, criteria: [{id, name}]}]."""
    out = []
    for s in list_scenarios():
        rubric = load_rubric(s)
        out.append({"id": s.id, "title": s.title, "minutes": s.minutes, "max": rubric.max_total, "per": rubric.points_per_criterion,
                    "criteria": [{"id": c.id, "name": c.name} for c in rubric.criteria]})
    return out


def _num(value, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _real_attempts(workspace: Path, scenario_id: str) -> list[dict]:
    """The learner's finished attempts of a scenario, oldest first. A record that is not a plain attempt (a demo, or no scores) is left out."""
    out = []
    for a in History(workspace, scenario_id).attempts():
        scores = a.get("scores")
        if a.get("kind") == "demo" or not isinstance(scores, dict) or isinstance(a.get("total"), bool) or not isinstance(a.get("total"), (int, float)):
            continue
        out.append({"attempt": a["attempt"], "total": a["total"], "scores": {k: int(v) for k, v in scores.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
                    "date": str(a.get("finished_at") or ""), "elapsed": _num(a.get("elapsed")), "project": str(a.get("project") or "")})
    return out


def _trend(scores: list[int]) -> str:
    """Oldest first. `new` for a single score; otherwise the latest against the average of the earlier ones."""
    if len(scores) < 2:
        return "new"
    delta = scores[-1] - sum(scores[:-1]) / (len(scores) - 1)
    return "up" if delta >= TREND_STEP else "down" if delta <= -TREND_STEP else "steady"


def report_path(workspace: Path, project: str, attempt: int, ext: str = "json") -> Path | None:
    """`<workspace>/<project>/.q/reports/attempt-N.<ext>` when the project name is one plain folder name inside the workspace."""
    if not _NAME.match(project or "") or project in (".", ".."):
        return None
    base = Path(workspace).resolve()
    path = (base / project / ".q" / "reports" / f"attempt-{int(attempt)}.{ext}").resolve()
    return path if base in path.parents else None


def read_report(workspace: Path, project: str, attempt: int, scenario_id: str) -> dict | None:
    """The saved report of a real attempt, or None: the file is gone or damaged, it belongs to another attempt, or it is a demo's."""
    path = report_path(workspace, project, attempt)
    try:
        report = json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("kind") == "demo" or report.get("scenario") != scenario_id or report.get("attempt") != attempt:
        return None
    return report


def _gap_of(workspace: Path, skill: str, records: list[tuple[dict, dict]]) -> dict | None:
    """The newest real report that has a gap for the skill: its first gap row of that criterion, as the report states it (the judge quotes the same row)."""
    for rec, scn in records:  # newest first
        report = read_report(workspace, rec["project"], rec["attempt"], scn["id"])
        row = next((r for r in (report or {}).get("rows", []) if isinstance(r, dict) and r.get("criterion") == skill and r.get("kind") == "gap"), None)
        if row:
            return {"scenario": scn["id"], "title": scn["title"], "attempt": rec["attempt"], "row": row.get("id", ""), "t": row.get("t", 0), "clock": clock(_num(row.get("t"))),
                    "source": row.get("source", ""), "quote": row.get("quote", ""), "note": row.get("note", ""), "advice": row.get("advice", "")}
    return None


def build_progress(workspace: Path, scenarios: list[dict] | None = None) -> dict:
    """Everything the My progress page shows. `scenarios` is the catalog (default: the shipped scenarios)."""
    workspace = Path(workspace)
    scenarios = catalog() if scenarios is None else scenarios
    per_scn: list[dict] = []
    flat: list[tuple[dict, dict]] = []  # (attempt, scenario) of every real attempt
    for scn in scenarios:
        attempts = [{**a, "max": scn["max"]} for a in _real_attempts(workspace, scn["id"])]
        per_scn.append({"id": scn["id"], "title": scn["title"], "minutes": scn.get("minutes", 0), "max": scn["max"], "attempts": attempts, "count": len(attempts),
                        "best_score": max((a["total"] for a in attempts), default=None), "best_time": min((a["elapsed"] for a in attempts), default=None),
                        "last_total": attempts[-1]["total"] if attempts else None})
        flat += [(a, scn) for a in attempts]
    flat.sort(key=lambda p: (p[0]["date"], p[1]["id"], p[0]["attempt"]))  # oldest first across scenarios
    names: dict[str, str] = {}
    for scn in scenarios:
        for c in scn["criteria"]:
            names.setdefault(c["id"], c["name"])
    top = max((scn.get("per", 4) for scn in scenarios), default=4)
    skills = []
    for cid, name in names.items():
        scores = [a["scores"][cid] for a, _ in flat if cid in a["scores"]]
        skills.append({"id": cid, "name": name, "max": top, "count": len(scores), "latest": scores[-1] if scores else None,
                       "average": round(sum(scores) / len(scores), 2) if scores else None, "trend": _trend(scores) if scores else "none"})
    weakest = _weakest(workspace, skills, flat)
    return {"version": VERSION, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "empty": not flat, "attempts_total": len(flat), "scenarios": per_scn, "skills": skills,
            "weakest": weakest, "next_step": _next_step(per_scn, weakest) if flat else None}


def _weakest(workspace: Path, skills: list[dict], flat: list[tuple[dict, dict]]) -> dict | None:
    scored = [s for s in skills if s["average"] is not None]
    if not scored:
        return None
    # lowest average; a tie goes to the lower latest score, then to the rubric's order
    s = min(scored, key=lambda s: (s["average"], s["latest"]))
    if s["average"] >= s["max"]:
        return None  # full marks on every attempt: nothing is weak
    newest_first = [p for p in reversed(flat) if s["id"] in p[0]["scores"]]
    gap = _gap_of(workspace, s["id"], newest_first)
    reason = "" if gap else f"No saved report with a {s['name']} gap was found (the project folders of earlier attempts may have been deleted)."
    return {"skill": s["id"], "name": s["name"], "average": s["average"], "latest": s["latest"], "max": s["max"], "gap": gap, "reason": reason}


def _score(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))


def _next_step(per_scn: list[dict], weakest: dict | None) -> dict:
    """One suggestion and the sentence that says why, from the numbers only."""
    attempted = [s for s in per_scn if s["attempts"]]
    fresh = next((s for s in per_scn if not s["attempts"]), None)
    if weakest:
        skill, name, top = weakest["skill"], weakest["name"], weakest["max"]
        lows = sorted(((s["attempts"][-1]["scores"].get(skill), s["attempts"][-1]["total"], i, s) for i, s in enumerate(attempted) if skill in s["attempts"][-1]["scores"]),
                      key=lambda x: x[:3])
        low = lows[0] if lows else None
        why = f"{name} is your weakest skill (average {_score(weakest['average'])}/{top})"
        if low and low[0] < WEAK_BELOW:
            s = low[3]
            return {"kind": "retry", "scenario": s["id"], "title": s["title"], "skill": skill,
                    "reason": f"Retry {s['title']}: your last attempt there scored {low[0]}/{top} on {name}, the lowest of your latest attempts, and {why}."}
        if fresh:
            return {"kind": "new", "scenario": fresh["id"], "title": fresh["title"], "skill": skill,
                    "reason": f"Try {fresh['title']}: you have not attempted it yet, and {why}."}
        if low and low[0] < top:
            s = low[3]
            return {"kind": "retry", "scenario": s["id"], "title": s["title"], "skill": skill,
                    "reason": f"Retry {s['title']}: your last attempt there scored {low[0]}/{top} on {name}, the lowest of your latest attempts, and {why}."}
    if fresh:
        return {"kind": "new", "scenario": fresh["id"], "title": fresh["title"], "skill": "", "reason": f"Try {fresh['title']}: every skill is at full marks so far, and you have not attempted it yet."}
    s = max(attempted, key=lambda s: (s["best_time"] / (s["minutes"] * 60)) if s["minutes"] else s["best_time"])  # the one closest to its time box has the most to gain
    return {"kind": "beat", "scenario": s["id"], "title": s["title"], "skill": "",
            "reason": f"Every skill is at full marks; beat your best time of {clock(s['best_time'])} on {s['title']}."}


def render_markdown(p: dict) -> str:
    """The same data as the page, as a markdown file."""
    lines = ["# My progress", "", f"Generated {p['generated_at']} · {p['attempts_total']} real attempt{'s' if p['attempts_total'] != 1 else ''} (demo runs never count).", ""]
    if p["empty"]:
        return "\n".join(lines + ["No real attempts yet. Start a scenario in Simulation mode; your first finished attempt shows up here.", ""])
    lines += ["## Scenarios", ""]
    for s in p["scenarios"]:
        lines += [f"### {s['title']}", ""]
        if not s["attempts"]:
            lines += ["Not attempted yet.", ""]
            continue
        lines += [f"Best score {s['best_score']}/{s['max']} · best time {clock(s['best_time'])}", "", "| Attempt | Score | Date | Time |", "| --- | --- | --- | --- |",
                  *[f"| {a['attempt']} | {a['total']}/{a['max']} | {a['date'].replace('T', ' ')} | {clock(a['elapsed'])} |" for a in s["attempts"]], ""]
    lines += ["## Skills across all scenarios", "", "| Skill | Latest | Average | Trend |", "| --- | --- | --- | --- |",
              *[f"| {k['name']} | {'-' if k['latest'] is None else str(k['latest']) + '/' + str(k['max'])} | {'-' if k['average'] is None else _score(k['average']) + '/' + str(k['max'])} | {k['trend']} |" for k in p["skills"]], ""]
    w = p["weakest"]
    lines += ["## Weakest skill", ""]
    if not w:
        lines += ["None: every skill is at full marks.", ""]
    else:
        lines += [f"**{w['name']}** (average {_score(w['average'])}/{w['max']}, latest {w['latest']}/{w['max']}).", ""]
        g = w["gap"]
        lines += [f"Most recent gap, {g['title']} attempt {g['attempt']} at {g['clock']}: “{g['quote']}”", "", g["note"] + (f" Next attempt: {g['advice']}" if g["advice"] else ""), ""] if g else [w["reason"], ""]
    n = p["next_step"]
    lines += ["## Suggested next step", "", n["reason"] if n else "-", ""]
    return "\n".join(lines)
