"""The incident channel without a server: the scripted timeline on a fake clock, the live replies and their fallback, the session log and the guide."""
import json
import threading

import pytest

from app.config import load_agents
from app.scenarios.build import diff_stats
from app.scenarios.director import Director, Replier, fallback_text
from app.scenarios.guide import GuideTracker, guide_markdown
from app.scenarios.loader import load_scenario
from app.scenarios.sessionlog import SessionLog

from scenario_helpers import FakeClock, ScenarioLLM

SCN = load_scenario("opd-bookings-down")
ROSTER = load_agents()


class Room:
    """A director, its log and the events it emitted, on a clock the test moves."""

    def __init__(self, llm=None, replier=None, timeout=5.0):
        self.clock = FakeClock()
        self.events: list[dict] = []
        self.emit = lambda type, **d: self.events.append({"type": type, **d})  # noqa: E731
        self.log = SessionLog(self.clock, self.emit)
        self.llm = llm
        self.replier = replier or Replier(llm, "qwen25-coder-7b", timeout=timeout)
        self.director = Director(SCN, self.log, self.emit, ROSTER, self.replier)
        self.log.subscribe(self.director.on_log_event)

    def at(self, seconds: float) -> list[dict]:
        """Move the session clock to `seconds` after the start and let the script speak."""
        self.clock.t = self.log.t0 + seconds
        return self.director.tick()

    def said(self, sender=None) -> list[dict]:
        return [e for e in self.events if e["type"] == "channel_message" and (sender is None or e["from"] == sender)]

    def logged(self, kind) -> list[dict]:
        return self.log.events(kind)


# -- the timeline ----------------------------------------------------------------------------------

def test_ananya_reports_the_real_error_three_seconds_in_and_only_once():
    r = Room()
    assert r.at(2) == []
    posted = r.at(3)
    assert [m["from"] for m in posted] == ["qa"] and posted[0]["channel"] == "incident-opd" and posted[0]["source"] == "scripted"
    assert "TypeError: add_appointment() got an unexpected keyword argument 'slot_time'" in posted[0]["text"] and "KeyError: 'slot_time'" in posted[0]["text"]
    assert r.at(60) == []  # nothing else is due, and the report is not repeated
    assert [m["id"] for m in r.said()] == ["C001"]


def test_aarav_asks_for_an_update_at_90_seconds_unless_you_already_posted():
    r = Room()
    r.at(3)
    assert [m["from"] for m in r.at(90)] == ["architect"] and "update" in r.said("architect")[0]["text"]
    quiet = Room()
    quiet.at(3)
    quiet.at(40)
    quiet.director.post("Looking at the booking route now.")
    quiet.director.join()
    quiet.at(95)
    assert [m for m in quiet.said("architect") if m.get("ref") == "lead-update"] == []  # skipped: he got your post, only his thanks is there
    assert [m["text"] for m in quiet.said("architect")] == SCN.acks[:1]


def test_aarav_nudges_after_five_quiet_minutes_three_times_at_most():
    r = Room()
    r.at(3)
    r.at(90)
    r.at(250)  # Karan's pointer at 4 minutes
    assert r.at(299) == []
    first = r.at(300)
    assert [m["ref"] for m in first] == ["lead-nudge"] and first[0]["text"].startswith("No update from you for 5 minutes")
    assert r.at(599) == [] and len(r.at(600)) == 1 and len(r.at(900)) == 1
    assert r.at(1500) == [] and r.at(3000) == []  # three nudges, then he stops
    assert [m["text"] for m in r.said("architect") if m["ref"] == "lead-nudge"] == SCN.timeline[2].texts


def test_a_post_from_you_restarts_the_five_minutes():
    r = Room()
    r.at(3)
    r.at(250)
    r.director.post("Still reading the failing tests.")
    r.director.join()
    assert r.at(300) == [] and r.at(549) == []
    assert [m["ref"] for m in r.at(550)] == ["lead-nudge"]


def test_karan_points_at_migration_0007_after_four_minutes_and_it_counts_as_a_hint():
    r = Room()
    r.at(3)
    assert all(m["from"] != "database" for m in r.at(239))  # Aarav's request for an update is due by now, Karan is not
    posted = r.at(240)
    assert [m["from"] for m in posted if m["from"] == "database"] == ["database"]
    karan = r.said("database")[0]
    assert "0007" in karan["text"] and "slot_at" in karan["text"] and karan["source"] == "scripted" and karan["hint"] is True
    hints = r.logged("hint_given")
    assert len(hints) == 1 and hints[0]["from"] == "database" and hints[0]["source"] == "scripted" and hints[0]["reason"] == "timeline" and hints[0]["n"] == 1
    assert hints[0]["message"] == karan["id"] and r.director.hints == 1


