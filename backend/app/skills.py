"""Skill packs: what Q knows about a kind of app, as data (config/skills/<name>.yaml, plus a short <name>.md).

A pack holds the match keywords, the vocabulary and labels, the typical modules and fields (used only to enrich a SHORT goal: a field the user wrote is never removed),
declarative rules (required, unique, phone, email, positive rupees, bounds, a status flow, a capacity limit) that become generated code and generated tests,
dashboard KPIs and charts, empty-state copy, icons, a skin (theme and type pairing) and the words of the seed data.
Matching is by rules, not by a model; the Architect and the spec step receive the matched pack in their context.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .config import CONFIG_DIR
from .schemas import ResourceRules, singular

SKILLS_DIR = CONFIG_DIR / "skills"


@lru_cache(maxsize=1)
def packs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(SKILLS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        data.setdefault("name", f.stem)
        out[data["name"]] = data
    return out


def pack(name: str) -> dict | None:
    return packs().get(name) if name else None


def pack_notes(name: str) -> str:
    """The short .md of a pack: domain notes for the model steps."""
    f = SKILLS_DIR / f"{name}.md"
    return f.read_text(encoding="utf-8").strip() if f.is_file() else ""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower().replace("_", " "))


def match_skill(goal: str, title: str = "", resources: list[str] | None = None) -> str:
    """The pack whose keywords the goal, the title and the resource names mention most (the app's name counts three times); '' when none matches."""
    head, _, rest = goal.partition(":")
    main = set(_words(" ".join([head, title, *(resources or [])])))
    main |= {singular(w) for w in main}
    body = set(_words(rest))
    body |= {singular(w) for w in body}
    best, best_score = "", 0
    for name, p in packs().items():
        keys = {k.lower() for k in p.get("keywords", [])}
        score = 3 * len(keys & main) + len(keys & body)
        if score > best_score:
            best, best_score = name, score
    return best


def _rx(pattern: str | None) -> re.Pattern[str]:
    return re.compile(pattern or ".*", re.I)


def rules_for(skill: str, r, resources: list) -> ResourceRules:
    """The rules of the matched pack that fit this resource (`r` is a SpecResource): a rule never adds a field and never applies to a field that is not there."""
    p = pack(skill)
    out = ResourceRules()
    if not p:
        return out
    by = {f.name: f for f in r.fields}
    plain = lambda f: f.type == "string" and not f.options  # noqa: E731
    for rule in p.get("rules", []):
        if not _rx(rule.get("resource")).fullmatch(r.name):
            continue
        kind = rule.get("rule")
        if kind in ("phone", "email", "positive", "unique", "bounds"):
            rx = _rx(rule.get("field"))
            for f in r.fields:
                if not rx.fullmatch(f.name):
                    continue
                if kind in ("phone", "email") and plain(f) and f.name not in getattr(out, kind):
                    getattr(out, kind).append(f.name)
                elif kind == "unique" and plain(f) and f.name not in out.unique:
                    out.unique.append(f.name)
                elif kind == "positive" and f.type in ("number", "integer") and f.name not in out.positive:
                    out.positive.append(f.name)
                elif kind == "bounds" and f.type in ("number", "integer"):
                    out.bounds[f.name] = [float(x) for x in rule.get("args", [0, 100])]
        elif kind == "flow":
            f = by.get(rule.get("field", "status"))
            labels = (f.options if f else [])
            flow = rule.get("flow") or {}
            if f and labels and all(k in labels for k in flow):
                out.status_field = f.name
                out.transitions = {k: [x for x in flow.get(k, []) if x in labels] for k in labels if k in flow}
        elif kind == "capacity" and r.parent:
            parent = next((x for x in resources if x.name == r.parent), None)
            field = rule.get("field", "capacity")
            if parent and any(f.name == field and f.type in ("number", "integer") for f in parent.fields):
                out.capacity_field = field
                status = next((f for f in r.fields if f.options and re.search(r"status|state", f.name)), None)
                if status and not out.status_field:
                    out.status_field = status.name
    return out


def skill_hints(name: str) -> str:
    """What the spec step is told about a matched pack: its notes and its typical modules (a short goal is enriched from them)."""
    p = pack(name)
    if not p:
        return ""
    modules = "\n".join(f"- {m['name']}" + (f" (belongs to {m['parent']})" if m.get("parent") else "") + f": {m['fields']}" for m in p.get("modules", []))
    return f"{pack_notes(name)}\nTypical modules and fields:\n{modules}".strip()


def skin_of(skill: str, fallback: str = "studio") -> str:
    p = pack(skill)
    return (p or {}).get("skin") or fallback
