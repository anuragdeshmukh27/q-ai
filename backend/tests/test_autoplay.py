"""Autoplay ("Watch a run") through the API: a scripted learner plays the real scenario with the LLM stubbed. The score, the Director, the Reviewer, the scope check and the debrief are the real ones,
so the exact scores below are the rubric's own. The session clock is a virtual one that only the script moves (a whole incident, with the nudge after five quiet minutes, in seconds of real time)."""
import re
import threading
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.registry import ModelRegistry
from app.scenarios.autoplay import ScaledClock, VirtualClock
from app.scenarios.debrief import Debrief
from app.scenarios.reports import History
from app.session import Session, SessionManager

from api_helpers import make_settings, wait_for
from scenario_helpers import ScenarioLLM

pytestmark = pytest.mark.slow  # whole module is slow (see backend/tests/conftest.py)

ID = "opd-bookings-down"
CRITERIA = ["communication", "diagnosis", "fix_quality", "testing", "ownership"]


def make(tmp_path, llm=None, virtual=True):
    settings = make_settings(tmp_path)
    settings.autoplay_virtual = virtual
    llm = llm or ScenarioLLM("Karan: slot_time became slot_at in migration 0007.")
    mgr = SessionManager(settings, ModelRegistry.load(env={}), llm_factory=lambda registry, observer: llm)
    return TestClient(create_app(settings, mgr)), mgr, settings


def events(s, type_):
    return [e for e in s.bus.history if e["type"] == type_]


def watch(client, mgr, variant, speed=1):
    r = client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": variant, "speed": speed})
    assert r.status_code == 201, r.text
    return r.json()["id"], mgr.get(r.json()["id"])


def play(client, mgr, variant):
    pid, s = watch(client, mgr, variant)
    ended = wait_for(lambda: next(iter(events(s, "autoplay_ended")), None), 420, "the run to end")
    assert ended["reason"] == "done", ended
    wait_for(lambda: next(iter(events(s, "debrief_ended")), None), 60, "the debrief")
    return pid, s, client.get(f"/api/projects/{pid}/report").json()


@pytest.fixture
def world(tmp_path):
    client, mgr, settings = make(tmp_path)
    yield client, mgr, settings
    mgr.shutdown()


def test_the_strong_run_scores_full_marks_and_the_screen_has_every_event_it_needs(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "strong")
    assert rep["total"] == 100 and [c["score"] for c in rep["criteria"]] == [4, 4, 4, 4, 4]
    assert rep["fairness"]["dropped"] == [] and rep["fairness"]["points"] == 20 and all(r["verified"] for r in rep["rows"])
    assert rep["kind"] == "demo" and rep["variant"] == "strong" and rep["attempt"] == 1
    types = [e["type"] for e in s.bus.history]
    started = events(s, "autoplay_started")[0]
    assert started["variant"] == "strong" and started["total"] == len(started["labels"]) and "morning clinic opens at 09:00" in started["doc"] and started["tree"]["ready"]
    assert types.index("autoplay_started") < types.index("autoplay_step") < types.index("human_test_result") < types.index("human_submit_result")
    opened = [e["path"] for e in events(s, "autoplay_open_file")]
    assert opened == ["backend/api/appointments.py", "database/migrations/0007_rename_slot_time_to_slot_at.sql", "backend/api/doctors.py"]
    assert [e["writable"] for e in events(s, "autoplay_open_file")] == [True, False, True]  # the migration is read-only for the learner
    assert events(s, "autoplay_search")[0]["q"] == "slot_time" and events(s, "autoplay_search")[0]["result"]["matches"] >= 6
    edits = events(s, "autoplay_edit")
    assert [e["path"] for e in edits] == ["tests/regression/test_regression_slot_at.py", "backend/api/appointments.py", "backend/api/doctors.py"]
    assert all("slot_time" not in e["content"] for e in edits[1:]) and "slot_at" in edits[1]["content"]
    assert [e["focus"] for e in events(s, "autoplay_step")][-1] == "debrief" and {e["focus"] for e in events(s, "autoplay_step")} == {"ide", "chat", "debrief"}
    assert [m["text"][:3] for m in events(s, "channel_message") if m.get("source") == "learner"] == ["On ", "Upd", "Fix"]
    assert events(s, "autoplay_ended")[0]["reason"] == "done" and events(s, "scenario_started")[0]["kind"] == "demo"
    # the evidence is the session log's, written by the same calls a person makes: the opens are deliberate (not "auto"), the saves are logged
    info = client.get(f"/api/projects/{pid}/session").json()
    kinds = [e["kind"] for e in info["events"]]
    assert kinds.count("file_saved") == 3 and kinds.count("search") == 1 and info["summary"]["hints"] <= 1
    assert not any(e.get("auto") for e in info["events"] if e["kind"] == "file_opened")