def test_karan_does_not_repeat_himself_when_you_asked_him_first():
    r = Room(ScenarioLLM("I merged migration 0007 on Monday."))
    r.at(3)
    r.at(100)
    r.director.post("Karan, did anything change in the database?")
    r.director.join()
    r.at(240)
    assert [m["source"] for m in r.said("database")] == ["live"]  # his own answer, not the timed pointer
    assert r.director.hints == 1


def test_the_team_reacts_when_you_submit():
    r = Room()
    r.at(3)
    r.log.add("submit_result", task="h1", ok=False, stage="tests", summary="1 failed", failed=["tests/api/test_booking.py::test_booking_an_appointment_returns_201", "tests/api/test_booking.py::test_editing_an_appointment_moves_its_time"], review_items=0)
    qa = [m for m in r.said("qa") if m["ref"] == "react-tests-failed"]
    assert len(qa) == 1 and "test_booking_an_appointment_returns_201, test_editing_an_appointment_moves_its_time" in qa[0]["text"]
    r.log.add("submit_result", task="h1", ok=True, stage="accepted", summary="12 passed", failed=[], review_items=0)
    assert [m["ref"] for m in r.said("architect") if m["ref"] == "react-accepted-lead"] == ["react-accepted-lead"]
    assert not [m for m in r.said("qa") if m["ref"] == "react-accepted-qa"]  # Ananya checks main a few seconds later
    r.at(10)
    assert [m["ref"] for m in r.said("qa") if m["ref"] == "react-accepted-qa"] == ["react-accepted-qa"]
    assert r.at(2000) == [] and r.director.closed  # solved: nobody nudges any more


def test_a_stopped_session_says_nothing_more():
    r = Room()
    r.director.stop()
    assert r.at(500) == []
    with pytest.raises(ValueError, match="closed"):
        r.director.post("hello?")


# -- you talk to a teammate ----------------------------------------------------------------------------

def test_a_question_to_karan_gets_a_short_live_reply_grounded_in_his_facts():
    llm = ScenarioLLM("That was my migration 0007: slot_time is now slot_at in database/appointments.py.")
    r = Room(llm)
    r.at(3)
    out = r.director.post("Karan, what changed in the appointments table on Monday?")
    assert out["to"] == ["database"] and out["pending"] == ["database"]
    r.director.join()
    mine, theirs = r.said("human")[0], r.said("database")[0]
    assert mine["text"].startswith("Karan,") and mine["source"] == "learner" and mine["to"] == ["database"]
    assert theirs["source"] == "live" and theirs["reply_to"] == mine["id"] and "0007" in theirs["text"] and theirs["hint"] is True
    prompt = llm.prompts[0]
    assert "You are Karan, the Database Engineer" in prompt and "Use ONLY the facts below" in prompt and "migration 0007_rename_slot_time_to_slot_at.sql" in prompt
    assert "Listing, completing, cancelling" not in prompt and "morning clinic opens at 09:00" not in prompt  # Ananya's and Aarav's facts are not Karan's
    assert "Ananya:" in prompt and "Booking is down" in prompt  # the latest messages of the channel are part of the context
    hint = r.logged("hint_given")[0]
    assert hint["source"] == "live" and hint["reason"] == "" and hint["question"].startswith("Karan, what changed") and hint["n"] == 1
    assert [e["kind"] for e in r.log.events()][-4:] == ["team_message", "message_posted", "team_message", "hint_given"]  # the report, your question, his answer, the hint counted


def test_the_recipient_can_be_picked_in_the_ui_or_written_as_a_name_or_an_at_id():
    r = Room(ScenarioLLM("ok"))
    assert r.director.post("what does the log say?", to="qa")["to"] == ["qa"]
    assert r.director.post("@database any idea?")["to"] == ["database"]
    assert r.director.post("Ananya and Priya, quick one")["to"] == ["qa", "planner"]
    assert r.director.post("Aarav, Ananya, Karan: who owns the slot picker?")["to"] == ["architect", "qa"]  # a post starts at most two replies
    assert r.director.post("anything?", to="nobody")["to"] == []
    r.director.join()


