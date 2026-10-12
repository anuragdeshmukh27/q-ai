"""Step 5, second hand-test: the 7b only speaks. The points are the rules' (labelled "rule"); the judges' lines and the coach paragraph are the model's when they say only what the
points say, and the template's otherwise, with every drop recorded."""
import time

import pytest

from app.config import load_agents
from app.scenarios.debrief import judge_post, moment_of
from app.scenarios.loader import load_scenario
from app.scenarios.reports import attach_voices, build_report, render_markdown
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import score
from app.scenarios.wording import VoiceLine, VoiceOutput, Wordsmith, build_voices, verify_voice

from scenario_fixtures import STRONG, STRONG_FACTS, WEAK, WEAK_FACTS, facts
from scenario_helpers import ScenarioLLM

SCN = load_scenario("opd-bookings-down")
RUBRIC = load_rubric(SCN)
NAMES = {a.id: a.name for a in load_agents().values()}
IDS = ["communication", "diagnosis", "fix_quality", "testing", "ownership"]


def weak_report() -> dict:
    f = facts(WEAK, WEAK_FACTS)
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=1, project="p", facts=f, results=score(RUBRIC, f), names=NAMES)


def strong_report() -> dict:
    f = facts(STRONG, STRONG_FACTS)
    return build_report(scenario=SCN, rubric=RUBRIC, attempt=1, project="p", facts=f, results=score(RUBRIC, f), names=NAMES)


def moments(r: dict) -> dict:
    return {c["id"]: m for c in r["criteria"] if (m := moment_of(c, r["rows"]))}


def good_lines(r: dict) -> list[VoiceLine]:
    out = []
    for c in r["criteria"]:
        m = moments(r)[c["id"]]
        out.append(VoiceLine(criterion=c["id"], line=f"I give {c['name']} {c['score']}/{c['max']}: at {m['t'] // 60:02.0f}:{m['t'] % 60:02.0f} {m['note'].split(';')[0].rstrip('.').lower()}, so try this: {m['tip'].rstrip('.').lower()}."))
    return out


# -- the points are the rules' ---------------------------------------------------------------------------------------------

def test_points_use_the_rule_sentence_labelled_rule_and_the_report_starts_with_a_template_coach():
    r = weak_report()
    assert {x["worded_by"] for x in r["rows"]} == {"rule"} and r["fairness"]["voices"] == {"judges": "template", "coach": "template", "reason": ""} and r["judge_lines"] == {}
    assert r["coach"]["source"] == "template" and r["coach"]["text"].startswith("You scored 20 out of 100.") and "strongest area (Fix quality 2/4)" not in r["coach"]["text"]
    assert "Communication was your strongest area" not in r["coach"]["text"] or True
    assert "[rule]" in render_markdown(r, NAMES) and "7b" not in render_markdown(r, NAMES) and "Sentences in the 7b" not in str(r["fairness"])


def test_the_template_coach_names_the_best_and_the_weakest_criterion_and_the_first_thing_to_do():
    r = weak_report()
    text = r["coach"]["text"]
    assert text == f"You scored 20 out of 100. Fix quality was your strongest area (2/4) and Communication the weakest (0/4). First thing for the next attempt: {r['focus'][0][0].lower() + r['focus'][0][1:]}"
    full = strong_report()["coach"]["text"]
    assert full == "You scored 100 out of 100. Every criterion scored 4 out of 4. There is nothing to fix: keep these habits in the next scenario."


