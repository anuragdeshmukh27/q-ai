"""Command policy: decides whether an agent's command may run.

Verdict kinds:
  DENY  hard-denied; blocked in every autonomy mode
  ASK   needs human approval (installs, programs not on the allowlist)
  ALLOW on the allowlist

Commands are never run through a shell (see runner.py), so shell operators are
rejected outright instead of being interpreted.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ALLOW, ASK, DENY = "allow", "ask", "deny"
MODES = ("assisted", "supervised", "autonomous")

HARD_DENY_PROGRAMS = {
    "rm", "del", "erase", "rmdir", "rd", "format", "sudo", "su", "runas", "reg", "regedit",
    "curl", "wget", "invoke-webrequest", "iwr", "certutil", "bitsadmin", "shutdown",
    "powershell", "pwsh", "cmd", "bash", "sh", "zsh", "wsl", "taskkill", "chmod", "chown",
    "mklink", "takeown", "icacls", "net", "netsh", "schtasks", "sc", "ssh", "scp", "ftp",
    "telnet", "nc", "ncat", "diskpart", "cipher", "wmic", "mshta", "rundll32", "regsvr32",
}
PYTHON_NAMES = {"python", "python3", "py"}
PYTHON_SAFE_FLAGS = {"-u", "-B", "-O", "-OO", "-q", "-s", "-S", "-E", "-I"}
PYTHON_MODULES = {"pytest", "uvicorn", "unittest", "compileall"}
PIP_ASK = {"install", "uninstall"}
PIP_READ = {"list", "freeze", "show", "check"}
GIT_SUBCOMMANDS = {"status", "diff", "add", "commit", "log"}
NPM_INSTALL = {"install", "i", "add", "ci"}
_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")

_OPT_VALUE = re.compile(r"^--?[\w-]+=")
_DRIVE = re.compile(r"^[A-Za-z]:")
_PARENT = re.compile(r"(^|[\\/])\.\.($|[\\/])")


@dataclass
class Verdict:
    kind: str
    reason: str = ""
    argv: list[str] = field(default_factory=list)


def _deny(reason: str) -> Verdict:
    return Verdict(DENY, reason)


def tokenize(cmd: str) -> list[str]:
    """Split on whitespace, honouring quotes. Raises ValueError on shell syntax."""
    tokens: list[str] = []
    cur: list[str] = []
    in_tok = False
    quote = ""
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == quote:
                quote = ""
            else:
                cur.append(c)
        elif c in "\"'":
            quote, in_tok = c, True
        elif c in "&|;<>`\r\n":
            raise ValueError(f"shell operator {c!r} is not allowed; run one command at a time")
        elif c == "$" and cmd[i + 1 : i + 2] == "(":
            raise ValueError("command substitution is not allowed")
        elif c.isspace():
            if in_tok:
                tokens.append("".join(cur))
                cur, in_tok = [], False
        else:
            cur.append(c)
            in_tok = True
        i += 1
    if quote:
        raise ValueError("unterminated quote")
    if in_tok:
        tokens.append("".join(cur))
    return tokens


def _program(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1].casefold()
    for s in _SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return name


class CommandPolicy:
    def __init__(self, root: Path | str, extra_allowed: list[str] | None = None):
        self.root = Path(os.path.realpath(root))
        self._extra = [p for p in (self._prefix(c) for c in (extra_allowed or [])) if p]

    @staticmethod
    def _prefix(cmd: str) -> list[str]:
        try:
            toks = tokenize(cmd)
        except ValueError:
            return []
        out = []
        for t in toks:
            if t.startswith("--") or "{" in t:
                break
            out.append(t.casefold())
        return out

    # -- public ---------------------------------------------------------------------
    def check(self, cmd: str) -> Verdict:
        if not cmd or not cmd.strip():
            return _deny("empty command")
        try:
            tokens = tokenize(cmd)
        except ValueError as e:
            return _deny(str(e))
        prog = _program(tokens[0])
        if prog in HARD_DENY_PROGRAMS:
            return _deny(f"{prog} is hard-denied")
        bad = self._check_paths(tokens)
        if bad:
            return _deny(bad)
        v = self._classify(prog, tokens)
        v.argv = tokens
        return v

    # -- internals ------------------------------------------------------------------
    def _check_paths(self, tokens: list[str]) -> str:
        for t in tokens:
            v = _OPT_VALUE.sub("", t).split("::")[0]
            if "://" in v:
                continue
            rooted = bool(_DRIVE.match(v)) or v.startswith(("/", "\\", "~"))
            if any(c.isspace() for c in v) and not rooted:
                continue  # free text such as a commit message
            if not (rooted or "/" in v or "\\" in v or _PARENT.search(v)):
                continue
            if v.startswith("~"):
                return f"path {t!r} is outside the project"
            real = os.path.realpath(v if (os.path.isabs(v) or rooted) else os.path.join(self.root, v))
            r, p = os.path.normcase(str(self.root)), os.path.normcase(real)
            try:
                inside = os.path.commonpath([p, r]) == r
            except ValueError:
                inside = False
            if not inside:
                return f"path {t!r} is outside the project"
        return ""

    def _classify(self, prog: str, tokens: list[str]) -> Verdict:
        args = tokens[1:]
        if prog in PYTHON_NAMES:
            return self._python(args)
        if prog == "pytest":
            return Verdict(ALLOW)
        if prog == "pip":
            return self._pip(args)
        if prog == "git":
            return self._git(args)
        if prog == "npm" and args and args[0] in NPM_INSTALL:
            return Verdict(ASK, "npm install needs approval")
        low = [t.casefold() for t in tokens]
        if any(low[: len(p)] == p for p in self._extra):
            return Verdict(ALLOW)
        return Verdict(ASK, f"{prog} is not on the allowlist")

    def _python(self, args: list[str]) -> Verdict:
        while args and args[0] in PYTHON_SAFE_FLAGS:
            args = args[1:]
        if not args:
            return _deny("interactive python is not allowed")
        if args[0] == "-m":
            if len(args) < 2:
                return _deny("python -m needs a module")
            mod = args[1].casefold()
            if mod == "pip":
                return self._pip(args[2:])
            if mod in PYTHON_MODULES:
                return Verdict(ALLOW)
            return _deny(f"python -m {mod} is not allowed")
        if args[0].startswith("-"):
            return _deny(f"python option {args[0]} is not allowed (write code to a file and run it)")
        if not args[0].casefold().endswith(".py"):
            return _deny("python can only run .py files inside the project")
        return Verdict(ALLOW)

    @staticmethod
    def _pip(args: list[str]) -> Verdict:
        sub = args[0].casefold() if args else ""
        if sub in PIP_ASK:
            return Verdict(ASK, f"pip {sub} needs approval")
        if sub in PIP_READ:
            return Verdict(ALLOW)
        return _deny(f"pip {sub} is not allowed")

    @staticmethod
    def _git(args: list[str]) -> Verdict:
        if not args or args[0].startswith("-"):
            return _deny("git options before the subcommand are not allowed")
        sub = args[0].casefold()
        if sub not in GIT_SUBCOMMANDS:
            return _deny(f"git {sub} is not allowed (status, diff, add, commit, log only)")
        if sub == "commit" and any(a in ("--no-verify", "-n") for a in args[1:]):
            return _deny("git commit --no-verify is not allowed")
        return Verdict(ALLOW)


def apply_mode(verdict: Verdict, mode: str) -> str:
    """Turn a policy verdict into the final decision for an autonomy mode."""
    if mode not in MODES:
        raise ValueError(f"unknown autonomy mode: {mode}")
    if verdict.kind == DENY:
        return DENY
    if mode == "autonomous":
        return ALLOW
    if mode == "assisted":
        return ASK
    return verdict.kind
