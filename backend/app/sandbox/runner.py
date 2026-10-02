"""Runs an already-approved command: no shell, cwd pinned, timeout, capped output, tree kill."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SECRET_ENV = ("GEMINI_API_KEY", "OPENAI_COMPAT_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY")


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    timed_out: bool
    truncated: bool
    duration: float


def resolve_argv(tokens: list[str]) -> list[str]:
    """Map the allowlisted program names to the interpreter Q itself runs on."""
    prog = os.path.basename(tokens[0]).casefold().removesuffix(".exe")
    if prog in ("python", "python3", "py"):
        return [sys.executable, *tokens[1:]]
    if prog == "pytest":
        return [sys.executable, "-m", "pytest", *tokens[1:]]
    if prog == "pip":
        return [sys.executable, "-m", "pip", *tokens[1:]]
    found = shutil.which(tokens[0])  # resolves npm -> npm.cmd on Windows
    return [found or tokens[0], *tokens[1:]]


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra or {})
    return env


def kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    import psutil

    try:
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            child.kill()
        proc.kill()
    except psutil.NoSuchProcess:
        pass


def run_command(
    argv: list[str],
    cwd: Path | str,
    timeout: float = 60,
    max_output: int = 20_000,
    on_output: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> RunResult:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    start = time.time()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env or clean_env(),
            creationflags=flags,
        )
    except OSError as e:
        return RunResult(None, f"could not start command: {e.strerror or e}", False, False, 0.0)

    chunks: list[str] = []
    size = 0
    truncated = False

    def pump() -> None:
        nonlocal size, truncated
        assert proc.stdout is not None
        for raw in iter(lambda: proc.stdout.readline(), b""):  # type: ignore[union-attr]
            line = raw.decode("utf-8", errors="replace")
            if on_output:
                on_output(line)
            if size < max_output:
                chunks.append(line[: max_output - size])
                size += len(line)
            else:
                truncated = True

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        proc.wait()
    reader.join(timeout=5)
    out = "".join(chunks)
    if truncated or size > max_output:
        truncated = True
        out += f"\n[output truncated at {max_output} characters]"
    if timed_out:
        out += f"\n[killed: timed out after {timeout:g}s]"
    return RunResult(None if timed_out else proc.returncode, out, timed_out, truncated, time.time() - start)
