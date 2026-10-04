"""A detailed goal that lists its things and their fields is followed as written, by rules.

"Build a cab booking app: drivers have name, phone, ..., car type Mini/Sedan/SUV and rating 1-5. Each driver has many rides. A ride has passenger name, ... fare in rupees
and status Requested/Accepted/On trip/Completed/Cancelled. Actions on a ride: mark completed and cancel. ..." is already a spec. Asking a 7B model to copy it into JSON
loses a field now and then (the 7-field cap made it drop `pickup time`, and sometimes a whole resource), so a goal with at least two linked resources whose fields are
listed in this style is read by rules; the model is only asked when the goal does not parse. Every field the user wrote is kept; the engine's caps still apply afterwards
(`normalize_spec`). Single-resource goals are not touched.
"""
from __future__ import annotations

import re

from .schemas import MAX_CHILDREN, SpecAction, SpecField, SpecOutput, SpecResource, goal_actions, singular

_SKIP = re.compile(r"^(?:mark|edit|delete|filter|sort|search|show|see|view|list|add|create)\b", re.I)
_UNITS = re.compile(r"\s+in\s+(?:rupees?|rs\.?|inr|₹|dollars?|usd)\s*$", re.I)
_MONEY = re.compile(r"amount|price|fare|fee|cost|salary|budget|total|balance|charge|rent|pay", re.I)
_INTEGER = re.compile(r"(^|_)(capacity|seats|quantity|count|age|year|stock|credits|rating|qty|marks|score|points|limit|rooms|guests|duration)$|^number_of", re.I)
_HAS = re.compile(r"^(?:an?\s+|the\s+)?(?P<name>[a-z][a-z ]{1,30}?)\s+(?:have|has)\s+(?:many\s+)?(?P<rest>.+)$", re.I)
_RELATION = re.compile(r"^(?:each|every)\s+(?P<parent>[a-z]+(?:\s[a-z]+)?)\s+(?:has|have|can have)\s+(?:many|several|multiple)\s+(?P<child>[a-z_ ]+?)\s*(?:[:,]\s*(?P<rest>.+))?$", re.I)


def plural(word: str) -> str:
    w = word.strip().lower().replace(" ", "_")
    if singular(w) != w:  # already plural
        return w
    if re.search(r"[^aeiou]y$", w):
        return w[:-1] + "ies"
    return w + ("es" if re.search(r"(s|x|z|ch|sh)$", w) else "s")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[a-z0-9)/])\.\s+(?=[A-Z])", text.strip())
    return [p.strip().rstrip(".") for p in parts if p.strip()]


def _snake(words: list[str]) -> str:
    return re.sub(r"[^a-z0-9_]+", "", "_".join(w.lower() for w in words))


def _field(token: str) -> SpecField | None:
    token = _UNITS.sub("", token.strip())
    if not token or _SKIP.match(token):
        return None
    words = token.split()
    cut = next((i for i, w in enumerate(words) if i > 0 and (w[0].isupper() or "/" in w or w[0].isdigit())), len(words))
    name = _snake(words[:cut])
    rest = " ".join(words[cut:])
    if not name:
        return None
    if "/" in rest:
        options = [o.strip() for o in rest.split("/") if o.strip()]
        return SpecField(name=name, type="string", options=options)
    if re.fullmatch(r"\d+\s*-\s*\d+", rest):
        return SpecField(name=name, type="integer")
    if _MONEY.search(name) and not re.search(r"(^|_)(id|name|type|status)$", name):
        return SpecField(name=name, type="number")
    if _INTEGER.search(name):
        return SpecField(name=name, type="integer")
    return SpecField(name=name, type="string")


def parse_fields(text: str) -> list[SpecField]:
    text = text.split(";")[0]
    out: list[SpecField] = []
    for token in re.split(r"\s*,\s*|\s+and\s+(?=[a-z])", text):
        f = _field(token)
        if f is not None and f.name not in {x.name for x in out}:
            out.append(f)
    return out


def goal_spec(goal: str) -> SpecOutput | None:
    """The spec a structured goal states, or None (the model step then runs as before)."""
    head, sep, body = goal.partition(":")
    if not sep:
        return None
    defs: dict[str, tuple[str, list[SpecField]]] = {}  # singular name -> (plural name, fields)
    relations: list[tuple[str, str]] = []  # (parent singular, child singular)
    for sentence in _sentences(body):
        m = _RELATION.match(sentence)
        if m:
            parent, child = singular(m["parent"].strip().replace(" ", "_")), singular(m["child"].strip().replace(" ", "_"))
            relations.append((parent, child))
            if m["rest"]:
                fields = parse_fields(m["rest"])
                if fields:
                    defs[child] = (plural(m["child"]), fields)
            else:
                defs.setdefault(child, (plural(m["child"]), []))
            continue
        m = _HAS.match(sentence)
        if m and not re.match(r"^(?:each|every|show|actions?)\b", sentence, re.I):
            name = m["name"].strip().replace(" ", "_")
            fields = parse_fields(m["rest"])
            if fields:
                s = singular(name)
                prior = defs.get(s)
                defs[s] = (prior[0] if prior else plural(name), fields)
    children: dict[str, list[str]] = {}
    for parent, child in relations:
        if parent in defs and child in defs and defs[child][1] and parent != child:
            children.setdefault(parent, []).append(child)
    if not children:
        return None
    root = next(iter(children))
    kids = list(dict.fromkeys(children[root]))[:MAX_CHILDREN]
    resources = [SpecResource(name=defs[root][0], fields=defs[root][1], operations=["list", "create", "update", "delete"])]
    for c in kids:
        resources.append(SpecResource(name=defs[c][0], parent=defs[root][0], fields=defs[c][1], operations=["list", "create", "update", "delete"]))
    wanted = goal_actions(goal, resources)
    for r in resources:
        status = next((f.name for f in r.fields if f.options and re.search(r"status|state|stage", f.name)), next((f.name for f in r.fields if f.options), ""))
        for phrase in wanted.get(r.name, []):
            if status and not any(a.name == phrase for a in r.actions):
                r.actions.append(SpecAction(name=phrase, field=status, kind="set"))
    title = re.sub(r"^(?:build|make|create|develop|design)\s+(?:an?\s+|the\s+)?", "", head.strip(), flags=re.I).strip()
    title = (title[:1].upper() + title[1:]) or "App"
    tail = body.split(".")[-1] if body.strip().endswith(".") is False else ""
    del tail
    names = [r.name.replace("_", " ") for r in resources]
    summary = f"Manage {names[0]} with their {', '.join(names[1:-1]) + (' and ' if len(names) > 2 else '') + names[-1]}." if len(names) > 1 else f"Manage {names[0]}."
    features = [f"Add, edit and delete {n}" for n in names]
    if any(re.search(r"\bfilter", s, re.I) for s in _sentences(body)):
        features.append("Filter lists by status or category")
    if any(re.search(r"\bsearch", s, re.I) for s in _sentences(body)):
        features.append("Search by name")
    features.append("Dashboard with totals and charts")
    return SpecOutput(title=title, summary=summary, resources=resources, features=features[:8])
