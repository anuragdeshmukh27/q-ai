"""Fast by default: tests marked `slow` (shipped-recording replays, autoplay full runs, whole-build and debrief flows, anything over about 5 s) are deselected unless asked for.

    pytest                  the fast tests (the dev loop)
    pytest --full           everything, slow ones included (the merge run)
    pytest -m slow          only the slow ones
    pytest tests/x.py       a file or test named on the command line always runs, slow or not

Nothing is skipped or weakened: a slow test is the same test, run less often.
"""


def pytest_addoption(parser):
    parser.addoption("--full", action="store_true", default=False, help="also run the tests marked slow (the merge run)")


def _asked_for_by_name(config) -> bool:
    return any("::" in a or a.endswith(".py") for a in config.args)


def pytest_collection_modifyitems(config, items):
    if config.getoption("--full") or config.option.markexpr or _asked_for_by_name(config):
        return
    slow = [i for i in items if i.get_closest_marker("slow")]
    if slow:
        config.hook.pytest_deselected(items=slow)
        items[:] = [i for i in items if i not in slow]


def pytest_report_header(config):
    if config.getoption("--full"):
        return "slow tests: included (--full)"
    if config.option.markexpr or _asked_for_by_name(config):
        return None
    return "slow tests: deselected (run `pytest --full` for everything)"
