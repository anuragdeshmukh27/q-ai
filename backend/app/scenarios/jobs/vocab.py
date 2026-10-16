"""The one vocabulary the job-description reader and the scoring emphasis share: skills, domains, role families, seniority cues, and the soft-skill phrases that point at a rubric criterion.

Nothing here is a model's opinion. The keyword reader (`extract.py`) and the weights (`adapt.py`) both read these tables, so a skill, a domain or an emphasis means the same thing
wherever it shows up, and a scenario's `fit` block (domain, skills) is written in this vocabulary.
"""
from __future__ import annotations

import re

# canonical skill name -> the spellings a job description uses for it (matched case-insensitively, as whole words)
SKILLS: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "django": ("django",),
    "java": ("java",),
    "spring": ("spring boot",),
    "go": ("golang",),
    "node.js": ("node.js", "nodejs"),
    "javascript": ("javascript", "ecmascript", "es6"),
    "typescript": ("typescript",),
    "react": ("react", "react.js", "reactjs"),
    "vue": ("vue", "vue.js"),
    "angular": ("angular",),
    "html": ("html", "html5"),
    "css": ("css", "css3", "sass", "tailwind"),
    "dom": ("dom",),
    "responsive design": ("responsive design", "responsive layouts", "responsive ui"),
    "accessibility": ("accessibility", "wcag", "a11y"),
    "rest api": ("rest api", "rest apis", "restful", "restful apis", "http api", "web api", "api design"),
    "graphql": ("graphql",),
    "sql": ("sql", "t-sql", "pl/sql"),
    "postgresql": ("postgresql", "postgres"),
    "mysql": ("mysql", "mariadb"),
    "sqlite": ("sqlite",),
    "mongodb": ("mongodb", "mongo"),
    "redis": ("redis",),
    "kafka": ("kafka",),
    "rabbitmq": ("rabbitmq",),
    "docker": ("docker", "containers"),
    "kubernetes": ("kubernetes", "k8s"),
    "aws": ("aws", "amazon web services"),
    "gcp": ("gcp", "google cloud"),
    "azure": ("azure",),
    "ci/cd": ("ci/cd", "continuous integration", "continuous delivery", "github actions", "jenkins"),
    "git": ("git", "github", "gitlab"),
    "linux": ("linux", "unix"),
    "microservices": ("microservices", "microservice"),
    "pytest": ("pytest",),
    "jest": ("jest", "vitest", "testing library"),
    "cypress": ("cypress", "playwright", "selenium"),
    "ui testing": ("ui testing", "end-to-end tests", "e2e tests", "component tests"),
    "database migrations": ("database migrations", "schema migrations", "migrations", "alembic", "flyway"),
    "indexing": ("indexing", "indexes", "index tuning", "query optimization", "query optimisation", "query tuning"),
    "data modeling": ("data modeling", "data modelling", "schema design", "database design", "normalization", "normalisation"),
    "etl": ("etl", "elt", "data pipelines", "data pipeline"),
    "airflow": ("airflow",),
    "spark": ("spark", "pyspark"),
    "dbt": ("dbt",),
    "snowflake": ("snowflake",),
    "bigquery": ("bigquery",),
    "data warehousing": ("data warehouse", "data warehousing", "data warehouses"),
    "error handling": ("error handling", "exception handling"),
    "debugging": ("debugging", "troubleshooting"),
    "monitoring": ("monitoring", "observability", "prometheus", "grafana", "datadog"),
}

# domain -> (the words that point at it, the one-line app Q would build for that domain: Part B's starting point)
DOMAINS: dict[str, tuple[tuple[str, ...], str]] = {
    "healthcare": (("healthcare", "health care", "hospital", "clinic", "clinical", "patient", "medical", "ehr", "pharma", "telehealth", "health"),
                   "An outpatient booking app: doctors, appointments, prescriptions and lab tests."),
    "fintech": (("fintech", "payment", "payments", "banking", "bank", "lending", "ledger", "trading", "brokerage", "card issuing", "insurance", "wallet"),
                "A payments service: accounts, transfers and a ledger with a transaction history."),
    "e-commerce": (("e-commerce", "ecommerce", "retail", "checkout", "storefront", "online store", "shopping", "marketplace", "merchants"),
                   "An online store: products, a cart, checkout and order tracking."),
    "education": (("education", "edtech", "students", "school", "university", "learning platform", "courses", "classroom"),
                  "A course platform: courses, enrolments, assignments and grades."),
    "logistics": (("logistics", "shipping", "freight", "fleet", "warehouse", "supply chain", "delivery", "last-mile"),
                  "A delivery tracker: shipments, drivers, routes and status updates."),
    "travel": (("travel", "airline", "hotel", "hospitality", "reservations", "tourism"),
               "A reservations app: listings, availability, bookings and cancellations."),
    "media": (("media", "streaming", "publishing", "podcast", "newsroom", "content platform"),
              "A content platform: articles, authors, subscriptions and comments."),
    "saas": (("saas", "b2b", "enterprise software", "crm", "workflow automation"),
             "A team workspace: accounts, projects, tasks and activity feeds."),
    "general software": ((), "A small task tracker: items, owners, due dates and status."),
}