def test_the_weak_run_scores_exactly_thirty_and_the_gaps_are_the_ones_it_was_given(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "weak")
    assert [(c["id"], c["score"]) for c in rep["criteria"]] == [("communication", 0), ("diagnosis", 0), ("fix_quality", 4), ("testing", 0), ("ownership", 2)]
    assert rep["total"] == 30 and rep["kind"] == "demo" and rep["variant"] == "weak"
    held = {r["rule"] for r in rep["rows"] if r["kind"] == "strength"}
    assert held == {"old_name_gone", "suite_green_on_main", "small_change", "review_clean", "within_time_box", "no_scope_rejection"}
    gaps = {r["rule"] for r in rep["rows"] if r["kind"] == "gap"}
    assert {"first_update", "no_nudges", "reproduced_first", "no_red_submit", "regression_test_added", "few_hints"} <= gaps
    log = client.get(f"/api/projects/{pid}/session").json()["events"]
    kinds = [e["kind"] for e in log]
    first_save = kinds.index("file_saved")
    assert "test_run" not in kinds[:first_save] and not any(e["kind"] == "message_posted" for e in log[:first_save])  # edits first, no tests, no update
    assert any(e["kind"] == "team_message" and e.get("ref") == "lead-nudge" for e in log)  # the team had to ask
    red = [e for e in log if e["kind"] == "submit_result" and not e["ok"]]
    assert len(red) == 1 and red[0]["stage"] == "tests" and log[-1]["kind"] == "session_finished"
    assert [e["path"] for e in events(s, "autoplay_edit")] == ["backend/api/appointments.py", "backend/api/doctors.py"]


def test_the_two_runs_differ_only_by_what_the_learner_did(world):
    client, mgr, settings = world
    _, _, strong = play(client, mgr, "strong")
    _, _, weak = play(client, mgr, "weak")
    assert strong["total"] - weak["total"] == 70 and strong["rubric"] == weak["rubric"]


def test_a_demo_never_counts_in_the_learners_attempts(world):
    client, mgr, settings = world
    play(client, mgr, "strong")
    play(client, mgr, "weak")
    assert History(settings.workspace, ID).attempts() == [] and History(settings.workspace, ID).next_number() == 1
    demos = History(settings.workspace, ID, "demo").attempts()
    assert [(a["attempt"], a["total"], a["variant"]) for a in demos] == [(1, 100, "strong"), (2, 30, "weak")]
    started = client.post(f"/api/scenarios/{ID}/start")
    assert started.status_code == 201 and started.json()["scenario"]["attempt"] == 1 and started.json()["scenario"]["kind"] == "learner"
    mgr.get(started.json()["id"]).orch.stop()


def test_a_demo_report_is_marked_demo_in_its_markdown_and_its_files(world):
    client, mgr, settings = world
    pid, s, rep = play(client, mgr, "strong")
    md = client.get(f"/api/projects/{pid}/report", params={"format": "md"}).text
    assert md.startswith("# Debrief: Production incident") and "**Demo run, strong (attempt 1 of the demos): 100/100**" in md
    assert [a["kind"] for a in rep["attempts"]] == ["demo"]


