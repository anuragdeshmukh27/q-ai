"""The example chips in the UI and the goals the scripts build must be the same list."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ui_chips_match_scripts_goals():
    sys.path.insert(0, str(ROOT / "scripts"))
    from goals import CHIPS

    ts = (ROOT / "frontend" / "src" / "examples.ts").read_text(encoding="utf-8")
    found = re.findall(r"label: '([^']+)', goal: '([^']+)'", ts)
    assert found == CHIPS
    assert all(len(goal.split()) > 12 for _, goal in found), "chips are detailed goals"
