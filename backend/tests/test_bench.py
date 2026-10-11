"""The benchmark suite itself must be sound: references pass the hidden checks, seeded defects are real, clean diffs are clean."""
import re
import shutil
import subprocess
import sys

import pytest

from app.agent.review import static_findings
from app.presets import load_preset
from app.router import BENCHMARKED_ROLES
from benchmarks.review_cases import CASES
from benchmarks.tasks import FIXTURES, HIDDEN, all_tasks, load_design, load_plan


@pytest.mark.parametrize("fixture", ["todo", "calculator"])
def test_the_reference_data_layer_passes_the_hidden_database_checks(fixture, tmp_path):
    root = tmp_path / "p"
    shutil.copytree(load_preset("fastapi-vanilla").skeleton, root)
    module = next(t for t in load_plan(fixture) if t.owner == "database").files[0]
    (root / module).write_text((FIXTURES / f"{fixture}.database.py").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy(HIDDEN / f"{fixture}_db_test.py", root / "tests" / "test_hidden_db.py")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_hidden_db.py"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-800:]


@pytest.mark.parametrize("fixture", ["todo", "calculator"])
def test_fixtures_are_valid_designs_with_a_plan_for_every_engineer(fixture):
    d = load_design(fixture)
    assert d.endpoints and d.tables and {t.owner for t in load_plan(fixture)} == {"database", "backend", "frontend"}


def test_every_task_belongs_to_a_benchmarked_role_and_ids_are_unique():
    tasks = all_tasks()
    assert len({t.id for t in tasks}) == len(tasks)
    assert {t.role for t in tasks} == set(BENCHMARKED_ROLES)


def test_the_seeded_defects_are_real_and_the_clean_diffs_are_clean():
    for case in CASES:
        added = {}
        for m in re.finditer(r"^diff --git a/(\S+) b/\S+\n(.*?)(?=^diff --git|\Z)", case["diff"], re.S | re.M):
            added[m.group(1)] = "\n".join(l[1:] for l in m.group(2).splitlines() if l.startswith("+") and not l.startswith("+++"))
        found = static_findings(added)
        if case["defect_file"] is None:
            assert not found, case["id"]
        elif case["id"] != "missing-validation":  # a semantic defect: only a reader can see that the acceptance criteria are not met
            assert any(f.file == case["defect_file"] for f in found), case["id"]
        else:
            assert not found


def test_the_analyst_cases_have_a_clean_answer_key():
    from benchmarks.tasks import ANALYST_CASES, _norm
    from app.finish.analyze import matches
    for case, (readme, routes, expected) in ANALYST_CASES.items():
        assert expected and all(p in readme for _, p in expected), case
        assert not any(matches(routes, m, p) for m, p in expected), f"{case}: an expected feature already exists"
    assert _norm("/items/<id>/quantity/") == _norm("/items/{item_id}/quantity") == "/items/{}/quantity"