def test_stop_in_the_middle_ends_the_script_the_session_and_the_debrief_and_cleans_up(world):
    client, mgr, settings = world
    pid, s = watch(client, mgr, "strong")
    wait_for(lambda: events(s, "autoplay_edit") and events(s, "autoplay_edit")[0], 240, "the first edit")
    root = s.root
    assert root and root.is_dir()
    r = client.post(f"/api/projects/{pid}/autoplay/stop")
    assert r.status_code == 200 and r.json()["stopped"] is True
    assert not s.autoplay.alive() and s.autoplay.state == "stopped"
    ended = events(s, "autoplay_ended")
    assert [e["reason"] for e in ended] == ["stopped"]
    assert not events(s, "debrief_started") and not events(s, "debrief_report") and client.get(f"/api/projects/{pid}/report").status_code == 404
    assert History(settings.workspace, ID).attempts() == [] and History(settings.workspace, ID, "demo").attempts() == []
    assert not root.exists(), "the demo's project folder is removed"
    assert not [t for t in threading.enumerate() if t.name.startswith(("autoplay-", "scenario-", "incident-clock", "debrief")) and t.is_alive()]
    nxt = client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "weak"})  # the next run can start at once
    assert nxt.status_code == 201
    client.post(f"/api/projects/{nxt.json()['id']}/autoplay/stop")


LIVE_THREADS = ("autoplay-", "scenario-", "incident-clock", "debrief", "ide-tests-")


def _live_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.is_alive() and t.name.startswith(LIVE_THREADS)]


def _children() -> list[int]:
    """Every process this one started and has not seen end: a test run, the demo's own app."""
    return [p.pid for p in psutil.Process().children(recursive=True) if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]


def _catch(monkeypatch, cls, name: str, torn_down, pending: bool):
    """Wrap `cls.name` so the test knows when an autoplay run is inside it. `pending`: the call is held until Stop has torn the session down and only then made, which is
    a step that was in flight when Stop arrived (the real call, against a stopped build); otherwise it is made at once and Stop arrives while it works."""
    orig = getattr(cls, name)
    entered = threading.Event()

    def wrapper(self, *a, **k):
        first = not entered.is_set()
        entered.set()
        if first and pending:
            end = time.time() + 60
            while not torn_down(self) and time.time() < end:
                time.sleep(0.02)
        return orig(self, *a, **k)

    monkeypatch.setattr(cls, name, wrapper)
    return entered


STOP_STEPS = [
    ("edit", Session, "ide_write", lambda s: s.orch.stopped.is_set(), True),
    ("test run, called as Stop arrives", Session, "ide_run_tests", lambda s: s.orch.stopped.is_set(), True),
    ("test run, the suite is running", None, None, None, False),
    ("submit, called as Stop arrives", Session, "submit_task", lambda s: s.orch.stopped.is_set(), True),
    ("submit, the check is running", Session, "submit_task", None, False),
    ("debrief, the meeting", None, None, None, False),
    ("debrief, the suite is re-run", Debrief, "measure", lambda d: d._halted.is_set(), True),
]


@pytest.mark.parametrize("step", STOP_STEPS, ids=[s[0] for s in STOP_STEPS])
def test_stop_during_any_kind_of_step_ends_as_stopped_and_leaves_nothing(tmp_path, monkeypatch, step):
    """Whatever the script was doing when Stop came (an edit, a test run, a submit, the debrief), the run ends as `stopped` (never `error`), and no thread, test process or folder is left."""
    label, cls, name, torn_down, pending = step
    client, mgr, settings = make(tmp_path)
    settings.debrief_pace = 30.0 if label == "debrief, the meeting" else 0.0  # the judges speak 30 s apart: Stop comes in the middle of the meeting
    try:
        caught = _catch(monkeypatch, cls, name, torn_down, pending) if cls else None
        before = set(_children())
        pid, s = watch(client, mgr, "strong")
        if label == "test run, the suite is running":
            wait_for(lambda: events(s, "human_test_started"), 240, "the first test run")
        elif label == "debrief, the meeting":
            wait_for(lambda: events(s, "debrief_started"), 400, "the meeting")
        else:
            wait_for(lambda: caught.is_set(), 400, f"the run to be in {name}")
        root = s.root
        assert root and root.is_dir()
        r = client.post(f"/api/projects/{pid}/autoplay/stop")
        assert r.status_code == 200 and r.json() == {"stopped": True, "state": "stopped"}, r.text
        runner = s.autoplay
        assert not runner.alive() and runner.state == "stopped", runner.error
        ended = events(s, "autoplay_ended")
        assert [e["reason"] for e in ended] == ["stopped"] and "error" not in ended[0] and runner.error == ""
        assert not events(s, "debrief_report") and client.get(f"/api/projects/{pid}/report").status_code == 404
        assert History(settings.workspace, ID).attempts() == [] and History(settings.workspace, ID, "demo").attempts() == []
        assert not root.exists(), "the demo's project folder is removed"
        assert _live_threads() == []
        assert [p for p in _children() if p not in before] == [], "a test run or the demo's app is still going"
    finally:
        mgr.shutdown()


