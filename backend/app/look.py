"""How a generated app looks: a theme, a layout, an icon and a subtitle, chosen by rules.

The model never writes page layouts: it cannot do it reliably (a 7B rewrites the page and breaks it), and every variant here is hand-made and tested.
So the choice is deterministic, from the goal text and from the shape of the data:
- theme: counted from keywords of the goal (the app's name counts three times, the fields and options once), finance = green, notes = warm paper,
  inventory = industrial, social = orange, food = red, health = teal; anything else keeps the default;
- layout: a feed with a detail view for parent -> child apps, a calculator panel for computed apps, a compact checklist when there is a yes/no field,
  a table when there are numbers, otherwise a card grid;
- icon and subtitle: an emoji from the keywords, and the spec's summary as one line.
The CSS of every theme and layout lives in the locked UI kit (`ui-kit.css`); the page only names them (`data-theme`, `layout-*` classes).
"""
from __future__ import annotations

import re

from .schemas import ArchitectOutput, Look, SpecOutput

THEMES = ("default", "finance", "paper", "industrial", "social", "food", "health")
LAYOUTS = ("table", "cards", "checklist", "calculator", "feed", "shell")

# (theme, keywords): the first theme with the most hits wins a tie
THEME_WORDS: list[tuple[str, str]] = [
    ("food", r"restaurants?|food|recipes?|meals?|menu|cook\w*|dish\w*|cafe|zomato|swiggy|pizza|diet|grocer\w*|kitchen|dining|chef"),
    ("health", r"hospitals?|patients?|doctors?|health\w*|medical|medicine|clinics?|fitness|workouts?|habits?|wellness|gym|sleep|symptoms?|nurse|therapy|appointments?"),
    ("finance", r"expenses?|budgets?|money|finance\w*|bank\w*|invoices?|payments?|income|salary|spend\w*|wallet|savings?|accounting|ledger|loans?|bills?|cash"),
    ("industrial", r"inventory|stock|warehouse|assets?|equipment|suppliers?|machines?|parts|uber|rides?|trips?|drivers?|vehicles?|fleet|delivery|logistics|shipments?|tickets?|maintenance|repairs?"),
    ("paper", r"notes?|journal|diary|books?|library|bookmarks?|wiki|reading|poems?|essays?|contacts?|address book|recipes? book|notebook"),
    ("social", r"instagram|twitter|reddit|forum|blog|posts?|comments?|social|feed|youtube|videos?|linkedin|whatsapp|chat|messages?|q&a|questions?|answers?|amazon|shop|store|products?|reviews?|likes?|followers?|tweets?"),
]
_THEME_RES = [(t, re.compile(rf"\b(?:{w})\b", re.I)) for t, w in THEME_WORDS]

# (emoji, keywords): the first match wins, so the specific words come first
ICONS: list[tuple[str, str]] = [
    ("📸", r"instagram|photos?|gallery"), ("🐦", r"twitter|tweets?"), ("🛒", r"amazon|shop\w*|store|cart"), ("🍽️", r"zomato|swiggy|restaurants?|menu|dining"),
    ("▶️", r"youtube|videos?"), ("💼", r"linkedin|jobs?|careers?"), ("💬", r"whatsapp|chats?|messages?|messenger"), ("🚗", r"uber|rides?|taxi|cabs?|trips?"),
    ("🏥", r"hospitals?|patients?|clinics?|medical"), ("👤", r"contacts?|address book|contact book"), ("📚", r"library|books?"), ("🧮", r"calculator"), ("💰", r"expenses?|budgets?|money|finance|bank|savings?"),
    ("✅", r"todos?|to-do|tasks? list|checklist"), ("📝", r"notes?|notebook|journal|diary"), ("📦", r"inventory|stock|warehouse"),
    ("🔖", r"bookmarks?"), ("🍕", r"food|recipes?|meals?|pizza|cook\w*"), ("🏋️", r"fitness|workouts?|gym"), ("🌱", r"habits?"), ("🧠", r"quiz|trivia"),
    ("🗂️", r"projects?|kanban"), ("❓", r"q&a|questions?|answers?"), ("📰", r"blog|articles?|news"), ("🔥", r"reddit|forum|threads?"), ("🗓️", r"events?|calendar|schedule"),
]
_ICON_RES = [(e, re.compile(rf"\b(?:{w})\b", re.I)) for e, w in ICONS]
_LAYOUT_ICON = {"table": "📊", "cards": "🗃️", "checklist": "✅", "calculator": "🧮", "feed": "💬"}
_MONEY = re.compile(r"amount|price|cost|total|balance|spent|fee|salary|budget", re.I)
_AVERAGE = re.compile(r"rating|score|stars?|grade", re.I)


