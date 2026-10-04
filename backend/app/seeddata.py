"""Realistic seed rows for a generated app, so a freshly opened app looks alive: Indian names, rupees, local places, near-future dates.

The rows follow the contract (every field, every label) and the rules of the skill pack (valid phone numbers, unique emails, positive amounts, bounds, a place left
in every event). They are written to `seed.json` (a locked loader, backend/seed.py, inserts them when the app is started to be looked at, never in tests).
Deterministic: the same app gets the same rows.
"""
from __future__ import annotations

import re
import zlib
from datetime import date, timedelta

from .schemas import ArchitectOutput, FieldSpec, ResourceInfo
from .skills import pack as _pack

PEOPLE = ["Aarav Sharma", "Meera Iyer", "Rohan Gupta", "Kavya Nair", "Imran Qureshi", "Sneha Kulkarni", "Arjun Reddy", "Priya Menon", "Vikram Shah", "Ananya Rao",
          "Farhan Ali", "Ishita Jain", "Karthik Raman", "Pooja Nair", "Aditya Menon", "Zoya Khan", "Siddharth Patil", "Neha Deshmukh", "Rahul Verma", "Lakshmi Iyer"]
PLACES = ["Indiranagar, Bengaluru", "Bandra West, Mumbai", "Connaught Place, Delhi", "T Nagar, Chennai", "Koramangala, Bengaluru", "Hitech City, Hyderabad", "Kothrud, Pune", "Salt Lake, Kolkata"]
ORGS = ["Zenith Labs", "Kavya Foods", "Tata Elxsi", "Razorpay", "Chai Point", "Freshworks", "Infosys Foundation", "Mahindra Logistics"]
COLLEGES = ["IIT Bombay", "NIT Trichy", "BITS Pilani", "VIT Vellore", "PES University", "COEP Pune", "Manipal Institute"]
SENTENCES = ["Really happy with how this turned out.", "Could be better, but a good start.", "Sharing what worked for me last week.", "Worth a look if you are in the area.",
             "Quick note for everyone following along.", "This one needs a follow-up next week."]
MONEY = [("fee", [0, 100, 250, 500]), ("fare", [180, 240, 420, 650, 1100]), ("price", [199, 499, 1299, 2499, 899]), ("amount", [5000, 10000, 25000, 50000, 15000]),
         ("cost", [300, 450, 700, 1200]), ("salary", [25000, 40000, 65000]), ("budget", [10000, 20000, 50000]), ("total", [450, 980, 1500, 2400])]
BASE = date(2026, 10, 4)