def test_an_exception_after_stop_was_asked_is_a_stop_and_one_before_it_is_an_error():
    """The runner's own rule, without any timing: a step that raises because Stop has just torn the build down (a closed task, a missing folder) is not a failure of the script."""
    from types import SimpleNamespace
    from app.scenarios.autoplay import AutoplayRunner
    from app.scenarios.loader import load_scenario

    def runner() -> AutoplayRunner:
        bus = SimpleNamespace(history=[{"type": "human_task_assigned", "task": "T1"}])
        bus.emit = lambda type_, **f: bus.history.append({"type": type_, **f})
        session = SimpleNamespace(id="x", scenario=load_scenario(ID), bus=bus, _stop=threading.Event(), orch=SimpleNamespace(),
                                  ide_tree=lambda role: {}, task_doc=lambda t: "")
        return AutoplayRunner(session, "strong", VirtualClock())

    a = runner()

    def closed_by_stop():
        a._stop.set()
        raise RuntimeError("You have no open task for this role: nothing can be edited now.")

    a.steps = [("edit", "ide", closed_by_stop)]
    a._run()
    assert a.state == "stopped" and a.error == "" and a.session.bus.history[-1] == {"type": "autoplay_ended", "reason": "stopped"}

    b = runner()
    b.session._stop.set()  # the session ended (its Stop, or the manager's shutdown) while the step was running

    def closed_by_session():
        raise RuntimeError("the folder is gone")

    b.steps = [("edit", "ide", closed_by_session)]
    b._run()
    assert b.state == "stopped" and b.error == ""

    c = runner()

    def broken():
        raise RuntimeError("the submit was not accepted")

    c.steps = [("submit", "ide", broken)]
    c._run()
    assert c.state == "error" and c.error == "RuntimeError: the submit was not accepted"
    assert c.session.bus.history[-1] == {"type": "autoplay_ended", "reason": "error", "error": c.error}


def test_a_test_run_killed_before_it_started_never_starts(tmp_path):
    """Stop can reach a SuiteRun between its creation and the moment its process exists: it must not run the suite then."""
    from app.humanide import SuiteRun
    (tmp_path / "test_x.py").write_text("def test_x():\n    open('ran', 'w').close()\n", encoding="utf-8")
    run = SuiteRun(tmp_path, lambda line: None)
    run.kill()
    res = run.run()
    assert res["ok"] is False and res["summary"] == "the test run was stopped" and not (tmp_path / "ran").exists()
    assert run.proc is None or run.proc.poll() is not None


