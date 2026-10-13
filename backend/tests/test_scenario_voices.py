"""The 7b only speaks. The points are the rules' (labelled "rule"); a judge's line is the model's (after the criterion and score, put in front in code) and the coach paragraph is the model's
when they say only what the points say, name one strength and one gap with their times and use no generic praise; otherwise the template's, with every rejection recorded apart."""
import threading
import time

import pytest

from app.config import load_agents
from app.scenarios.debrief import judge_post, moment_of
from app.scenarios.loader import load_scenario
from app.scenarios.reports import attach_voices, build_report, render_markdown
from app.scenarios.rubric import load_rubric
from app.scenarios.scoring import clock, score
from app.scenarios.wording import VoiceLine, VoiceOutput, Wordsmith, build_voices, coach_moments, verify_voice

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
    """What the model says for each judge: about the moment, by its time, with the tip. Neither the criterion nor the score: they are put in front in code."""
    out = []
    for c in r["criteria"]:
        m = moments(r)[c["id"]]
        out.append(VoiceLine(criterion=c["id"], line=f"at {clock(m['t'])} {m['note'].split(';')[0].rstrip('.')[0].lower()}{m['note'].split(';')[0].rstrip('.')[1:]}, so try this: {m['tip'].rstrip('.')[0].lower()}{m['tip'].rstrip('.')[1:]}."))
    return out


def good_coach(r: dict) -> str:
    cm = coach_moments(r)
    gap = f" At {clock(cm['gap']['t'])} {cm['gap']['note'].rstrip('.')}, and that is what to work on first." if cm["gap"] else ""
    return f"At {clock(cm['strength']['t'])} {cm['strength']['note'].rstrip('.')}.{gap} Do the same again in the next scenario."


# -- the points are the rules' ---------------------------------------------------------------------------------------------

def test_points_use_the_rule_sentence_labelled_rule_and_the_report_starts_with_a_template_coach():
    r = weak_report()
    assert {x["worded_by"] for x in r["rows"]} == {"rule"} and r["fairness"]["voices"] == {"judges": "template", "coach": "template", "reason": ""} and r["judge_lines"] == {}
    assert r["fairness"]["ai_rejected"] == [] and r["coach"]["source"] == "template" and r["coach"]["text"].startswith(f"You scored {r['total']} out of 100.")
    assert "[rule]" in render_markdown(r, NAMES) and "Sentences in the 7b" not in str(r["fairness"])


def test_the_template_coach_names_the_best_and_the_weakest_criterion_and_the_first_thing_to_do():
    r = weak_report()
    assert r["coach"]["text"] == (f"You scored {r['total']} out of 100. Fix quality was your strongest area (2/4) and Communication the weakest (0/4). "
                                  f"First thing for the next attempt: {r['focus'][0][0].lower() + r['focus'][0][1:]}")
    assert strong_report()["coach"]["text"] == "You scored 100 out of 100. Every criterion scored 4 out of 4. There is nothing to fix: beat your time or take these habits to the next scenario."


# -- the verifier: a judge's line ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,problem", [
    ("your first update came at 05:30, late, so post sooner next time.", None),
    ("at 02:00 you were late, so post sooner next time.", "the time 02:00 is not the time of any point"),
    ("at 05:30 you were late; see backend/api/zzz.py for how to do it.", "the file backend/api/zzz.py is not in any point"),
    ("at 05:30 you waited 777 seconds, so post sooner next time.", "the number 777 is not in any point"),
    ("at 05:30 you wrote “we fixed it already” in the channel.", "the quoted words “we fixed it already” are not in any point"),
    ("at 05:30 you wrote “ok still on it” in the channel, so say more next time.", None),
    ("at 05:30 the architect nudged you, so post sooner next time.", "it uses a role id instead of a name"),
    ("at 05:30 you did a great job posting, so post sooner next time.", "generic praise"),
    ("too short.", "characters, it must be"),
    ("and so on " * 40, "characters, it must be"),
    ("at 05:30 you were late, so post sooner next time: this is 0/4.", None),  # stating the criterion's own score is harmless
    ("at 05:30 you were late, so post sooner next time: this is 3/4.", "it states the score 3/4, the criterion's is 0/4"),
])
def test_a_judge_line_may_only_say_facts_of_the_points_of_its_criterion(text, problem):
    got = verify_voice(text, weak_report(), "communication", "judge")
    assert (got is None) if problem is None else (got is not None and problem in got)


