"""The example chips in the UI and the goals the scripts build must be the same list."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ui_chips_match_scripts_goals():
    sys.path.insert(0, str(ROOT / "scripts"))
    from goals import CHIPS

    ts = (ROOT / "frontend" / "src" / "examples.ts").read_text(encoding="utf-8")
    found = re.findall(r"label: '([^']+)', goal: '([^']+)'", ts.split("export const FAMOUS")[0])
    assert found == CHIPS
    assert all(len(goal.split()) > 12 for _, goal in found), "chips are detailed goals"


def test_famous_app_chips_match_scripts_goals_and_all_map_to_a_platform():
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "backend"))
    from goals import FAMOUS
    from app.platforms import match_platform

    ts = (ROOT / "frontend" / "src" / "examples.ts").read_text(encoding="utf-8")
    found = re.findall(r"label: '([^']+)', goal: '([^']+)'", ts.split("export const FAMOUS")[1])
    assert found == FAMOUS
    assert all(match_platform(goal) is not None for _, goal in FAMOUS), "every famous-app chip is a short goal that maps to a hand-written spec"
