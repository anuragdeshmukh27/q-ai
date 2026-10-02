from app.agent.actions import Action
from app.agent.termination import MAX_ITERATIONS, NO_IMPROVEMENT, REPEATED_ACTION, TerminationTracker


def a(action="read_file", **kw):
    kw.setdefault("path", "x.py") if action in ("read_file", "write_file") else None
    if action == "write_file":
        kw.setdefault("content", "c")
    return Action(thought="t", action=action, **kw)


def test_no_termination_initially():
    assert TerminationTracker().check() is None


def test_max_iterations_default_8():
    t = TerminationTracker()
    for i in range(7):
        t.record(a(path=f"f{i}.py"))
        assert t.check() is None
    t.record(a(path="f7.py"))
    assert t.check() == MAX_ITERATIONS


def test_custom_max_iterations():
    t = TerminationTracker(max_iterations=2)
    t.record(a(path="a"))
    assert t.check() is None
    t.record(a(path="b"))
    assert t.check() == MAX_ITERATIONS


def test_same_failing_tests_three_runs_is_no_improvement():
    t = TerminationTracker(max_iterations=20)
    for i in range(2):
        t.record(a("run_tests"), "tests/t.py::test_a")
        t.record(a("write_file", path=f"f{i}.py"))
    assert t.check() is None
    t.record(a("run_tests"), "tests/t.py::test_a")
    assert t.check() == NO_IMPROVEMENT


def test_changed_failures_reset_the_window():
    t = TerminationTracker(max_iterations=20)
    t.record(a("run_tests"), "x")
    t.record(a("write_file", path="a"))
    t.record(a("run_tests"), "x")
    t.record(a("write_file", path="b"))
    t.record(a("run_tests"), "y")  # different failure set = progress
    assert t.check() is None


def test_passing_run_resets_the_window():
    t = TerminationTracker(max_iterations=20)
    t.record(a("run_tests"), "x")
    t.record(a("write_file", path="a"))
    t.record(a("run_tests"), "x")
    t.record(a("write_file", path="b"))
    t.record(a("run_tests"), "")  # passed
    t.record(a("write_file", path="c"))
    t.record(a("run_tests"), "x")
    assert t.check() is None


def test_repeated_identical_action_warns_then_terminates():
    t = TerminationTracker(max_iterations=20)
    t.record(a(path="same.py"))
    assert not t.repeat_warning()
    t.record(a(path="same.py"))
    assert t.repeat_warning() and t.check() is None
    t.record(a(path="same.py"))
    assert t.check() == REPEATED_ACTION


def test_thought_does_not_make_actions_different():
    t = TerminationTracker(max_iterations=20)
    for thought in ("one", "two", "three"):
        t.record(Action(thought=thought, action="read_file", path="same.py"))
    assert t.check() == REPEATED_ACTION


def test_different_action_in_between_resets_repeats():
    t = TerminationTracker(max_iterations=20)
    t.record(a(path="same.py"))
    t.record(a(path="same.py"))
    t.record(a(path="other.py"))
    t.record(a(path="same.py"))
    assert t.check() is None and not t.repeat_warning()


def test_failed_iteration_counts_towards_the_limit():
    t = TerminationTracker(max_iterations=2)
    t.record_failed()
    t.record_failed()
    assert t.check() == MAX_ITERATIONS


def test_consecutive_invalid_outputs_terminate():
    t = TerminationTracker(max_iterations=20)
    t.record_failed()
    t.record_failed()
    assert t.check() is None
    t.record_failed()
    assert t.check() == "invalid_output"
    t2 = TerminationTracker(max_iterations=20)
    t2.record_failed()
    t2.record_failed()
    t2.record(a(path="ok"))
    t2.record_failed()
    assert t2.check() is None


def test_stall_warning_one_failure_before_escalation():
    t = TerminationTracker(max_iterations=20)
    t.record(a("run_tests"), "tests/t.py::test_a")
    assert not t.stall_warning()
    t.record(a("write_file"))
    t.record(a("run_tests"), "tests/t.py::test_a")
    assert t.stall_warning() and t.check() is None
    t.record(a("write_file", path="g.py"))
    t.record(a("run_tests"), "tests/t.py::test_a")
    assert t.check() == NO_IMPROVEMENT


def test_stall_warning_not_for_passing_or_changing_failures():
    t = TerminationTracker(max_iterations=20)
    t.record(a("run_tests"), "")
    t.record(a("run_tests"), "")
    assert not t.stall_warning()
    t.record(a("run_tests"), "x")
    t.record(a("run_tests"), "y")
    assert not t.stall_warning()