def test_a_judge_line_does_not_need_to_say_the_score_and_may_not_borrow_a_time_from_another_criterion():
    r = weak_report()
    other = next(x for x in r["rows"] if x["criterion"] == "testing")
    later = clock(other["t"])
    assert later not in {clock(x["t"]) for x in r["rows"] if x["criterion"] == "communication"}
    assert verify_voice("at 05:30 your update was late, so post sooner next time.", r, "communication", "judge") is None  # no score in it: that is fine
    assert "is not the time of any point" in verify_voice(f"at {later} you were late, so post sooner next time.", r, "communication", "judge")


# -- the verifier: the coach paragraph --------------------------------------------------------------------------------------------

def test_the_coach_paragraph_must_name_a_strength_and_a_gap_with_their_times_from_the_findings():
    r = weak_report()
    cm = coach_moments(r)
    assert cm["strength"]["kind"] == "strength" and cm["gap"]["kind"] == "gap" and cm["strength"]["criterion"] in ("fix_quality", "ownership") and cm["gap"]["criterion"] == "communication"
    good = good_coach(r)
    assert verify_voice(good, r, None, "coach") is None
    only_strength = f"At {clock(cm['strength']['t'])} you kept the change small, and the rest of this attempt needs work on the updates and the tests."
    assert "does not name the gap at " + clock(cm["gap"]["t"]) in verify_voice(only_strength, r, None, "coach")
    only_gap = f"At {clock(cm['gap']['t'])} your first update came late, and the tests were run after the first edit, so start with those two."
    assert "does not name the strength at " + clock(cm["strength"]["t"]) in verify_voice(only_gap, r, None, "coach")
    no_time = "Your fix was small and your updates were late, so run the tests before you change anything and post within two minutes next time."
    assert "does not name the strength" in verify_voice(no_time, r, None, "coach")
    assert "does not name the" in verify_voice("short", r, None, "coach") or "characters" in verify_voice("short", r, None, "coach")


@pytest.mark.parametrize("praise", ["You did a great job.", "You showed strong problem-solving skills.", "Well done on the fix.", "Overall this was an excellent attempt."])
def test_generic_praise_is_refused_even_when_the_times_are_right(praise):
    r = weak_report()
    assert "generic praise" in verify_voice(good_coach(r) + " " + praise, r, None, "coach")


@pytest.mark.parametrize("praise", [
    "You showed great communication, diagnosis, fix quality, and testing skills.",
    "You showed great communication in this incident.",
    "That was great communication and great skills overall.",
    "Your communication, diagnosis and testing were all handled well.",
    "You demonstrated strong ownership of the problem.",
])
def test_praise_by_criterion_name_is_refused_and_the_template_paragraph_is_used(praise):
    r = strong_report()
    assert verify_voice(good_coach(r), r, None, "coach") is None
    why = verify_voice(good_coach(r) + " " + praise, r, None, "coach")
    assert why and ("generic praise" in why or "criterion names" in why), why
    got, said, rejected, _ = build_voices(r, Stub(VoiceOutput(lines=good_lines(r), coach=good_coach(r) + " " + praise)), moments(r), template(r))
    assert said == {"text": r["coach"]["text"], "source": "template"} and [d.finding for d in rejected] == ["coach"]


@pytest.mark.parametrize("ask", ["Next time, aim for a full-marks run.", "Aim for full marks next time.", "Try to get a perfect score next attempt.", "Work towards 100 out of 100 again."])
def test_a_full_marks_run_is_never_asked_for_full_marks(ask):
    r = strong_report()
    assert r["total"] == r["max"]
    why = verify_voice(good_coach(r) + " " + ask, r, None, "coach")
    assert why and "asks for full marks" in why, why
    assert verify_voice(good_coach(r) + f" Next time beat the time of {clock(r['elapsed'])} or move on to the next scenario.", r, None, "coach") is None