def test_the_speed_switch_and_the_bad_requests(world):
    client, mgr, settings = world
    assert client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "great"}).status_code == 400
    assert client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "strong", "speed": 3}).status_code == 400
    assert client.post(f"/api/scenarios/nope/autoplay", json={"variant": "strong"}).status_code == 404
    pid, s = watch(client, mgr, "weak")
    assert client.post(f"/api/projects/{pid}/autoplay/speed", json={"speed": 2}).json() == {"speed": 2}
    assert client.post(f"/api/projects/{pid}/autoplay/speed", json={"speed": 5}).status_code == 400
    assert events(s, "autoplay_speed")[-1]["speed"] == 2
    assert client.post(f"/api/projects/{pid}/autoplay/stop").status_code == 200
    plain = client.post(f"/api/scenarios/{ID}/start").json()["id"]
    assert client.post(f"/api/projects/{plain}/autoplay/stop").status_code == 409  # a person's session is not an autoplay run
    assert client.post(f"/api/projects/{plain}/autoplay/speed", json={"speed": 2}).status_code == 409
    mgr.get(plain).orch.stop()


# -- the clocks ----------------------------------------------------------------------------------------------------------

def test_the_scaled_clock_integrates_so_a_change_of_speed_never_jumps():
    real = [100.0]
    clock = ScaledClock(speed=1, factor=2, base=lambda: real[0])
    assert clock() == 0 and clock.rate == 2
    real[0] += 10
    assert clock() == 20
    clock.set_speed(2)
    assert clock() == 20 and clock.rate == 4  # no jump at the change
    real[0] += 10
    assert clock() == 60
    clock.set_speed(1)
    real[0] += 5
    assert clock() == 70


def test_the_virtual_clock_moves_only_when_told():
    clock = VirtualClock()
    time.sleep(0.02)
    assert clock() == 0
    clock.advance(5)
    clock.advance(2.5)
    assert clock() == 7.5


def test_autoplay_data_lives_with_the_scenario_and_the_patch_applies():
    from app.scenarios.autoplay import FIX_FILES, reference_fix, regression_test
    seed = Path(__file__).parent.parent / "app" / "scenarios" / ID / "seed"
    fixed = reference_fix({p: (seed / p).read_text(encoding="utf-8") for p in FIX_FILES})
    assert all("slot_time" not in text for text in fixed.values()) and "def test_booking" in regression_test()


def test_a_new_run_does_not_start_while_the_last_debrief_is_still_going(tmp_path):
    client, mgr, settings = make(tmp_path)
    settings.debrief_pace = 4.0  # the judges speak four seconds apart: the debrief takes a while
    try:
        pid, s = watch(client, mgr, "strong")
        wait_for(lambda: events(s, "debrief_started"), 300, "the meeting")
        late = client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "weak"})
        assert late.status_code == 409 and "debrief" in late.json()["detail"]
        assert client.post(f"/api/scenarios/{ID}/start").status_code == 409
        wait_for(lambda: events(s, "debrief_ended"), 120, "the debrief to end")
        wait_for(lambda: events(s, "autoplay_ended"), 30, "the run to end")
        again = client.post(f"/api/scenarios/{ID}/autoplay", json={"variant": "weak"})
        assert again.status_code == 201  # and the demo numbering went on from the finished one
        assert History(settings.workspace, ID, "demo").attempts()[0]["attempt"] == 1 and mgr.get(again.json()["id"]).orch.attempt == 2
        client.post(f"/api/projects/{again.json()['id']}/autoplay/stop")
    finally:
        mgr.shutdown()


def test_nobody_else_posts_in_the_channel_while_a_script_plays(world):
    """A viewer's message would change the weak run's score (it must stay silent until the nudge): the channel is the script's, and a person's own session is not affected."""
    client, mgr, settings = world
    pid, s = watch(client, mgr, "weak")
    wait_for(lambda: events(s, "autoplay_started"), 60, "the run to start")
    r = client.post(f"/api/projects/{pid}/channel", json={"text": "Update: I am on it."})
    assert r.status_code == 409 and "scripted run" in r.json()["detail"]
    assert not [m for m in events(s, "channel_message") if m.get("source") == "learner"]
    client.post(f"/api/projects/{pid}/autoplay/stop")
    plain = client.post(f"/api/scenarios/{ID}/start").json()["id"]
    assert client.post(f"/api/projects/{plain}/channel", json={"text": "Update: I am on it."}).status_code == 200
    mgr.get(plain).orch.stop()
