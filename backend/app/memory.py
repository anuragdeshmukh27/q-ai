"""Project memory (`.q/`) and the message bus.

`.q/` holds the shared knowledge of a project. Agents read only what their role needs
(see `context_for`), which keeps prompts small enough for a 7B model.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, insert, select, update

from .schemas import ArchitectOutput, Endpoint, spec_text

# --- rendering ----------------------------------------------------------------------


def contract_dict(a: ArchitectOutput, version: int = 1) -> dict:
    return {
        "version": version,
        "error_format": {"detail": "string"},
        "endpoints": [
            {
                "method": e.method,
                "path": e.path,
                "summary": e.summary,
                "request": {"fields": [f.model_dump() for f in e.request_fields]},
                "response": {"status": e.response_status, "fields": [f.model_dump() for f in e.response_fields]},
                "errors": [x.model_dump() for x in e.errors],
                "examples": [x.model_dump() for x in e.examples],
            }
            for e in a.endpoints
        ],
    }


def _fields(fields: list[dict]) -> str:
    def one(f: dict) -> str:
        # a categorical field shows its labels, so engineers send and display "High", never a number
        return f"{f['name']}: " + (" | ".join(f'"{o}"' for o in f["options"]) if f.get("options") else f["type"])
    return "{" + ", ".join(one(f) for f in fields) + "}" if fields else "none"


def contract_brief(contract: dict) -> str:
    """The contract as short human-readable lines (7B models follow this better than raw JSON)."""
    lines = [f"API contract v{contract['version']} (errors are always JSON {{\"detail\": string}}):"]
    for e in contract["endpoints"]:
        where = "query/body" if e["method"] in ("GET", "DELETE") else "JSON body"
        lines.append(f"- {e['method']} {e['path']} - {e['summary']}")
        lines.append(f"    {where}: {_fields(e['request']['fields'])}")
        lines.append(f"    success: {e['response']['status']} {_fields(e['response']['fields'])}")
        for err in e["errors"]:
            lines.append(f"    error: {err['status']} detail \"{err['detail']}\"")
        for ex in e.get("examples", [])[:3]:
            lines.append(f"    example: {json.dumps(ex['request'])} -> {ex['status']} {json.dumps(ex['response'])}")
    return "\n".join(lines)


def architecture_md(a: ArchitectOutput, goal: str, spec=None) -> str:
    feats = "\n".join(f"- {f}" for f in a.ui_features)
    eps = "\n".join(f"- `{e.method} {e.path}`: {e.summary}" for e in a.endpoints)
    return (
        f"# Architecture\n\n**Goal:** {goal}\n\n**Preset:** {a.preset}\n\n{a.architecture.strip()}\n\n"
        + (f"## Product spec\n\n{spec_text(spec).replace('# ', '### ', 1)}\n" if spec is not None else "")
        + f"## Endpoints\n{eps}\n\n## Web page must\n{feats}\n"
    )


def schema_md(a: ArchitectOutput) -> str:
    if not a.tables:
        return "# Database schema\n\nThis app stores no data.\n"
    out = ["# Database schema", "", "SQLite. Connections come from `database.connection.get_conn()` (a `sqlite3.Row` factory).", ""]
    for t in a.tables:
        out += [f"## Table `{t.name}`", ""]
        out += [f"- `{c.name}` {c.type} {c.constraints}".rstrip() for c in t.columns]
        out.append("")
    out += ["## Data access functions (module chosen by the Database engineer, exported from `database/`)", ""]
    out += [f"- `{f.signature}`: {f.description}" for f in a.db_functions]
    return "\n".join(out) + "\n"


# --- memory -------------------------------------------------------------------------


class ProjectMemory:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.q = self.root / ".q"

    def read(self, name: str, default: str = "") -> str:
        p = self.q / name
        return p.read_text(encoding="utf-8") if p.is_file() else default

    def write(self, name: str, text: str) -> None:
        """System-level write (orchestrator bookkeeping). Agents write through the sandboxed ToolBox instead."""
        p = self.q / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")

    def append_decision(self, text: str) -> None:
        self.write("decisions.md", self.read("decisions.md", "# Decisions\n\n") + f"- {text}\n")

    def contract(self) -> dict | None:
        raw = self.read("api_contract.json")
        return json.loads(raw) if raw else None

    def design(self) -> ArchitectOutput | None:
        raw = self.read("design.json")
        return ArchitectOutput.model_validate_json(raw) if raw else None

    def goal(self) -> str:
        return self.read("goal.md").removeprefix("# Goal").strip()

    def tasks(self) -> list[dict]:
        raw = self.read("tasks.json")
        return json.loads(raw).get("tasks", []) if raw else []

    def context_for(self, agent_id: str) -> str:
        """Only the parts of the shared memory this role needs."""
        parts: list[str] = []
        contract = self.contract()
        if agent_id in ("backend", "frontend", "qa") and contract:
            parts.append(contract_brief(contract))
        if agent_id in ("backend", "database"):
            schema = self.read("database_schema.md")
            if schema:
                parts.append(schema)
        if agent_id == "frontend":
            m = re.search(r"## Web page must\n(.*?)(?:\n##|\Z)", self.read("architecture.md"), re.S)
            if m:
                parts.append("The web page must:\n" + m.group(1).strip())
        return "\n\n".join(parts)


# --- message bus --------------------------------------------------------------------

_meta = MetaData()
_messages = Table(
    "messages", _meta,
    Column("id", Integer, primary_key=True),
    Column("ts", Integer), Column("sender", String), Column("recipient", String),
    Column("kind", String), Column("text", Text), Column("read", Integer, default=0),
)


class MessageBus:
    """Agent-to-agent messages: persisted in SQLite (`.q/messages.db`) and mirrored as `.q/messages/NNN-from-to.md`."""

    def __init__(self, memory: ProjectMemory, emit=None):
        self.memory = memory
        self.emit = emit or (lambda *a, **k: None)
        (memory.q / "messages").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._engine = create_engine(f"sqlite:///{(memory.q / 'messages.db').as_posix()}")
        _meta.create_all(self._engine)

    def send(self, sender: str, to: str, text: str, kind: str = "message") -> int:
        with self._lock, self._engine.begin() as c:
            mid = c.execute(insert(_messages).values(ts=int(time.time()), sender=sender, recipient=to, kind=kind, text=text, read=0)).inserted_primary_key[0]
        slug = re.sub(r"[^a-z0-9]+", "-", f"{sender}-{to}".lower())
        (self.memory.q / "messages" / f"{mid:03d}-{slug}.md").write_text(f"From: {sender}\nTo: {to}\nKind: {kind}\n\n{text}\n", encoding="utf-8")
        return mid

    def inbox(self, agent_id: str, mark_read: bool = True) -> list[dict]:
        with self._lock, self._engine.begin() as c:
            rows = c.execute(select(_messages).where(_messages.c.recipient == agent_id, _messages.c.read == 0).order_by(_messages.c.id)).mappings().all()
            if mark_read and rows:
                c.execute(update(_messages).where(_messages.c.id.in_([r["id"] for r in rows])).values(read=1))
        return [dict(r) for r in rows]

    def all(self) -> list[dict]:
        with self._lock, self._engine.begin() as c:
            return [dict(r) for r in c.execute(select(_messages).order_by(_messages.c.id)).mappings().all()]