def test_the_full_marks_advice_is_a_faster_time_or_the_next_scenario_in_the_report_and_the_prompt():
    r = strong_report()
    assert r["focus"] == [f"Full marks already. Beat your time of {clock(r['elapsed'])}, or take these habits to the next scenario."]
    prompt = Wordsmith._prompt(r, moments(r))[0]["content"]
    assert "never ask for full marks" in prompt and "beat the time or to move on to the next scenario" in prompt and "list of criterion names as praise" in prompt
    assert "never ask for full marks" not in Wordsmith._prompt(weak_report(), moments(weak_report()))[0]["content"]
    assert "full-marks" not in r["coach"]["text"] and "full marks" not in r["coach"]["text"].lower()


def test_the_coach_checks_every_time_number_and_file_against_all_the_points():
    r = weak_report()
    assert "the time 59:59 is not the time of any point" in verify_voice(good_coach(r) + " At 59:59 you did something nobody logged.", r, None, "coach")
    assert "the number 88" in verify_voice(good_coach(r) + " You waited 88 minutes.", r, None, "coach")
    assert "the file backend/api/zzz.py" in verify_voice(good_coach(r) + " Look at backend/api/zzz.py.", r, None, "coach")
    full = strong_report()
    assert coach_moments(full)["gap"] is None and verify_voice(good_coach(full), full, None, "coach") is None  # nothing to name as a gap in a clean run


# -- build_voices ----------------------------------------------------------------------------------------------------------------

class Stub:
    def __init__(self, out=None, reason=""):
        self.out, self.reason = out, reason

    def speak(self, report, moments):
        return self.out, self.reason


def template(r):
    return lambda c: judge_post(c, r["rows"])


def test_a_judge_line_gets_its_criterion_and_score_in_front_in_code_and_a_correct_one_is_kept():
    r = weak_report()
    out = VoiceOutput(lines=good_lines(r), coach=good_coach(r))
    lines, coach, rejected, reason = build_voices(r, Stub(out), moments(r), template(r))
    assert reason == "" and rejected == [] and {v["source"] for v in lines.values()} == {"model"} and coach == {"text": good_coach(r), "source": "model"}
    first = lines["communication"]
    assert first["text"].startswith("Communication 0/4: at 05:30 ") and len(first["bubble"]) <= 78 and first["bubble"].startswith("Communication 0/4: ")
    assert lines["testing"]["text"].startswith("Testing 0/4: at ")


def test_lines_that_hold_are_the_models_and_the_rest_are_the_templates_with_the_rejections_recorded():
    r = weak_report()
    lines = good_lines(r)
    lines[1] = VoiceLine(criterion="diagnosis", line="at 99:99 you read nothing, so read the migration first next time.")  # an invented time
    stub = Stub(VoiceOutput(lines=lines, coach=good_coach(r)))
    got, said, rejected, reason = build_voices(r, stub, moments(r), template(r))
    assert reason == "" and [got[i]["source"] for i in IDS] == ["model", "template", "model", "model", "model"]
    assert got["diagnosis"]["text"] == judge_post(next(c for c in r["criteria"] if c["id"] == "diagnosis"), r["rows"])[0]
    assert said["source"] == "model" and [(d.finding, "99:99" in d.reason) for d in rejected] == [("diagnosis", True)]
    attach_voices(r, got, said, rejected, reason)
    assert r["fairness"]["dropped"] == [] and [d["finding"] for d in r["fairness"]["ai_rejected"]] == ["diagnosis"]  # the unbacked claims are about evidence points only
    assert r["fairness"]["voices"] == {"judges": "mixed", "coach": "model", "reason": ""}


