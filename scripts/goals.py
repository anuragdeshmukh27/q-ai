"""The goals the scripts build. CHIPS are the detailed example goals offered in the UI (frontend/src/examples.ts keeps the same list; only goals that built end to end are listed,
the habit tracker and quiz goals failed their one run and are not offered; the last four are the related-resource goals of P9a);
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

# Related resources (a parent and its children, votes, sort): the short goals a user would type, used for the P9a proof runs.
RELATED = [
    "Build a reddit replica",
    "Build a blog with comments",
    "Build a Q&A forum with answers and votes",
    "Build a project tracker where each project has tasks",
]

# Detailed versions of the same goals. All four built end to end (P9a), so they are appended to CHIPS below.
RELATED_DETAILED = [
    ("reddit replica", "Build a reddit-style forum: posts with title, content and author, comments on each post, upvote and downvote posts, sort by top or newest, edit and delete"),
    ("blog with comments", "Build a blog: posts with title, content and author, readers add comments to a post, edit and delete posts and comments"),
    ("Q&A forum", "Build a Q&A forum: questions with title, details and author, answers to each question, upvote questions and answers, sort by top or newest"),
    ("project tasks", "Build a project tracker: projects with name and description, tasks for each project with title and status To do/In progress/Done, edit and delete"),
]

CHIPS += RELATED_DETAILED