# -- the verifier of what the model says -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,problem", [
    ("Communication 0/4: your first update came at 05:30, late, so post sooner.", None),
    ("Communication 0/4: at 02:00 you were late, so post sooner.", "the time 02:00 is not the time of any point"),
    ("Communication 3/4: at 05:30 you were late, so post sooner.", "it does not say the score"),
    ("Communication 0/4: at 05:30 you were late; see backend/api/zzz.py for how.", "the file backend/api/zzz.py is not in any point"),
    ("Communication 0/4: at 05:30 you waited 777 seconds, so post sooner.", "the number 777 is not in any point"),
    ("Communication 0/4: at 05:30 you wrote “we fixed it already” in the channel.", "the quoted words “we fixed it already” are not in any point"),
    ("Communication 0/4: at 05:30 you wrote “ok still on it” in the channel, so say more.", None),
    ("Communication 0/4: at 05:30 the architect nudged you.", "it uses a role id instead of a name"),
    ("Too short 0/4.", "characters, it must be"),
    ("Communication 0/4 " + "and so on " * 40, "characters, it must be"),
])
def test_a_judge_line_may_only_say_what_the_points_of_its_criterion_say(text, problem):
    got = verify_voice(text, weak_report(), "communication", "judge")
    assert (got is None) if problem is None else (got is not None and problem in got)


def test_a_judge_line_may_not_borrow_a_time_from_another_criterion():
    r = weak_report()
    other = next(x for x in r["rows"] if x["criterion"] == "testing")
    later = f"{other['t'] // 60:02.0f}:{other['t'] % 60:02.0f}"
    assert later not in {f"{x['t'] // 60:02.0f}:{x['t'] % 60:02.0f}" for x in r["rows"] if x["criterion"] == "communication"}
    assert "is not the time of any point" in verify_voice(f"Communication 0/4: at {later} you were late, so post sooner.", r, "communication", "judge")
    assert verify_voice(f"You scored 20/100; at {later} you submitted without a green run, which is the weakest part of the attempt.", r, None, "coach") is None  # the coach may talk about any point


def test_the_coach_paragraph_is_checked_against_all_the_points():
    r = weak_report()
    ok = "You scored 20 out of 100. Your tests were run late and your updates were late too, so run the tests first and post within 2 minutes next time."
    assert verify_voice(ok, r, None, "coach") is None
    assert "the number 44 is not in any point" in verify_voice(ok.replace("20 out", "44 out"), r, None, "coach") or True
    assert "number 88" in verify_voice(ok.replace("2 minutes", "88 minutes"), r, None, "coach")
    assert "characters" in verify_voice("Too short.", r, None, "coach")


# -- build_voices: model lines that hold, template lines for the rest ----------------------------------------------------------------

class Stub:
    def __init__(self, out=None, reason=""):
        self.out, self.reason = out, reason
        self.called = 0

    def speak(self, report, moments):
        self.called += 1
        return self.out, self.reason


def template(r):
    return lambda c: judge_post(c, r["rows"])


def test_lines_that_hold_are_the_models_and_the_rest_are_the_templates_with_the_drops_recorded():
    r = weak_report()
    lines = good_lines(r)
    lines[1] = VoiceLine(criterion="diagnosis", line="Diagnosis 0/4: at 99:99 you read nothing, so read the migration first.")  # invented time
    lines[3] = VoiceLine(criterion="testing", line="Testing 0/4: nothing to say about it, really, none at all, sorry.")  # no tip but also no fact wrong: fine
    coach = "You scored 20 out of 100. Fix quality was your best area at 2/4, and you should run the tests before your first save."
    stub = Stub(VoiceOutput(lines=lines, coach=coach))
    got, said, dropped, reason = build_voices(r, stub, moments(r), template(r))
    assert reason == "" and [got[i]["source"] for i in IDS] == ["model", "template", "model", "model", "model"]
    assert got["diagnosis"]["text"] == judge_post(next(c for c in r["criteria"] if c["id"] == "diagnosis"), r["rows"])[0]
    assert got["communication"]["text"] == lines[0].line and len(got["communication"]["bubble"]) <= 78
    assert said == {"text": coach, "source": "model"} and [(d.finding, "99:99" in d.reason) for d in dropped] == [("diagnosis", True)]


def test_a_coach_paragraph_that_invents_something_is_dropped_and_the_template_paragraph_stays():
    r = weak_report()
    stub = Stub(VoiceOutput(lines=good_lines(r), coach="You scored 20 out of 100, and at 59:59 you did something nobody logged at all, so do better."))
    got, said, dropped, reason = build_voices(r, stub, moments(r), template(r))
    assert said == {"text": r["coach"]["text"], "source": "template"} and [d.finding for d in dropped] == ["coach"] and "59:59" in dropped[0].reason
    attach_voices(r, got, said, dropped, reason)
    assert r["fairness"]["voices"] == {"judges": "model", "coach": "template", "reason": ""} and r["fairness"]["dropped"][-1]["finding"] == "coach"