def test_a_generic_or_timeless_coach_paragraph_is_rejected_and_the_template_paragraph_stays():
    r = weak_report()
    generic = "You did a great job communicating the status and showed strong problem-solving skills. Remember to read the migration before editing next time."
    got, said, rejected, reason = build_voices(r, Stub(VoiceOutput(lines=good_lines(r), coach=generic)), moments(r), template(r))
    assert said == {"text": r["coach"]["text"], "source": "template"} and [d.finding for d in rejected] == ["coach"] and "generic praise" in rejected[0].reason
    attach_voices(r, got, said, rejected, reason)
    assert r["fairness"]["voices"] == {"judges": "model", "coach": "template", "reason": ""} and r["fairness"]["ai_rejected"][0]["finding"] == "coach" and r["fairness"]["dropped"] == []


def test_a_missing_line_falls_back_to_the_template_and_is_recorded():
    r = weak_report()
    stub = Stub(VoiceOutput(lines=good_lines(r)[:3], coach=good_coach(r)))
    got, said, rejected, reason = build_voices(r, stub, moments(r), template(r))
    assert [got[i]["source"] for i in IDS] == ["model", "model", "model", "template", "template"] and [d.finding for d in rejected] == ["testing", "ownership"]
    assert all("no line" in d.reason for d in rejected) and said["source"] == "model"


@pytest.mark.parametrize("reason", ["unavailable", "busy", "timeout", "error", "invalid"])
def test_when_the_model_cannot_be_used_every_line_and_the_paragraph_are_the_templates(reason):
    r = weak_report()
    got, said, rejected, why = build_voices(r, Stub(None, reason), moments(r), template(r))
    assert {v["source"] for v in got.values()} == {"template"} and said["source"] == "template" and rejected == [] and why == reason
    assert got["communication"]["text"] == judge_post(r["criteria"][0], r["rows"])[0]
    attach_voices(r, got, said, rejected, why)
    assert r["fairness"]["voices"] == {"judges": "template", "coach": "template", "reason": reason} and r["fairness"]["ai_rejected"] == []


def test_the_markdown_lists_unbacked_claims_and_ai_lines_not_used_apart():
    r = weak_report()
    attach_voices(r, {}, r["coach"], [], "")
    r["fairness"]["ai_rejected"] = [{"finding": "coach", "text": "You did a great job.", "reason": "it uses generic praise"}]
    md = render_markdown(r, NAMES)
    assert "- Unbacked claims dropped: 0" in md and "- AI lines not used: 1" in md and "coach: “You did a great job.” (it uses generic praise)" in md


# -- the call itself ----------------------------------------------------------------------------------------------------------------

def test_the_model_is_not_asked_for_the_score_and_is_told_which_strength_and_gap_to_name():
    r = weak_report()
    seen = []
    llm = ScenarioLLM(wording=lambda prompt: (seen.append(prompt), VoiceOutput(lines=good_lines(r), coach=good_coach(r)))[1])
    out, reason = Wordsmith(llm, available=lambda: True).speak(r, moments(r))
    assert reason == "" and len(out.lines) == 5 and llm.wording_calls == 1
    prompt = seen[0]
    cm = coach_moments(r)
    assert "Do not write the criterion name or the score" in prompt and "say what to do first next time" in prompt and "No praise words" in prompt
    assert f"the strength at {clock(cm['strength']['t'])}" in prompt and f"the gap at {clock(cm['gap']['t'])}" in prompt
    assert 'criterion "communication": Communication, judge Aarav, score 0/4' in prompt and "05:30" in prompt and "ok still on it" in prompt and "total score is" in prompt
    assert "[GAP]" not in prompt and "F01" not in prompt  # no per-point sentences are asked for


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
    r = weak_report()
    slow = ScenarioLLM(wording=lambda p: (time.sleep(1.0), VoiceOutput(lines=good_lines(r), coach=good_coach(r)))[1])
    ws = Wordsmith(slow, timeout=5)
    first = threading.Thread(target=ws.speak, args=(r, moments(r)))
    first.start()
    time.sleep(0.2)
    assert ws.speak(r, moments(r)) == (None, "busy")
    first.join()