def test_without_a_name_the_lead_answers_with_an_acknowledgement_and_it_is_no_hint():
    llm = ScenarioLLM()
    r = Room(llm)
    r.director.post("Reproduced it locally, it is a TypeError in the booking route.")
    r.director.post("Looking at the migration folder next.")
    assert [m["text"] for m in r.said("architect")] == SCN.acks[:2] and llm.chat_calls == 0 and r.director.hints == 0
    r.director.post("Vikram, any idea?")  # a colleague who is not on this incident
    assert "is not on this incident" in r.said("architect")[-1]["text"] and llm.chat_calls == 0


@pytest.mark.parametrize("llm,reason", [
    (ScenarioLLM(fail=True), "error"),
    (ScenarioLLM("```python\nx = 1\n```"), "invalid"),
    (ScenarioLLM("   "), "invalid"),
])
def test_the_scripted_text_answers_when_the_model_errors_or_answers_badly(llm, reason):
    r = Room(llm)
    r.director.post("Karan, what changed?")
    r.director.join()
    msg = r.said("database")[0]
    assert msg["source"] == "fallback" and msg["text"] == fallback_text(SCN, "database", "what changed?") and "0007" in msg["text"]
    hint = r.logged("hint_given")[0]
    assert hint["source"] == "fallback" and hint["reason"] == reason and r.director.hints == 1  # still counted and logged


def test_the_scripted_text_answers_when_the_model_is_not_installed():
    r = Room(replier=Replier(ScenarioLLM(), "qwen25-coder-7b", available=lambda: False))
    r.director.post("Karan, what changed?")
    r.director.join()
    assert r.said("database")[0]["source"] == "fallback" and r.logged("hint_given")[0]["reason"] == "unavailable"
    r2 = Room(replier=Replier(None))
    r2.director.post("Karan, what changed?")
    r2.director.join()
    assert r2.logged("hint_given")[0]["reason"] == "unavailable"


def test_the_scripted_text_answers_when_the_model_is_too_slow():
    r = Room(ScenarioLLM(delay=1.0), timeout=0.2)
    r.director.post("Karan, what changed?")
    r.director.join()
    assert r.said("database")[0]["source"] == "fallback" and r.logged("hint_given")[0]["reason"] == "timeout"


def test_a_second_question_while_the_model_is_busy_gets_the_scripted_text_at_once():
    gate = threading.Event()
    r = Room(ScenarioLLM(gate=gate))
    r.director.post("Karan, what changed?")  # this one holds the model
    r.director.post("Ananya, what does the log say about the slots?")
    for th in list(r.director._threads)[1:]:
        th.join(5)
    assert [(m["from"], m["source"]) for m in r.said() if m["from"] == "qa" and m["reply_to"]] == [("qa", "fallback")]
    assert r.logged("hint_given")[0]["reason"] == "busy"
    gate.set()
    r.director.join()
    assert sorted(m["source"] for m in r.said() if m.get("hint")) == ["fallback", "live"] and r.director.hints == 2


def test_a_long_reply_is_cut_and_the_fallback_picks_the_answer_that_fits_the_question():
    r = Room(ScenarioLLM("Word. " * 200))
    r.director.post("Karan, what changed?")
    r.director.join()
    assert len(r.said("database")[0]["text"]) <= 320
    assert "slots" in fallback_text(SCN, "qa", "what about the doctor slots?").lower() and "KeyError: 'slot_time'" in fallback_text(SCN, "qa", "what about the doctor slots?")
    assert "booking returns 500" in fallback_text(SCN, "qa", "tell me everything")  # the default (last) one
    assert "rolled back" in fallback_text(SCN, "architect", "can we rollback?") or "cannot roll" in fallback_text(SCN, "architect", "can we rollback?")


def test_every_hint_is_counted_and_numbered():
    r = Room(ScenarioLLM("A short answer."))
    for q in ("Karan, one?", "Ananya, two?", "Priya, three?"):
        r.director.post(q)
        r.director.join()
    assert r.director.hints == 3 and [h["n"] for h in r.logged("hint_given")] == [1, 2, 3]
    assert r.log.summary()["hints"] == 3 and r.log.summary()["messages"] == 3


# -- the session log ------------------------------------------------------------------------------------

