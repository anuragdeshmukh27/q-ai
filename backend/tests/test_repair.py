"""The contract repair: the bodies the engineer should have written, generated from the resource model, pass every generated test of every famous app."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.contract_tests import api_test_source, edge_test_source
from app.platforms import PLATFORMS
from app.relation_tests import db_test_source
from app.relations import endpoints_for_resource, synthesize_design
from app.scaffold import db_stub, route_stub
from app.schemas import SpecOutput, normalize_spec

SKELETON = Path(__file__).resolve().parents[1] / "app" / "presets" / "fastapi_vanilla" / "skeleton"


def filled_project(tmp_path, design):
    root = tmp_path / "app"
    shutil.copytree(SKELETON, root)
    for sub in ("tests/api", "tests/db", "tests/qa"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "backend" / "api").mkdir(parents=True, exist_ok=True)
    for r in design.resources:
        (root / "tests" / "api" / f"test_contract_{r.name}.py").write_text(api_test_source(design, r.name), encoding="utf-8")
        (root / "tests" / "db" / f"test_{r.name}.py").write_text(db_test_source(design, r), encoding="utf-8")
        (root / "database" / f"{r.name}.py").write_text(db_stub(design, r.name, fill=True), encoding="utf-8")
        (root / "backend" / "api" / f"{r.name}.py").write_text(
            route_stub(design, endpoints_for_resource(design, r.name), r.name, (r.parent,) if r.parent else (), fill=True), encoding="utf-8")
    (root / "tests" / "qa" / "test_edge_cases.py").write_text(edge_test_source(design), encoding="utf-8")
    return root


@pytest.mark.parametrize("key,words,spec", PLATFORMS)
def test_the_generated_bodies_pass_every_generated_test_of_the_app(key, words, spec, tmp_path):
    design = synthesize_design(normalize_spec(SpecOutput.model_validate(spec), "Build " + key))
    root = filled_project(tmp_path, design)
    for r in design.resources:
        for path in (root / "database" / f"{r.name}.py", root / "backend" / "api" / f"{r.name}.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            assert "NotImplementedError" not in path.read_text(encoding="utf-8"), path.name
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "--tb=short"], cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout[-2500:]


def test_without_fill_the_stubs_are_unchanged():
    design = synthesize_design(normalize_spec(SpecOutput.model_validate(PLATFORMS[0][2]), "Build Instagram"))
    assert "NotImplementedError" in db_stub(design, "posts") and "NotImplementedError" in route_stub(design, endpoints_for_resource(design, "posts"), "posts")