FAMILIES = ("backend", "frontend", "database", "fullstack", "devops", "other")
SENIORITY = ("intern", "junior", "mid", "senior", "lead")

# role family -> phrases that name it. The first lines of a posting (the title) weigh more than the rest.
FAMILY_CUES: dict[str, tuple[str, ...]] = {
    "database": ("database engineer", "database developer", "database administrator", "dba", "data engineer", "sql developer", "analytics engineer", "data platform engineer", "etl developer"),
    "frontend": ("frontend", "front-end", "front end", "ui engineer", "ui developer", "react developer", "web developer"),
    "backend": ("backend", "back-end", "back end", "api engineer", "server-side", "python developer", "java developer", "platform engineer"),
    "fullstack": ("full-stack", "full stack", "fullstack"),
    "devops": ("devops", "site reliability", "sre", "infrastructure engineer", "cloud engineer"),
}
FAMILY_NAME = {"backend": "Backend engineer", "frontend": "Frontend engineer", "database": "Database engineer", "fullstack": "Full-stack engineer", "devops": "DevOps engineer", "other": "Software engineer"}

SENIORITY_CUES: dict[str, tuple[str, ...]] = {
    "intern": ("intern", "internship", "trainee"),
    "junior": ("junior", "entry level", "entry-level", "graduate"),
    "lead": ("lead", "principal", "staff engineer", "head of", "architect"),
    "senior": ("senior", "sr.", "sr "),
    "mid": ("mid-level", "mid level", "intermediate"),
}

# rubric criterion -> (the soft skill it stands for, the phrases in a job description that ask for it). The emphasis of the role fit and the soft skills the reader reports come from here.
SIGNALS: dict[str, tuple[str, tuple[str, ...]]] = {
    "communication": ("communication", ("communicat", "stakeholder", "cross-functional", "collaborat", "teamwork", "written", "explain", "document")),
    "diagnosis": ("debugging and root-cause analysis", ("debug", "troubleshoot", "root cause", "incident", "production issue", "performance", "observab", "monitoring", "diagnos")),
    "fix_quality": ("code quality", ("code review", "clean code", "maintainab", "best practice", "refactor", "readable", "design pattern", "technical debt", "high-quality", "quality code")),
    "testing": ("testing culture", ("testing", "unit test", "integration test", "tdd", "test-driven", "pytest", "jest", "automated test", "test coverage", "ci/cd", "quality assurance", "regression")),
    "ownership": ("ownership", ("ownership", "own the", "owning", "end-to-end", "on-call", "on call", "accountab", "self-starter", "autonom", "take initiative", "responsib")),
}
SOFT_SKILLS = tuple(label for label, _ in SIGNALS.values())

_PATTERNS: dict[str, re.Pattern] = {}


def phrase(p: str) -> re.Pattern:
    """A compiled case-insensitive pattern for a phrase of SIGNALS. A phrase starts at a word boundary; unless it is listed in `_WHOLE` it is a stem and also matches its longer forms
    ("communicat" matches communication, communicating)."""
    if p not in _PATTERNS:
        _PATTERNS[p] = re.compile(r"(?<![A-Za-z0-9])" + re.escape(p) + (r"(?![A-Za-z0-9])" if p in _WHOLE else ""), re.I)
    return _PATTERNS[p]


_WHOLE = {"tdd", "jest", "pytest", "document", "written", "explain", "performance", "own the", "owning", "on-call", "on call", "regression", "testing", "monitoring", "ci/cd", "incident"}


def find_skills(text: str) -> list[str]:
    """The canonical skills the text names, in the order they first appear."""
    found: list[tuple[int, str]] = []
    for name, aliases in SKILLS.items():
        first = min((m.start() for a in aliases if (m := re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", text, re.I))), default=None)
        if first is not None:
            found.append((first, name))
    return [name for _, name in sorted(found)]


def signal_hits(text: str) -> dict[str, list[str]]:
    """criterion id -> the distinct phrases of SIGNALS the text contains (empty list: the job description does not ask for it)."""
    return {cid: [p for p in phrases if phrase(p).search(text)] for cid, (_, phrases) in SIGNALS.items()}


def normalise_domain(value: str) -> str:
    """A domain as the vocabulary names it: an exact name, or the domain whose words the value contains; anything else is kept (lower case), so a new domain still shows."""
    v = " ".join(str(value).lower().split())
    if v in DOMAINS:
        return v
    for name, (words, _) in DOMAINS.items():
        if v == name.replace("-", "") or any(w in v for w in words):
            return name
    return v or "general software"
