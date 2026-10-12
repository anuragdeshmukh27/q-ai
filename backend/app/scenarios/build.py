"""A scenario session: a finished app with a planted problem, one task for the person, and the AI team on call.

`ScenarioBuild` is an Orchestrator that skips design and planning (no model is asked anything): it copies the scenario's seed into a new project, hands one task to the
person's role with `add_human_task`, and then runs the same scheduler as every Simulation build, so Submit means what it meant in step 2: all tests, the Reviewer (at most two
send-backs), the scope check, the Integrator's merge. On top of that it keeps the session log, Priya's guide and the incident channel (see sessionlog, guide, director).
Nothing here changes how an ordinary build runs.
"""
from __future__ import annotations

import difflib
import shutil
import time
from pathlib import Path
from typing import Callable

from ..config import WORKSPACE
from ..humanide import search_worktree
from ..integrator import Integrator
from ..memory import MessageBus, ProjectMemory
from ..orchestrator import Orchestrator
from ..project import git, slugify
from ..repo import Repo
from ..schemas import ArchitectOutput
from .debrief import Debrief
from .director import Director, Replier
from .guide import GuideTracker, guide_markdown
from .loader import Scenario
from .reports import History
from .rubric import Rubric
from .sessionlog import SessionLog
from .wording import Wordsmith


REGRESSION_TESTS = "tests/regression/**"  # where the learner's own tests go (the folder is in the seed)


def diff_stats(before: str, after: str) -> tuple[int, int]:
    """(lines added, lines removed) going from `before` to `after`."""
    added = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


