"""Sandboxed tool layer: the only way an agent touches files or runs commands.

Every call goes through the path policy and the command policy, honours the
autonomy mode, and is logged (agent, args, result, duration, approval decision).
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .agent.actions import Action
from .approvals import request_approval
from .config import AgentConfig
from .sandbox.commands import ALLOW, ASK, DENY, CommandPolicy, apply_mode
from .pybody import replace_function_body, undefined_calls, undefined_variables
from .sandbox.paths import PathPolicy, SandboxError
from .sandbox.runner import resolve_argv, run_command

MAX_READ_CHARS = 12_000
MAX_WRITE_CHARS = 1_000_000
MAX_SEARCH_HITS = 50
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".worktrees"}
_UNSAFE_CALL = re.compile(r"(?<![\w.])(eval|exec)\s*\(")
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)
_SECTION = re.compile(r"^_{3,} (.+?) _{3,}$", re.MULTILINE)
_FINAL_LINE = re.compile(r"^=+ .*\b(?:passed|failed|errors?|no tests ran)\b.* in [\d.]+s.*=+$|^\d+ (?:passed|failed).* in [\d.]+s", re.MULTILINE)
_LOCATION = re.compile(r"^(\S+\.py):(\d+): (\w+)", re.MULTILINE)


def failure_digest(output: str, limit: int = 6) -> str:
    """For each failing test: the exception message (the `E ` lines) and the last frame inside the project's own code.

    A request that ends in a server error (500) puts the real exception in the middle of a long framework traceback, which
    trimming an observation to head and tail would cut away. The digest is what the engineer must read first.
    """
    marks = list(_SECTION.finditer(output))
    parts = []
    for i, m in enumerate(marks[:limit]):
        body = output[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(output)]
        errors = [l[1:].strip()[:220] for l in body.splitlines() if l.startswith("E ") and l[1:].strip()]
        own = [x for x in _LOCATION.finditer(body) if ".venv" not in x.group(1) and "site-packages" not in x.group(1)]
        where = f"{own[-1].group(1)}:{own[-1].group(2)}" if own else ""
        if errors or where:
            parts.append(f"- {m.group(1)}" + (f" at {where}" if where else "") + ":\n    " + "\n    ".join(errors[:4]))
    if len(marks) > limit:
        parts.append(f"- ... and {len(marks) - limit} more failing tests")
    return "\n".join(parts)

Approver = Callable[[str, str, str, dict], bool]


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict = field(default_factory=dict)
    finished: bool = False
    needs_human: bool = False


def _must_return(fn: ast.FunctionDef) -> bool:
    """Route handlers (decorated with router.*) and functions annotated with a return type other than None have to return a value."""
    routed = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name) and d.func.value.id == "router" for d in fn.decorator_list)
    typed = fn.returns is not None and ast.unparse(fn.returns) != "None"
    return routed or typed


def _fail(msg: str, **data) -> ToolResult:
    return ToolResult(False, msg, data)


def _syntax_problem(rel: str, content: str) -> str:
    """Immediate, precise feedback for the model: which line of the file it just wrote does not parse."""
    try:
        compile(content, rel, "exec")
    except SyntaxError as e:
        lines = content.splitlines()
        text = lines[e.lineno - 1].strip() if e.lineno and 0 < e.lineno <= len(lines) else ""
        return f"wrote {rel}, but it is not valid Python: {e.msg} on line {e.lineno}: `{text}`. Fix that line and write the whole file again."
    return ""


def _js_problem(rel: str, path: Path) -> str:
    """`node --check` feedback for JavaScript files (skipped when node is not installed)."""
    node = shutil.which("node")
    if not node:
        return ""
    r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return ""
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    where = next((l for l in lines if re.search(r":\d+$", l)), "")
    msg = next((l for l in lines if "Error" in l), "SyntaxError")
    line_no = where.rsplit(":", 1)[-1] if where else "?"
    src = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text = src[int(line_no) - 1].strip() if line_no.isdigit() and int(line_no) <= len(src) else ""
    return f"wrote {rel}, but it is not valid JavaScript: {msg} on line {line_no}: `{text}`. Fix that line and write the whole file again."


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
        self._mode = mode  # a string, or a callable so the UI can switch the autonomy mode while the agent runs
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

    @property
    def mode(self) -> str:
        return self._mode() if callable(self._mode) else self._mode

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
        return request_approval(self.emit, self.approver, self.agent.id, kind, summary, details)

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
        return self._store(p, content)

    def _implement(self, a: Action) -> ToolResult:
        """Replace the body of one function in a Python file; the rest of the file is untouched."""
        p = self.paths.resolve_write(a.path or "")
        if not p.is_file():
            return _fail(f"{a.path} does not exist; create it with write_file first")
        new_source, problem = replace_function_body(p.read_text(encoding="utf-8", errors="replace"), a.function or "", a.content or "")
        if problem:
            return _fail(problem)
        try:
            tree = ast.parse(new_source)
        except SyntaxError as e:  # never leave a half-broken file behind: later `implement` calls could not even parse it
            return _fail(f"not applied: your body makes the file invalid Python (line {e.lineno}: {e.msg}). Send only valid Python lines for the inside of "
                         f"{a.function}; SQL goes in a string passed to conn.execute(...).")
        fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == a.function), None)
        if fn is not None and _must_return(fn) and not any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(fn)):
            return _fail(f"not applied: {a.function} must return its result (a route returns the response, a database function returns the row, list or flag) "
                         "but your body has no `return <value>`. Add it.")
        missing = undefined_calls(tree)
        if missing:
            alias = next((x.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "database" for x in n.names if x.asname), None)
            hint = (f" The database functions are called through the module alias: write `{alias}.{missing[0]}(...)`, not `{missing[0]}(...)`." if alias else
                    " Define or import it first, or call the function that exists.")
            return _fail(f"not applied: {', '.join(f'`{m}(...)`' for m in missing)} is called but not defined or imported in this file (it would raise NameError).{hint}")
        unknown, params = undefined_variables(tree, a.function or "")
        if unknown:
            return _fail(f"not applied: {', '.join(f'`{u}`' for u in unknown)} is not defined inside {a.function} (it would raise NameError). "
                         f"Use only its parameters ({', '.join(params) or 'none'}), names you assign yourself and what the file imports. "
                         f"For example the path parameter of a route is named in its signature and in the `body:` hints, nothing else.")
        return self._store(p, new_source, f"implemented {a.function} in")

    def _store(self, p: Path, content: str, verb: str = "wrote") -> ToolResult:
        rel = self.paths.rel(p)
        if rel.endswith(".py") and _UNSAFE_CALL.search(content):
            return _fail("refused: eval()/exec() would run user-supplied text as code (injection risk). Use an if/elif chain or a dict of "
                         "functions, e.g. {'add': operator.add, 'subtract': operator.sub}[name](a, b).", decision="deny")
        if self.mode == "assisted" and not self._approve("write", f"write {rel}", {"path": rel, "bytes": len(content)}):
            return _fail("write was not approved", decision="denied_by_human")
        old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        if p.exists() and old == content:
            return _fail(f"no change: {rel} already has exactly this content, so nothing was fixed. Look at the failure again "
                         "and change the specific lines it points to.", decision="allow", unchanged=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        diff = "".join(
            difflib.unified_diff(old.splitlines(True), content.splitlines(True), f"a/{rel}", f"b/{rel}")
        )
        if rel not in self.files_touched:
            self.files_touched.append(rel)
        self.emit("file_changed", agent=self.agent.id, path=rel, diff=diff, created=not old)
        data = {"decision": "approved"} if self.mode == "assisted" else {}
        if rel.endswith(".py"):
            problem = _syntax_problem(rel, content)
            if problem:
                return ToolResult(False, problem.replace("wrote ", f"{verb} ", 1), {**data, "wrote": True})
        if rel.endswith(".js"):
            problem = _js_problem(rel, p)
            if problem:
                return ToolResult(False, problem.replace("wrote ", f"{verb} ", 1), {**data, "wrote": True})
        return ToolResult(True, f"{verb} {rel} ({len(content.splitlines())} lines)", data)

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
        final = _FINAL_LINE.findall(r.output)
        summary = final[-1] if final else next((l for l in reversed(r.output.splitlines()) if re.search(r"passed|failed|no tests", l)), "")
        r.ok = passed
        r.data.update(passed=passed, failed=sorted(failed), signature=signature, summary=summary.strip(" ="),
                      digest="" if passed else failure_digest(r.output))
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
        if answer is None and self.mode == "autonomous":
            # Autonomous mode means nobody is watching: pausing the task would only end it. Keep working within the area you own.
            return _fail("No human is available in Autonomous mode, so decide yourself. You cannot edit files outside your own area: if you need a change "
                         "there, use send_message to its owner, or adapt your own code to what already exists (read the other file to see its exact names).")
        if answer is None:
            return ToolResult(False, "waiting for a human answer", {"question": q}, needs_human=True)
        return ToolResult(True, f"human answered: {answer}", {"question": q})

    def _finish(self, a: Action) -> ToolResult:
        return ToolResult(True, a.summary or "", finished=True)