def test_log_entries_have_a_stable_quotable_id_and_a_session_relative_time(tmp_path):
    clock = FakeClock()
    seen = []
    log = SessionLog(clock, lambda type, **d: seen.append((type, d)))
    log.attach(tmp_path / "session")
    a = log.add("session_started", scenario="x", role="backend")
    clock.advance(63.24)
    b = log.add("file_opened", role="backend", path="backend/api/appointments.py")
    assert (a["id"], a["t"]) == ("E001", 0.0) and (b["id"], b["t"]) == ("E002", 63.2)
    assert [t for t, _ in seen] == ["session_event", "session_event"] and seen[1][1]["id"] == "E002" and seen[1][1]["kind"] == "file_opened"
    assert log.get("E002")["path"] == "backend/api/appointments.py" and log.get("E099") is None
    lines = [json.loads(x) for x in (tmp_path / "session" / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines == log.events() and [x["id"] for x in lines] == ["E001", "E002"]
    with pytest.raises(ValueError):
        log.add("lunch")


def test_a_log_attached_late_keeps_what_happened_before(tmp_path):
    log = SessionLog(FakeClock())
    log.add("session_started", scenario="x", role="backend")
    log.attach(tmp_path / "s")
    log.add("submit", task="h1")
    assert [json.loads(x)["id"] for x in (tmp_path / "s" / "log.jsonl").read_text(encoding="utf-8").splitlines()] == ["E001", "E002"]


def test_diff_stats_count_added_and_removed_lines():
    assert diff_stats("a\nb\nc\n", "a\nB\nc\nd\n") == (2, 1)
    assert diff_stats("", "x\ny\n") == (2, 0) and diff_stats("x\ny\n", "") == (0, 2) and diff_stats("same\n", "same\n") == (0, 0)
    assert diff_stats("a\r\nb\r\n", "a\nb\n") == (0, 0)  # line endings are not changes


# -- Priya's guide ------------------------------------------------------------------------------------------

def test_the_guide_advances_on_what_you_do_and_never_on_a_timer():
    clock = FakeClock()
    out: list[dict] = []
    log = SessionLog(clock)
    guide = GuideTracker(SCN, lambda type, **d: out.append({"type": type, **d}), log.events)
    log.subscribe(guide.on_event)
    guide.start("h1")
    assert out[-1]["type"] == "guide_progress" and out[-1]["current"] == "run-tests" and out[-1]["done"] == 0 and len(out[-1]["steps"]) == 7
    clock.advance(3600)
    log.add("message_posted", message="C001", text="hello", to=[])  # an hour later and nothing moved, then a post: it counts only when the guide reaches that step
    assert out[-1]["current"] == "run-tests"
    log.add("test_run", task="h1", trigger="ide")
    assert out[-1]["current"] == "open-route"
    log.add("file_opened", role="backend", path="database/migrations/0007_rename_slot_time_to_slot_at.sql")  # out of order: remembered
    assert out[-1]["current"] == "open-route"
    log.add("file_opened", role="backend", path="backend/api/appointments.py", auto=True)  # the IDE showed its first file by itself: not the learner's choice
    assert out[-1]["current"] == "open-route"
    log.add("file_opened", role="backend", path="backend/api/appointments.py")
    assert out[-1]["current"] == "fix" and [s["state"] for s in out[-1]["steps"]][:5] == ["done", "done", "done", "done", "current"]  # the migration and the post were already done
    log.add("file_saved", role="backend", path="tests/api/test_x.py", added=1, removed=0, size=1)  # not a backend file: no
    assert out[-1]["current"] == "fix"
    log.add("file_saved", role="backend", path="backend/api/doctors.py", added=1, removed=1, size=10)
    assert out[-1]["current"] == "tests-green"
    n = len(out)
    log.add("test_result", task="h1", ok=False, passed=1, failed=["a"], summary="1 failed", trigger="ide")  # red does not advance, and nothing is announced
    assert out[-1]["current"] == "tests-green" and len(out) == n
    log.add("test_result", task="h1", ok=True, passed=2, failed=[], summary="2 passed", trigger="ide")
    assert out[-1]["current"] == "submit"
    log.add("submit", task="h1")
    assert out[-1]["current"] is None and out[-1]["done"] == 7 and all(s["state"] == "done" for s in out[-1]["steps"])


def test_the_guide_file_lists_every_step():
    md = guide_markdown(SCN, "h1", "Fix: booking an appointment returns 500")
    assert md.startswith("# Priya's guide: h1 Fix: booking") and md.count("\n1. **Reproduce it**") == 1 and "7. **Submit for review**" in md
    assert "0007" not in md.split("\n", 3)[3].split("Find what changed")[0]  # the steps point at where to look, not at the answer