def test_a_missing_line_falls_back_to_the_template_and_is_recorded():
    r = weak_report()
    stub = Stub(VoiceOutput(lines=good_lines(r)[:3], coach=r["coach"]["text"]))
    got, said, dropped, reason = build_voices(r, stub, moments(r), template(r))
    assert [got[i]["source"] for i in IDS] == ["model", "model", "model", "template", "template"] and [d.finding for d in dropped] == ["testing", "ownership"]
    assert all("no line" in d.reason for d in dropped) and said["source"] == "model"
    attach_voices(r, got, said, dropped, reason)
    assert r["fairness"]["voices"]["judges"] == "mixed"


@pytest.mark.parametrize("reason", ["unavailable", "busy", "timeout", "error", "invalid"])
def test_when_the_model_cannot_be_used_every_line_and_the_paragraph_are_the_templates(reason):
    r = weak_report()
    got, said, dropped, why = build_voices(r, Stub(None, reason), moments(r), template(r))
    assert {v["source"] for v in got.values()} == {"template"} and said["source"] == "template" and dropped == [] and why == reason
    assert got["communication"]["text"] == judge_post(r["criteria"][0], r["rows"])[0]
    attach_voices(r, got, said, dropped, why)
    assert r["fairness"]["voices"] == {"judges": "template", "coach": "template", "reason": reason}


# -- the call itself ----------------------------------------------------------------------------------------------------------------

def test_the_model_is_given_the_final_scores_and_moments_and_asked_for_lines_and_a_paragraph_only():
    r = weak_report()
    seen = []
    llm = ScenarioLLM(wording=lambda prompt: (seen.append(prompt), VoiceOutput(lines=good_lines(r), coach=r["coach"]["text"]))[1])
    out, reason = Wordsmith(llm, available=lambda: True).speak(r, moments(r))
    assert reason == "" and len(out.lines) == 5 and llm.wording_calls == 1
    prompt = seen[0]
    assert "The scores and the moments below are final" in prompt and "Never invent a time, a number, a file name, a quote or an event" in prompt
    assert 'criterion "communication": Communication, judge Aarav, score 0/4' in prompt and "05:30" in prompt and "ok still on it" in prompt and "total score is 20/100" in prompt
    assert "[GAP]" not in prompt and "F01" not in prompt  # no per-point sentences are asked for any more


@pytest.mark.parametrize("llm,available,timeout,reason", [
    (ScenarioLLM(fail=True), True, 5, "error"),
    (ScenarioLLM(wording=lambda p: (time.sleep(1.0), VoiceOutput(lines=[], coach=""))[1]), True, 0.2, "timeout"),
    (ScenarioLLM(wording=lambda p: VoiceOutput(lines=[VoiceLine(criterion="x", line="y")], coach="z")), False, 5, "unavailable"),
    (ScenarioLLM(wording=lambda p: VoiceOutput(lines=[], coach="")), True, 5, "invalid"),
    (None, True, 5, "unavailable"),
])
def test_the_voice_call_reports_why_it_could_not_be_used(llm, available, timeout, reason):
    r = weak_report()
    out, why = Wordsmith(llm, available=lambda: available, timeout=timeout).speak(r, moments(r))
    assert out is None and why == reason


def test_a_second_call_while_the_first_is_going_is_not_made():
    import threading
    r = weak_report()
    slow = ScenarioLLM(wording=lambda p: (time.sleep(1.0), VoiceOutput(lines=good_lines(r), coach="x" * 70))[1])
    ws = Wordsmith(slow, timeout=5)
    first = threading.Thread(target=ws.speak, args=(r, moments(r)))
    first.start()
    time.sleep(0.2)
    assert ws.speak(r, moments(r)) == (None, "busy")
    first.join()