class ScenarioBuild(Orchestrator):
    STAGES = ("setup", "tasks", "verify")

    def __init__(self, scenario: Scenario, registry, llm, bus=None, clock: Callable[[], float] = time.monotonic, replier: Replier | None = None,
                 rubric: Rubric | None = None, wordsmith: Wordsmith | None = None, attempt: int = 1, debrief_pace: float = 3.5, **kw):
        kw.update(mode="simulation", human_roles=(scenario.role,), qa=False, polish=False)  # QA's phase and the polish task belong to a build from a goal
        super().__init__(scenario.goal, registry, llm, bus, **kw)
        self.scenario = scenario
        self.design = ArchitectOutput(preset=scenario.seed.preset, architecture="An existing app", endpoints=[])  # only its preset (the test and run commands) is used
        self.log = SessionLog(clock, self.emit)
        self.guide = GuideTracker(scenario, self.emit, self.log.events)
        self.director = Director(scenario, self.log, self.emit, self.agents, replier)
        self.log.subscribe(self.guide.on_event)
        self.log.subscribe(self.director.on_log_event)
        self.bus.subscribe(self._on_event)
        self.attempt = attempt
        self.history = History(self.base or WORKSPACE, scenario.id)
        self.debrief = Debrief(self, rubric, wordsmith or Wordsmith(), self.history, attempt, debrief_pace) if rubric is not None else None  # no rubric, no debrief
        self._trigger = "ide"  # what started the test run that is going: the IDE's Run tests, or Submit

    # -- the pipeline -----------------------------------------------------------------
    def run(self):
        self.emit("scenario_started", scenario=self.scenario.id, title=self.scenario.title, role=self.scenario.role, minutes=self.scenario.minutes,
                  channel={"id": self.scenario.channel.id, "name": self.scenario.channel.name}, teammates=list(self.scenario.characters), started_at=self.log.started_at, attempt=self.attempt,
                  scoring=self.debrief.rubric.scoring() if self.debrief else [])
        self.log.add("session_started", scenario=self.scenario.id, role=self.scenario.role)
        self.director.start()
        return super().run()

    def _pipeline(self, start: str = "setup") -> None:
        steps = {"setup": self._setup, "tasks": self._execute_tasks, "verify": self._verify}
        for name in self.STAGES[self.STAGES.index(start):]:
            if self.stopped.is_set():
                break
            self.stage = name
            steps[name]()

    def _setup(self) -> None:
        """The project is the seed, committed as it is; the person's task is the only task."""
        s = self.scenario
        base = self.base or WORKSPACE
        base.mkdir(parents=True, exist_ok=True)
        slug = slugify(s.id)
        root, n = base / slug, 1
        while root.exists():
            n += 1
            root = base / f"{slug}-{n}"
        shutil.copytree(s.seed_dir, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.db", ".worktrees"))
        (root / ".q").mkdir(exist_ok=True)
        (root / ".q" / "goal.md").write_text(f"# Goal\n\n{s.goal}\n", encoding="utf-8", newline="\n")
        (root / ".q" / "decisions.md").write_text(f"# Decisions\n\n- Scenario: {s.id} ({s.title})\n", encoding="utf-8", newline="\n")
        git(root, "init", "-b", "main")
        for k, v in (("user.name", "Q"), ("user.email", "q@localhost"), ("commit.gpgsign", "false"), ("core.autocrlf", "false")):  # LF everywhere: the person's editor and the reference patch agree
            git(root, "config", k, v)
        git(root, "add", "-A")
        git(root, "commit", "-m", f"Seed: {s.title}")
        self.root = root
        self.repo = Repo(root)
        self.memory = ProjectMemory(root)
        self.messages = MessageBus(self.memory, self.emit)
        self.emit("project_created", slug=root.name, goal=s.goal, preset=s.seed.preset, path=str(root))
        ia = self.agents["integrator"]
        self.integrator = Integrator(ia, self.repo, self.llm, self._model(ia).id, self.emit, lambda: self.mode, self.approver)
        self.log.attach(root / ".q" / "session")
        self.add_human_task(s.role, s.task.title, s.task.files, s.task.acceptance_tests)
        self._commit("[q] scenario task")

    def _engineer(self, owner: str):
        """The learner may also add tests of their own for the incident (a regression test); the generated and QA's tests stay read-only."""
        a = super()._engineer(owner)
        if owner == self.scenario.role:
            a = a.model_copy(update={"owned_paths": [*a.owned_paths, REGRESSION_TESTS]})
        return a

    # -- what a person's task needs here ------------------------------------------------------
    def _scaffold(self, t: dict, agent, wt: Path):
        return None  # the app is finished: there is no stub to generate and no contract to generate tests from

    def _human_doc(self, t: dict, wt: Path, stub, tests: list[str]) -> str:
        base = super()._human_doc(t, wt, stub, tests)
        head = [f"# {t['id']}: {t['title']}", "", self.scenario.brief, "", "## What to do", *[f"- {c}" for c in t["acceptance"]],
                "- add a regression test in `tests/regression/` (a file named `test_regression_<what>.py`) that fails on the code as it is now and passes after your fix",
                "- the whole test suite passes: `python -m pytest -q`", ""]
        return "\n".join(head) + "\n" + base[base.index("## Files you may edit"):]

    def _start_human(self, t: dict):
        fut = super()._start_human(t)
        assert self.memory
        self.memory.write(f"guides/{t['id']}.md", guide_markdown(self.scenario, t["id"], t["title"]))
        self.guide.start(t["id"])
        return fut

    # -- the person's actions go to the session log -----------------------------------------------
    def _on_event(self, e: dict) -> None:
        if e["type"] == "human_test_started":
            self.log.add("test_run", task=e["task"], trigger=self._trigger)
        elif e["type"] == "human_test_result":
            self.log.add("test_result", task=e["task"], ok=bool(e["ok"]), passed=e["passed"], failed=[x["id"] for x in e["tests"] if x["outcome"] == "failed"], summary=e["summary"], trigger=self._trigger)

    def ide_read(self, role: str, rel: str, auto: bool = False) -> dict:
        """`auto`: the IDE opened the file by itself (its first file); that is logged, but it is not something the learner chose, so the guide does not count it."""
        out = super().ide_read(role, rel)
        self.log.add("file_opened", role=role, path=out["path"], **({"auto": True} if auto else {}))
        return out

    def ide_write(self, role: str, rel: str, content: str) -> dict:
        wt = self._ide_worktree(role)
        created = not (wt / rel).is_file()
        out = super().ide_write(role, rel, content)  # refuses a path that is not yours before anything is logged
        added, removed = diff_stats(self._starting_text(rel), content)  # against the file as the incident started: a file you created is all added, and saving it again never adds more
        self.log.add("file_saved", role=role, path=out["path"], added=added, removed=removed, size=out["size"], created=created)
        return out

    def _starting_text(self, rel: str) -> str:
        """The file as it was in the seed ("" for a file the learner created)."""
        seed = self.scenario.seed_dir.resolve()
        target = (seed / rel).resolve()
        try:
            target.relative_to(seed)
            return target.read_text(encoding="utf-8") if target.is_file() else ""
        except (ValueError, OSError):
            return ""

    def ide_search(self, role: str, query: str) -> dict:
        """A project-wide search: read-only files included. Every search is logged with its query and how much it found (the debrief can use that)."""
        out = search_worktree(self._ide_worktree(role), query)
        self.log.add("search", role=role, query=out["query"], matches=out["matches"], files=out["files"])
        return out

    def submit_human_task(self, tid: str) -> dict:
        with self._human_lock:
            ht = self._humans.get(tid)
            open_ = ht is not None and not ht.future.done() and not ht.submitting and ht.run is None
        if open_:
            self.log.add("submit", task=tid)
        self._trigger = "submit"
        try:
            result = super().submit_human_task(tid)
        finally:
            self._trigger = "ide"
        self.log.add("submit_result", task=tid, ok=result["ok"], stage=result["stage"], summary=result["summary"], failed=result.get("failed", []), review_items=len(result.get("items", [])))
        return result

    # -- the end -------------------------------------------------------------------------
    def stop(self) -> None:
        self.director.stop()
        if self.debrief:
            self.debrief.stop()
        super().stop()

    def _finish(self, seconds: float):
        res = super()._finish(seconds)
        self.log.add("session_finished", ok=res.ok)
        self.director.closed = True  # the thanks that are still waiting for their delay are posted; nobody nudges any more
        if self.debrief and res.ok and self.log.first_accepted():
            self.debrief.start()  # the team walks to the meeting room; the report arrives as `debrief_report`
        return res
