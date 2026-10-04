"""Scope guard: what Q can build with the fastapi-vanilla preset, decided from the goal text alone, before any model work.

- impossible: the core of the goal is something this preset cannot make (a game to play, a charting tool, a native app): refuse, with working examples.
- mvp: the goal asks for more than fits (login, real-time, uploads, payments): build the small version and say what was left out.
- in scope: build it.
Rules, not a model, because the refusal has to be instant and the same every time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EXAMPLE_GOALS = [
    "Build a todo app with priorities and due dates",
    "Build a blog with posts and comments",
    "Build a Q&A forum with questions, answers and votes",
]

# What a goal may mention that this version leaves out: (pattern, label shown to the user)
LEFT_OUT = [
    (re.compile(r"\b(log ?in|sign ?(?:up|in)|authenticat\w*|authori[sz]\w*|accounts?|passwords?|oauth|user profiles?)\b", re.I), "login and accounts"),
    (re.compile(r"\b(real[- ]?time|live updates?|websockets?|notifications?|chat)\b", re.I), "real-time updates"),
    (re.compile(r"\b(uploads?|uploading|images?|photos?|pictures?|attachments?|avatars?)\b", re.I), "uploads and images"),
    (re.compile(r"\b(payments?|checkout|stripe|paypal|billing|subscriptions?|shopping cart)\b", re.I), "payments"),
    (re.compile(r"\b(charts?|graphs?|plots?)\b", re.I), "charts"),
]

_GAME_TITLES = r"snake|tetris|chess|checkers|pong|minesweeper|sudoku|tic[- ]?tac[- ]?toe|flappy|2048|wordle|platformer|shooter|arcade|hangman|solitaire|pacman|pac-man"
_GAME_BUT_DATA = r"tracker|list|library|collection|catalog|catalogue|inventory|log|scores?|reviews?|wishlist|backlog|database|store|shop|stats"
# (pattern, what it is). A pattern only counts when the goal is about building the thing itself.
IMPOSSIBLE = [
    (re.compile(rf"\b({_GAME_TITLES})\b", re.I), "a game that is played in the browser"),
    (re.compile(r"\b(?:video|board|card|puzzle|computer|2d|3d|multiplayer|browser|platform|arcade) game\b", re.I), "a game that is played in the browser"),
    (re.compile(r"\b(?:build|make|create|develop|design|code|write)\b(?: me)?(?: an?| the)?(?: [\w-]+){0,4} games?\b", re.I), "a game that is played in the browser"),  # 'a 3D cab racing game'
    (re.compile(r"\b(?:android|ios|iphone|ipad|mobile|native|desktop|windows|mac|electron|flutter|react native) (?:app|application)\b", re.I), "a native or mobile app"),
    (re.compile(r"\b(?:chart|graph|plot|visuali[sz]ation)s? (?:app|maker|tool|builder|generator|dashboard)\b|\bdashboard (?:of|with|showing) (?:charts?|graphs?)\b", re.I), "a charting or visualisation tool"),
    (re.compile(r"\b(?:3d|ar|vr|augmented reality|virtual reality)\b (?:app|viewer|model|scene|editor)|\b(?:video|audio|photo|image) (?:editor|player|streaming|encoder)\b|\b(?:machine learning|neural network|ai model|chatbot|image recognition)\b", re.I), "media editing or machine learning"),
]
_BUILD_VERB = re.compile(r"\b(build|make|create|develop|design|write|code|want|need)\b", re.I)


@dataclass
class Scope:
    level: str = "in_scope"  # in_scope | mvp | impossible
    left_out: list[str] = field(default_factory=list)
    message: str = ""  # the friendly refusal, only for "impossible"
    what: str = ""


def refusal(goal: str, what: str) -> str:
    examples = "; ".join(f'"{g}"' for g in EXAMPLE_GOALS)
    return (f"Q builds small web apps that store data (lists, forms, comments, votes), so it cannot build {what}. "
            f"Try a goal like these instead: {examples}.")


def classify_goal(goal: str) -> Scope:
    text = goal.strip()
    for pattern, what in IMPOSSIBLE:
        m = pattern.search(text)
        if not m:
            continue
        if "game" in what and re.search(rf"\b({_GAME_BUT_DATA})\b", text, re.I):
            continue  # a game score tracker or game library is a data app
        if "game" in what and not (_BUILD_VERB.search(text) or len(text.split()) <= 4):
            continue
        return Scope("impossible", message=refusal(text, what), what=what)
    left: list[str] = []
    for pattern, label in LEFT_OUT:
        if pattern.search(text) and label not in left:
            left.append(label)
    return Scope("mvp" if left else "in_scope", left_out=left)