def _hits(rx: re.Pattern[str], text: str) -> int:
    return len({m.group(0).lower() for m in rx.finditer(text)})


def choose_theme(goal: str, title: str = "", resources: list[str] | None = None) -> str:
    """The theme whose keywords the goal mentions most: the name of the app (the words before the first colon, the title and the resources) counts three times."""
    head, _, rest = goal.partition(":")
    main = " ".join([head, title, *(resources or [])]).replace("_", " ")
    best, best_score = "default", 0
    for theme, rx in _THEME_RES:
        score = 3 * _hits(rx, main) + _hits(rx, rest)
        if score > best_score:
            best, best_score = theme, score
    return best


def is_feed(design: ArchitectOutput) -> bool:
    """Related resources, votes or other one-click actions: posts with an open item. A plain single resource built by rules (Uber) is a table or cards instead."""
    return any(r.parent or r.counters or r.flags for r in design.resources)


def choose_layout(design: ArchitectOutput) -> str:
    """From the data: related resources -> feed, a computed result -> calculator, a yes/no field -> checklist, numbers -> table, else cards."""
    if is_feed(design):
        return "feed"
    from .uistub import Shape  # the page shape of a single resource

    s = Shape(design)
    if not s.ok:
        return "cards"
    if s.calculator:  # a calculator has no text of its own; a server-assigned status next to a rider's name does not make a calculator
        return "calculator"
    if s.booleans:
        return "checklist"
    if s.numbers:
        return "table"
    return "cards"


def choose_icon(goal: str, title: str, layout: str, resources: list[str] | None = None) -> str:
    head, _, _ = goal.partition(":")
    text = " ".join([head, title, *(resources or [])]).replace("_", " ")
    for emoji, rx in _ICON_RES:
        if rx.search(text):
            return emoji
    return _LAYOUT_ICON.get(layout, "✨")


def subtitle_of(spec: SpecOutput | None, title: str) -> str:
    """The first sentence of the spec's summary, as one short line."""
    text = (spec.summary if spec else "").strip()
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s+", text)[0].rstrip(".")
    if len(first) > 110:
        first = first[:107].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return first


SKIN_OF_THEME = {"default": "studio", "finance": "ledger", "paper": "academy", "industrial": "depot", "social": "community", "food": "kitchen", "health": "clinic"}
_RUPEE = re.compile(r"rupees?|\brs\b\.?|₹|\binr\b|\blakh|\bcrore", re.I)
_DOLLAR = re.compile(r"dollars?|\$|\busd\b", re.I)


def detect_currency(goal: str, skill_currency: str = "") -> str:
    """Rupees or dollars named in the goal win; else the skill pack's; else dollars (the kit's old default)."""
    if _RUPEE.search(goal):
        return "INR"
    if _DOLLAR.search(goal):
        return "USD"
    return skill_currency or "USD"


def shell_applies(design: ArchitectOutput) -> bool:
    """Every app with a dashboard-worthy list gets the multi-page shell; a calculator (a computed result, no list of things) keeps its panel."""
    from .schemas import shell_enabled

    if not shell_enabled():
        return False
    if design.resources:
        return True
    from .uistub import Shape

    s = Shape(design)
    return s.ok and not s.calculator


def choose_look(goal: str, spec: SpecOutput | None, design: ArchitectOutput) -> Look:
    from .skills import pack

    layout = "shell" if shell_applies(design) else choose_layout(design)
    title = spec.title if spec else ""
    names = [r.name for r in design.resources] or [t.name for t in design.tables]
    theme = choose_theme(goal, title, names)
    skill = spec.skill if spec else ""
    p = pack(skill) or {}
    return Look(theme=theme, layout=layout, icon=p.get("icon") or choose_icon(goal, title, layout, names), subtitle=subtitle_of(spec, title),
                not_included=list(spec.not_included) if spec else [], skill=skill, skin=p.get("skin") or SKIN_OF_THEME.get(theme, "studio"),
                currency=detect_currency(goal, p.get("currency", "")))


def look_of(design: ArchitectOutput) -> Look:
    """The design's look, or one computed on the spot for a design that predates it (tests, old projects)."""
    return design.look or Look(theme="default", layout=choose_layout(design))
