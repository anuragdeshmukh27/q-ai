"""Path sandbox: traversal, absolute paths, symlinks/junctions, .git, ownership."""
import os
import subprocess
import sys

import pytest

from app.sandbox.paths import PathPolicy, SandboxError


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "wt"
    (r / "backend").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / ".q").mkdir()
    (r / ".git").mkdir()
    (r / "backend" / "main.py").write_text("x = 1\n")
    (r / ".git" / "config").write_text("[core]\n")
    (tmp_path / "secret.txt").write_text("outside")
    return r


@pytest.fixture()
def policy(root):
    return PathPolicy(root, owned=["backend/**", "static/**"], forbidden=["tests/**", ".q/**"])


TRAVERSAL = [
    "../secret.txt",
    "..\\secret.txt",
    "backend/../../secret.txt",
    "backend\\..\\..\\secret.txt",
    "a/b/../../../secret.txt",
    "./../secret.txt",
    "backend/./../../secret.txt",
    "....//secret.txt",
]


@pytest.mark.parametrize("p", TRAVERSAL)
def test_traversal_rejected_for_read_and_write(policy, p):
    with pytest.raises(SandboxError):
        policy.resolve_read(p)
    with pytest.raises(SandboxError):
        policy.resolve_write(p)


ABSOLUTE = [
    "C:\\Windows\\win.ini",
    "C:/Windows/win.ini",
    "c:secret.txt",
    "/etc/passwd",
    "\\Windows\\win.ini",
    "\\\\server\\share\\x.txt",
    "//server/share/x.txt",
    "\\\\?\\C:\\Windows\\win.ini",
    "~/x.txt",
]


@pytest.mark.parametrize("p", ABSOLUTE)
def test_absolute_paths_rejected(policy, p):
    with pytest.raises(SandboxError):
        policy.resolve_read(p)
    with pytest.raises(SandboxError):
        policy.resolve_write(p)


def test_absolute_path_inside_root_still_rejected(policy, root):
    # Agents must use relative paths; an absolute path is never accepted.
    with pytest.raises(SandboxError):
        policy.resolve_read(str(root / "backend" / "main.py"))


@pytest.mark.parametrize("p", ["", " ", ".", "backend/\x00x.py", "a\nb.py"])
def test_empty_dot_and_control_chars_rejected(policy, p):
    with pytest.raises(SandboxError):
        policy.resolve_write(p)


@pytest.mark.parametrize(
    "p",
    [
        "backend/main.py:stream",  # NTFS alternate data stream
        "backend/CON",
        "backend/nul.py",
        "backend/aux.txt",
        "backend/x.py.",  # trailing dot is stripped by Windows
        "backend/x.py ",  # trailing space is stripped by Windows
        "backend/<x>.py",
        "backend/a|b.py",
        "backend/a?.py",
        "backend/a*.py",
    ],
)
def test_windows_special_names_rejected(policy, p):
    with pytest.raises(SandboxError):
        policy.resolve_write(p)


def test_valid_relative_paths_resolve_inside_root(policy, root):
    assert policy.resolve_read("backend/main.py") == (root / "backend" / "main.py").resolve()
    assert policy.resolve_read("backend\\main.py") == (root / "backend" / "main.py").resolve()
    assert policy.resolve_read("./backend/main.py") == (root / "backend" / "main.py").resolve()
    assert policy.resolve_read("backend/../backend/main.py") == (root / "backend" / "main.py").resolve()


# --- .git ------------------------------------------------------------------
@pytest.mark.parametrize(
    "p",
    [".git", ".git/config", ".GIT/config", "backend/../.git/config", ".git./config", ".git /config", "GIT~1/config"],
)
def test_git_dir_is_unreadable_and_unwritable(policy, p):
    with pytest.raises(SandboxError):
        policy.resolve_read(p)
    with pytest.raises(SandboxError):
        policy.resolve_write(p)


def test_nested_dot_git_rejected(policy):
    with pytest.raises(SandboxError):
        policy.resolve_read("backend/.git/config")


# --- ownership ---------------------------------------------------------------
def test_reads_allowed_project_wide(policy):
    policy.resolve_read("backend/main.py")
    policy.resolve_read("tests")  # forbidden for writes, readable
    policy.resolve_read(".q")


def test_write_inside_owned_ok(policy, root):
    assert policy.resolve_write("backend/app/routes.py") == (root / "backend" / "app" / "routes.py").resolve()
    policy.resolve_write("static/index.html")


@pytest.mark.parametrize("p", ["README.md", "frontend/x.js", "main.py", "backendx/y.py", "tests/test_a.py", ".q/tasks.json"])
def test_write_outside_owned_rejected(policy, p):
    with pytest.raises(SandboxError):
        policy.resolve_write(p)


@pytest.mark.parametrize("p", ["BACKEND/x.py", "Backend\\x.py"])
def test_ownership_match_is_case_insensitive_for_forbidden(root, p):
    # Windows is case-insensitive: Tests/x.py must not dodge forbidden "tests/**".
    pol = PathPolicy(root, owned=["**"], forbidden=["backend/**"])
    with pytest.raises(SandboxError):
        pol.resolve_write(p)


def test_forbidden_beats_owned(root):
    pol = PathPolicy(root, owned=["**"], forbidden=["tests/**"])
    with pytest.raises(SandboxError):
        pol.resolve_write("Tests/test_a.py")
    pol.resolve_write("backend/a.py")


def test_exact_file_glob(root):
    pol = PathPolicy(root, owned=[".q/tasks.json"], forbidden=[])
    pol.resolve_write(".q/tasks.json")
    with pytest.raises(SandboxError):
        pol.resolve_write(".q/other.json")


def test_star_does_not_cross_directories(root):
    pol = PathPolicy(root, owned=["backend/*.py"], forbidden=[])
    pol.resolve_write("backend/a.py")
    with pytest.raises(SandboxError):
        pol.resolve_write("backend/sub/a.py")


def test_empty_owned_means_no_writes(root):
    pol = PathPolicy(root, owned=[], forbidden=[])
    with pytest.raises(SandboxError):
        pol.resolve_write("backend/a.py")
    pol.resolve_read("backend/main.py")


# --- links out of the root -------------------------------------------------------
def _make_link_out(link, target):
    """Directory junction (no admin needed on Windows) or symlink elsewhere."""
    if sys.platform == "win32":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if r.returncode != 0:
            pytest.skip("cannot create junction")
    else:
        os.symlink(target, link, target_is_directory=True)


def test_link_pointing_outside_root_is_rejected(policy, root, tmp_path):
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "x.txt").write_text("hi")
    _make_link_out(root / "backend" / "escape", outside)
    with pytest.raises(SandboxError):
        policy.resolve_read("backend/escape/x.txt")
    with pytest.raises(SandboxError):
        policy.resolve_write("backend/escape/new.py")


def test_link_to_git_dir_is_rejected(policy, root):
    _make_link_out(root / "backend" / "g", root / ".git")
    with pytest.raises(SandboxError):
        policy.resolve_read("backend/g/config")
    with pytest.raises(SandboxError):
        policy.resolve_write("backend/g/config")


def test_root_itself_may_be_reached_via_a_link(tmp_path):
    # A root that is itself under a junction/symlink must still work.
    real = tmp_path / "real"
    (real / "backend").mkdir(parents=True)
    link = tmp_path / "linked"
    _make_link_out(link, real)
    pol = PathPolicy(link, owned=["backend/**"], forbidden=[])
    pol.resolve_write("backend/a.py")