def _h(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def _pool(pools: dict, resource: str, name: str):
    return pools.get(f"{resource}.{name}") or pools.get(name)


def _value(ri: ResourceInfo, f: FieldSpec, i: int, pools: dict, seen: dict) -> object:
    name = f.name
    pool = _pool(pools, ri.name, name)
    if f.options:
        weights = [0, 0, 1, 1, 2, 3] if len(f.options) > 3 else [0, 0, 1, 2]
        return f.options[weights[(i * 5 + _h(ri.name, name) % 4) % len(weights)] % len(f.options)]
    if f.type == "boolean":
        return i % 3 == 0
    if f.type in ("number", "integer"):
        if pool:  # the pack knows what such a number looks like (a daily expense is a few hundred rupees, not fifty thousand)
            return pool[i % len(pool)]
        if name in ri.rules.bounds:
            lo, hi = ri.rules.bounds[name]
            return int(lo + (hi - lo) * ((i * 37 + 11) % 100) / 100) if f.type == "integer" else round(lo + (hi - lo) * ((i * 37 + 11) % 100) / 100, 1)
        if re.search(r"rating|stars?", name):
            return [5, 4, 4, 3, 5][i % 5]
        if re.search(r"capacity|seats|limit|quota", name):
            return [120, 80, 200, 60, 150][i % 5]
        for key, values in MONEY:
            if key in name:
                return values[(i + _h(ri.name, name)) % len(values)]
        return 3 + (i * 7) % 40 if f.type == "integer" else round(2.5 + i * 3.5, 2)
    if name in ri.rules.phone or re.search(r"phone|mobile", name):
        return f"{9 - (i % 2)}{(_h(ri.name, name, i) % 900_000_000) + 100_000_000}"[:10]
    if name in ri.rules.email or "email" in name:
        n = seen.setdefault("email", [0])
        n[0] += 1
        who = str(seen.get("last_person", "user")).lower().replace(" ", ".")
        return f"{who}{n[0]}@example.com"
    if "date" in name:
        return (BASE + timedelta(days=3 + (i * 5 + _h(ri.name, name) % 6) % 40)).isoformat()
    if re.search(r"(^|_)time$", name):
        return ["09:30", "11:00", "14:00", "16:30", "18:00"][i % 5]
    if pool:
        return pool[i % len(pool)]
    if re.search(r"name|student|author|patient|passenger|contact|owner|guest|member|sender|doctor|driver", name) and not re.search(r"company|college|team|event|course|file|project", name):
        who = PEOPLE[(i * 3 + _h(ri.name, name) % 7) % len(PEOPLE)]
        seen["last_person"] = who.split()[0]
        return who
    if re.search(r"company|org|brand|supplier", name):
        return ORGS[i % len(ORGS)]
    if "college" in name or "school" in name or "university" in name:
        return COLLEGES[i % len(COLLEGES)]
    if re.search(r"city|location|venue|area|address|place|pickup|drop", name):
        return PLACES[(i + _h(name) % 5) % len(PLACES)]
    if re.search(r"content|comment|description|message|reason|notes?|details|text|about|body|caption|title", name):
        return SENTENCES[(i + _h(ri.name, name)) % len(SENTENCES)]
    return f"{name.replace('_', ' ').capitalize()} {i + 1}"


def seed_rows(design: ArchitectOutput, skill: str = "") -> dict[str, list[dict]]:
    """{table: rows}; a child row names its parent row by `_of`, `_idx` and `_fk` (backend/seed.py resolves them)."""
    pools = (_pack(skill) or {}).get("pools", {})
    out: dict[str, list[dict]] = {}
    seen: dict = {}
    uniq: set[tuple[str, str, object]] = set()
    parents = [r for r in design.resources if not r.parent]
    by = {r.name: r for r in design.resources}

    def make(ri: ResourceInfo, i: int) -> dict:
        row: dict = {}
        first_text = next((f.name for f in ri.fields if f.type == "string" and not f.options), "")
        for f in ri.fields:
            v = _value(ri, f, i, pools, seen)
            if f.name == first_text and f.name not in ri.rules.unique:  # the main text of a row differs from row to row (two doctors called Dr. Rao read as a bug)
                shown = seen.setdefault(("titles", ri.name), set())
                k = 0
                while v in shown and k < 40:
                    k += 1
                    v = _value(ri, f, i + k * 7, pools, seen)
                shown.add(v)
            if f.name in ri.rules.unique:
                k = 0
                while (ri.name, f.name, v) in uniq:
                    k += 1
                    v = f"{v} {k}" if isinstance(v, str) and f.name not in ri.rules.email else v
                    if k > 50:
                        break
                uniq.add((ri.name, f.name, v))
            row[f.name] = v
        for c in ri.counters:
            row[c] = (i * 5 + 3) % 17
        return row

    for p in parents:
        out[p.name] = [make(p, i) for i in range(6)]
        for ch in [r for r in design.resources if r.parent == p.name]:
            rows = []
            for pi in range(len(out[p.name])):
                cap = out[p.name][pi].get(ch.rules.capacity_field) if ch.rules.capacity_field else None
                n = min(2 + (pi * 3 + _h(ch.name)) % 4, int(cap) if cap else 99)
                for k in range(n):
                    row = make(ch, len(rows))
                    row.update({"_of": p.name, "_idx": pi, "_fk": ch.fk})
                    rows.append(row)
            out[ch.name] = rows
    del by
    return out


def seed_for(design: ArchitectOutput, skill: str = "") -> dict[str, list[dict]]:
    """The rows of any shell app: a related design by its resources, a single resource (todo, expenses) by its contract."""
    if design.resources:
        return seed_rows(design, skill)
    from .uistub import Shape

    s = Shape(design)
    if not (s.ok and design.tables):
        return {}
    table = design.tables[0].name
    ri = ResourceInfo(name=table, singular=table, fields=list(s.inputs))
    pools = (_pack(skill) or {}).get("pools", {})
    seen: dict = {}
    return {table: [{f.name: _value(ri, f, i, pools, seen) for f in ri.fields} for i in range(6)]}


def seed_test_source() -> str:
    return "\n".join([
        '"""Generated: the sample data loads into the finished schema (every row, every label, every rule). Do not edit; fix the database modules instead."""',
        "import json", "from pathlib import Path", "", "from backend.seed import seed", "", "ROOT = Path(__file__).resolve().parents[2]", "", "",
        "def test_the_sample_data_loads_into_an_empty_database():",
        "    expected = {t: len(rows) for t, rows in json.loads((ROOT / 'seed.json').read_text(encoding='utf-8')).items()}",
        "    assert seed(force=True) == expected",
    ]) + "\n"
