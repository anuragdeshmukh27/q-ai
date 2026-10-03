"""The scope guard: refuse what the preset cannot build before any model work, say what is left out of a bigger goal."""
import sys
from pathlib import Path

import pytest

from app.scope import EXAMPLE_GOALS, classify_goal

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("goal", [
    "Build a reddit replica", "Build a blog with comments", "Build a Q&A forum with answers and votes", "Build a project tracker where each project has tasks",
    "Build a calculator with history", "Build a todo app", "Build a contact book: name, phone, email, group Family/Friends/Work, search by name, edit and delete",
    "Build a game score tracker", "Build a board game library with ratings", "Track my video game backlog", "Build a notes app with search",
])
def test_data_apps_are_in_scope(goal):
    s = classify_goal(goal)
    assert s.level == "in_scope" and not s.left_out, (goal, s)


@pytest.mark.parametrize("goal", [
    "Build a snake game", "make me a tetris clone", "Build a chess game", "Build a multiplayer game", "Build an Android app for tracking steps",
    "Build a mobile app that tracks habits", "Build a bar chart maker", "Build a dashboard with charts", "Build a video editor", "Build a machine learning model",
])
def test_things_this_preset_cannot_make_are_refused_with_working_examples(goal):
    s = classify_goal(goal)
    assert s.level == "impossible", goal
    assert all(g in s.message for g in EXAMPLE_GOALS) and len(EXAMPLE_GOALS) == 3
    assert "cannot build" in s.message


@pytest.mark.parametrize("goal,left", [
    ("Build a reddit replica with login and subreddits", "login and accounts"),
    ("Build a blog with user accounts", "login and accounts"),
    ("Build a shop with payments and checkout", "payments"),
    ("Build a todo app with real-time sync", "real-time updates"),
    ("Build a gallery with image uploads", "uploads and images"),
    ("Build an expense tracker with charts", "charts"),
])
def test_bigger_goals_are_built_small_and_say_what_is_left_out(goal, left):
    s = classify_goal(goal)
    assert s.level == "mvp" and left in s.left_out, (goal, s)


def test_example_goals_are_in_scope_and_the_chips_stay_in_scope():
    sys.path.insert(0, str(ROOT / "scripts"))
    from goals import CHIPS, RELATED

    for g in [*EXAMPLE_GOALS, *(goal for _, goal in CHIPS), *RELATED]:
        assert classify_goal(g).level != "impossible", g
    assert all(not classify_goal(goal).left_out for _, goal in CHIPS), "a proven chip must not get a 'not in this version' note"


def test_the_api_refuses_before_any_model_work(tmp_path):
    from api_helpers import make_client

    client, _, mgr = make_client(tmp_path)
    r = client.post("/api/projects", json={"goal": "Build a snake game"})
    assert r.status_code == 422 and EXAMPLE_GOALS[0] in r.json()["detail"]
    assert not mgr.sessions, "no project is created for a refused goal"


def test_an_author_field_is_not_a_login():
    assert classify_goal("Build a blog: posts with title, content and author").level == "in_scope"
    assert classify_goal("Build an app with user authentication").left_out == ["login and accounts"]
