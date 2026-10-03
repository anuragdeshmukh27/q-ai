"""The goals the scripts build. CHIPS are the detailed example goals offered in the UI (frontend/src/examples.ts keeps the same list; only goals that built end to end are listed,
the habit tracker and quiz goals failed their one run and are not offered);
SHORT are the original one-line goals the generality check and the earlier comparisons used."""

CHIPS = [
    ("calculator with history", "Build a calculator with history: add, subtract, multiply and divide two numbers, show the result, keep a history list, clear the history"),
    ("todo app", "Build a todo app: title, description, priority Low/Medium/High, due date, mark as done, filter by status, edit and delete"),
    ("expense tracker", "Build an expense tracker: description, amount, category Food/Transport/Housing/Fun/Other, date, total spent, filter by category, edit and delete"),
    ("notes app", "Build a notes app: title, content, tag Work/Personal/Ideas, search by text, edit and delete"),
    ("contact book", "Build a contact book: name, phone, email, group Family/Friends/Work, search by name, edit and delete"),
    ("inventory list", "Build an inventory list: item name, quantity, location Warehouse/Shop/Home, status In stock/Low/Out of stock, edit and delete"),
]

SHORT = [
    "Build a calculator with history",
    "Build a todo app with priorities",
    "Build an expense tracker with categories and totals",
    "Build a notes app with search",
    "Build a habit tracker",
    "Build a quiz app",
    "Build a contact book",
    "Build an inventory list",
]
