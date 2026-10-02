import subprocess
import time

import httpx
import psutil
import pytest

from app.ports import PortError, PortManager, port_is_free
from app.presets import list_presets, load_preset
from app.project import create_project, slugify
from app.sandbox.commands import ALLOW, CommandPolicy


def test_slugify_is_short_and_safe():
    assert slugify("Build a calculator with history!") == "build-a-calculator-with"
    assert len(slugify("x" * 100)) <= 24
    assert slugify("???") == "project"
    assert ".." not in slugify("../../etc")


def test_preset_loads():
    p = load_preset()
    assert p.name == "fastapi-vanilla" and "{port}" in p.run_cmd and p.skeleton.is_dir()
    assert "fastapi-vanilla" in list_presets()
    with pytest.raises(ValueError):
        load_preset("../../etc")


def test_preset_run_and_test_commands_pass_the_command_policy(tmp_path):
    p = load_preset()
    pol = CommandPolicy(tmp_path, extra_allowed=[p.run_cmd, p.test_cmd])
    assert pol.check(p.test_cmd).kind == ALLOW
    assert pol.check(p.run_cmd.replace("{port}", "9100")).kind == ALLOW


def test_create_project_makes_a_git_repo_with_skeleton(tmp_path):
    root = create_project("Build a calculator", base=tmp_path)
    assert root.parent == tmp_path and (root / "backend" / "main.py").is_file()
    assert (root / ".q" / "goal.md").read_text().strip().endswith("Build a calculator")
    log = subprocess.run(["git", "log", "--oneline"], cwd=root, capture_output=True, text=True).stdout
    assert "Initial skeleton" in log
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True).stdout.strip()
    assert branch == "main"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    assert status.strip() == ""
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout
    assert ".q/bugs/.gitkeep" in tracked


def test_create_project_slug_collision(tmp_path):
    a = create_project("Same goal", base=tmp_path)
    b = create_project("Same goal", base=tmp_path)
    assert a != b and b.name.endswith("-2")


def test_skeleton_tests_pass(tmp_path):
    root = create_project("skeleton check", base=tmp_path)
    import sys
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_port_manager_runs_and_stops_an_app(tmp_path):
    root = create_project("port check", base=tmp_path)
    p = load_preset()
    pm = PortManager()
    app = pm.start("p1", root, p.run_cmd, p.health_path)
    try:
        assert 9100 <= app.port <= 9199 and app.url == f"http://127.0.0.1:{app.port}"
        assert httpx.get(app.url + "/").status_code == 200
        assert pm.get("p1") == app
        assert not port_is_free(app.port)
        pid = app.pid
    finally:
        pm.stop("p1")
    time.sleep(0.5)
    assert pm.get("p1") is None
    assert port_is_free(app.port)
    assert not psutil.pid_exists(pid)


def test_two_projects_get_different_ports(tmp_path):
    p = load_preset()
    pm = PortManager()
    a = pm.start("a", create_project("app a", base=tmp_path), p.run_cmd)
    b = pm.start("b", create_project("app b", base=tmp_path), p.run_cmd)
    try:
        assert a.port != b.port
    finally:
        pm.stop_all()
    assert port_is_free(a.port) and port_is_free(b.port)


def test_start_fails_cleanly_when_the_app_crashes(tmp_path):
    root = create_project("crashy", base=tmp_path)
    (root / "backend" / "main.py").write_text("raise RuntimeError('boom')\n")
    pm = PortManager()
    with pytest.raises(PortError, match="exited"):
        pm.start("c", root, load_preset().run_cmd, timeout=15)
    assert pm.get("c") is None


def test_port_exhaustion(tmp_path):
    pm = PortManager(ports=range(0))
    with pytest.raises(PortError):
        pm.start("x", create_project("none", base=tmp_path), load_preset().run_cmd)
