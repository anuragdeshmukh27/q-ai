"""Sandboxed tool layer: the only way an agent touches files or runs commands.

Every call goes through the path policy and the command policy, honours the
autonomy mode, and is logged (agent, args, result, duration, approval decision).
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .agent.actions import Action
from .config import AgentConfig
from .sandbox.commands import ALLOW, ASK, DENY, CommandPolicy, apply_mode
from .sandbox.paths import PathPolicy, SandboxError
from .sandbox.runner import resolve_argv, run_command

MAX_READ_CHARS = 12_000
MAX_WRITE_CHARS = 1_000_000
MAX_SEARCH_HITS = 50
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".worktrees"}
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)

Approver = Callable[[str, str, str, dict], bool]


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict = field(default_factory=dict)
    finished: bool = False
    needs_human: bool = False


def _fail(msg: str, **data) -> ToolResult:
    return ToolResult(False, msg, data)


class ToolBox:
    def __init__(
        self,
        root: Path | str,
        agent: AgentConfig,
        mode: str = "supervised",
        approver: Approver | None = None,
        emit: Callable[..., object] | None = None,
        human: Callable[[str], str | None] | None = None,
        message_sink: Callable[[str, str, str], None] | None = None,
        extra_allowed: list[str] | None = None,
        test_cmd: str = "python -m pytest -q",
        command_timeout: float = 60,
        max_output: int = 20_000,
        on_output: Callable[[str], None] | None = None,
    ):
        self.root = Path(os.path.realpath(root))
        self.agent = agent
        self.mode = mode
        self.approver = approver
        self.human = human
        self.message_sink = message_sink
        self.test_cmd = test_cmd
        self.command_timeout = command_timeout
        self.max_output = max_output
        self.on_output = on_output
        self.paths = PathPolicy(self.root, agent.owned_paths, agent.forbidden_paths)
        self.commands = CommandPolicy(self.root, extra_allowed=[test_cmd, *(extra_allowed or [])])
        self.emit = emit or (lambda *a, **k: None)
        self.log: list[dict] = []
        self.files_touched: list[str] = []

    # -- dispatch -------------------------------------------------------------------
    def execute(self, action: Action) -> ToolResult:
        start = time.time()
        name = action.action
        if name not in self.agent.tools:
            result = _fail(f"tool '{name}' is not available to the {self.agent.role}")
            result.data["decision"] = "deny"
        else:
            try:
                result = getattr(self, f"_{name}")(action)
            except SandboxError as e:
                result = _fail(str(e), decision="deny")
            except Exception as e:  # never leak a stack trace to the agent or the UI
                result = _fail("tool failed unexpectedly; try a different approach", error=type(e).__name__)
        result.data.setdefault("decision", "allow")
        args = {k: (v[:300] + "..." if len(v) > 300 else v) for k, v in action.args().items()}
        entry = {
            "agent": self.agent.id,
            "tool": name,
            "args": args,
            "ok": result.ok,
            "decision": result.data["decision"],
            "duration": round(time.time() - start, 3),
            "output": result.output[:500],
        }
        self.log.append(entry)
        self.emit("tool_call", **entry)
        return result

    # -- approvals ------------------------------------------------------------------
    def _approve(self, kind: str, summary: str, details: dict) -> bool:
        self.emit("approval_needed", agent=self.agent.id, kind=kind, summary=summary, details=details)
        if self.approver is None:
            return False
        try:
            return bool(self.approver(self.agent.id, kind, summary, details))
        except Exception:
            return False

    # -- file tools -----------------------------------------------------------------
    def _list_dir(self, a: Action) -> ToolResult:
        p = (a.path or ".").strip()
        target = self.root if p in (".", "./", ".\\") else self.paths.resolve_read(p)
        if not target.is_dir():
            return _fail(f"not a directory: {a.path}")
        names = sorted(
            (e for e in target.iterdir() if e.name not in SKIP_DIRS),
            key=lambda e: (not e.is_dir(), e.name.casefold()),
        )
        return ToolResult(True, "\n".join(e.name + ("/" if e.is_dir() else "") for e in names) or "(empty)")

    def _read_file(self, a: Action) -> ToolResult:
        p = self.paths.resolve_read(a.path or "")
        if not p.exists():
            return _fail(f"file not found: {a.path}")
        if p.is_dir():
            return _fail(f"{a.path} is a directory; use list_dir")
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n[truncated: file has {len(text)} characters]"
        return ToolResult(True, text)

    def _write_file(self, a: Action) -> ToolResult:
        content = a.content or ""
        if len(content) > MAX_WRITE_CHARS:
            return _fail("file too large; keep files small (under ~150 lines)")
        p = self.paths.resolve_write(a.path or "")
        if p.is_dir():
            return _fail(f"{a.path} is a directory")
        rel = self.paths.rel(p)
        if self.mode == "assisted" and not self._approve("write", f"write {rel}", {"path": rel, "bytes": len(content)}):
            return _fail("write was not approved", decision="denied_by_human")
        old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        diff = "".join(
            difflib.unified_diff(old.splitlines(True), content.splitlines(True), f"a/{rel}", f"b/{rel}")
        )
        if rel not in self.files_touched:
            self.files_touched.append(rel)
        self.emit("file_changed", agent=self.agent.id, path=rel, diff=diff, created=not old)
        data = {"decision": "approved"} if self.mode == "assisted" else {}
        return ToolResult(True, f"wrote {rel} ({len(content.splitlines())} lines)", data)

    def _search(self, a: Action) -> ToolResult:
        pat = a.pattern or ""
        try:
            rx = re.compile(pat)
        except re.error:
            rx = re.compile(re.escape(pat))
        p = (a.path or ".").strip()
        base = self.root if p in (".", "./", ".\\") else self.paths.resolve_read(p)
        hits: list[str] = []
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in sorted(files):
                fp = Path(dirpath) / f
                try:
                    if fp.stat().st_size > 500_000:
                        continue
                    lines = fp.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for i, line in enumerate(lines, 1):
                    if rx.search(line):
                        hits.append(f"{self.paths.rel(fp)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= MAX_SEARCH_HITS:
                            return ToolResult(True, "\n".join(hits) + "\n[more matches omitted]")
        return ToolResult(True, "\n".join(hits) or "no matches")

    # -- commands -------------------------------------------------------------------
    def _run(self, a: Action) -> ToolResult:
        return self._run_command(a.command or "")

    def _run_command(self, command: str) -> ToolResult:
        verdict = self.commands.check(command)
        final = apply_mode(verdict, self.mode)
        if final == DENY:
            return _fail(f"command denied: {verdict.reason}", decision="deny")
        decision = "allow"
        if final == ASK:
            why = verdict.reason or "every command needs approval in assisted mode"
            if not self._approve("run", f"run: {command}", {"command": command, "reason": why}):
                return _fail(f"command was not approved ({why})", decision="denied_by_human")
            decision = "approved"
        res = run_command(
            resolve_argv(verdict.argv),
            self.root,
            timeout=self.command_timeout,
            max_output=self.max_output,
            on_output=self.on_output,
        )
        ok = res.exit_code == 0 and not res.timed_out
        out = res.output if res.timed_out else f"{res.output}\n[exit code {res.exit_code}]"
        return ToolResult(
            ok, out.strip(),
            {"decision": decision, "exit_code": res.exit_code, "timed_out": res.timed_out, "duration": res.duration},
        )

    def _run_tests(self, a: Action) -> ToolResult:
        r = self._run_command(self.test_cmd)
        if r.data.get("decision") in ("deny", "denied_by_human"):
            return r
        failed = _FAILED.findall(r.output)
        passed = r.data.get("exit_code") == 0
        if failed:
            signature = "|".join(sorted(failed))
        elif passed:
            signature = ""
        else:
            tail = re.sub(r"[\d.]+s\b|\d+", "#", "\n".join(r.output.splitlines()[-15:]))
            signature = "unstructured:" + hashlib.sha1(tail.encode()).hexdigest()[:12]
        summary = next((l for l in reversed(r.output.splitlines()) if re.search(r"passed|failed|error|no tests", l)), "")
        r.ok = passed
        r.data.update(passed=passed, failed=sorted(failed), signature=signature, summary=summary.strip())
        return r

    # -- communication / control ----------------------------------------------------
    def _send_message(self, a: Action) -> ToolResult:
        to, text = (a.to or "").strip(), (a.text or "").strip()
        if not to or not text:
            return _fail("send_message needs a recipient and text")
        if self.message_sink:
            self.message_sink(self.agent.id, to, text)
        self.emit("message_sent", **{"from": self.agent.id, "to": to, "text": text})
        return ToolResult(True, f"message sent to {to}")

    def _ask_human(self, a: Action) -> ToolResult:
        q = a.question or ""
        answer = self.human(q) if self.human else None
        if answer is None:
            return ToolResult(False, "waiting for a human answer", {"question": q}, needs_human=True)
        return ToolResult(True, f"human answered: {answer}", {"question": q})

    def _finish(self, a: Action) -> ToolResult:
        return ToolResult(True, a.summary or "", finished=True)
