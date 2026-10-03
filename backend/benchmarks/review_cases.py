"""Seeded diffs for the Reviewer benchmark. `defect_file` is the file a correct review must name; None means the diff is clean (expect PASS).

Automatic (static) findings are NOT given to the model here: the benchmark measures the model's own review, including false alarms.
"""
from __future__ import annotations

TODO_ACCEPTANCE = [
    "POST /api/todos returns 201 with id, title, description, priority",
    "POST with an empty title returns 400 {\"detail\": \"Title must not be empty\"}",
    "POST with an invalid priority returns 400 {\"detail\": \"Priority must be one of 'low', 'medium', 'high'\"}",
]

CASES = [
    {   # SQL built from user text
        "id": "sql-injection", "defect_file": "database/todos.py",
        "task": {"id": "t1", "title": "Implement todo data access functions", "owner": "database",
                 "acceptance": ["add_todo(title, description, priority) returns a dict with id, title, description, priority", "values are stored safely"]},
        "diff": '''diff --git a/database/todos.py b/database/todos.py
--- a/database/todos.py
+++ b/database/todos.py
@@ -6,3 +6,12 @@
 SCHEMA = "CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL);"
+
+
+def add_todo(title: str, description: str, priority: str) -> dict:
+    """Insert and return the new row"""
+    with connect(SCHEMA) as conn:
+        cur = conn.execute("INSERT INTO todos (title, description, priority) VALUES ('" + title + "', '" + description + "', '" + priority + "')")
+        row = conn.execute("SELECT id, title, description, priority FROM todos WHERE id = " + str(cur.lastrowid)).fetchone()
+        return dict(row)
''',
    },
    {   # innerHTML with user data
        "id": "xss-innerhtml", "defect_file": "static/app.js",
        "task": {"id": "t4", "title": "Write the page script", "owner": "frontend",
                 "acceptance": ["the list shows each todo's title and priority", "user text is shown safely"]},
        "diff": '''diff --git a/static/app.js b/static/app.js
--- a/static/app.js
+++ b/static/app.js
@@ -1,3 +1,14 @@
+const list = document.getElementById("list");
+
+async function loadTodos() {
+  const res = await fetch("/api/todos");
+  const data = await res.json();
+  list.innerHTML = "";
+  for (const item of data.items) {
+    list.innerHTML += "<li>" + item.title + " (" + item.priority + ")</li>";
+  }
+}
+
+loadTodos();
''',
    },
    {   # missing validation required by the acceptance criteria
        "id": "missing-validation", "defect_file": "backend/api/todos.py",
        "task": {"id": "t2", "title": "Implement the todos API router", "owner": "backend", "acceptance": TODO_ACCEPTANCE},
        "diff": '''diff --git a/backend/api/todos.py b/backend/api/todos.py
--- a/backend/api/todos.py
+++ b/backend/api/todos.py
@@ -14,6 +14,9 @@
 @router.post("/api/todos", status_code=201, response_model=PostTodosResponse)
 def handle_post_todos(req: PostTodosRequest):
     # Add a new todo
-    raise NotImplementedError
+    row = db.add_todo(title=req.title, description=req.description, priority=req.priority)
+    return row
''',
    },
    {   # eval on user input
        "id": "eval-input", "defect_file": "backend/api/calculator.py",
        "task": {"id": "t2", "title": "API router", "owner": "backend", "acceptance": ["POST /api/calculate returns 201 with the result", "dividing by zero returns 400"]},
        "diff": '''diff --git a/backend/api/calculator.py b/backend/api/calculator.py
--- a/backend/api/calculator.py
+++ b/backend/api/calculator.py
@@ -10,3 +10,8 @@
 @router.post("/api/calculate", status_code=201, response_model=PostCalculateResponse)
 def handle_post_calculate(req: PostCalculateRequest):
-    raise NotImplementedError
+    symbols = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}
+    if req.operation == "divide" and req.b == 0:
+        raise HTTPException(status_code=400, detail="Cannot divide by zero")
+    result = eval(f"{req.a} {symbols[req.operation]} {req.b}")
+    return db.add_calculation(req.a, req.b, req.operation, result)
''',
    },
    {   # clean database code
        "id": "clean-database", "defect_file": None,
        "task": {"id": "t1", "title": "Implement todo data access functions", "owner": "database",
                 "acceptance": ["add_todo(title, description, priority) returns a dict with id, title, description, priority", "values are stored safely"]},
        "diff": '''diff --git a/database/todos.py b/database/todos.py
--- a/database/todos.py
+++ b/database/todos.py
@@ -6,3 +6,14 @@
 SCHEMA = "CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL);"
+
+
+def add_todo(title: str, description: str, priority: str) -> dict:
+    """Insert and return the new row"""
+    with connect(SCHEMA) as conn:
+        cur = conn.execute("INSERT INTO todos (title, description, priority) VALUES (?, ?, ?)", (title, description, priority))
+        row = conn.execute("SELECT id, title, description, priority FROM todos WHERE id = ?", (cur.lastrowid,)).fetchone()
+        return dict(row)
+
+
+def list_todos() -> list[dict]:
+    """All rows, newest first"""
+    with connect(SCHEMA) as conn:
+        return [dict(r) for r in conn.execute("SELECT id, title, description, priority FROM todos ORDER BY id DESC")]
''',
    },
    {   # clean router with validation
        "id": "clean-router", "defect_file": None,
        "task": {"id": "t2", "title": "Implement the todos API router", "owner": "backend", "acceptance": TODO_ACCEPTANCE},
        "diff": '''diff --git a/backend/api/todos.py b/backend/api/todos.py
--- a/backend/api/todos.py
+++ b/backend/api/todos.py
@@ -14,6 +14,12 @@
 @router.post("/api/todos", status_code=201, response_model=PostTodosResponse)
 def handle_post_todos(req: PostTodosRequest):
     # Add a new todo
-    raise NotImplementedError
+    if not req.title.strip():
+        raise HTTPException(status_code=400, detail="Title must not be empty")
+    if req.priority not in ["low", "medium", "high"]:
+        raise HTTPException(status_code=400, detail="Priority must be one of 'low', 'medium', 'high'")
+    return db.add_todo(title=req.title, description=req.description, priority=req.priority)
''',
    },
    {   # clean frontend script
        "id": "clean-script", "defect_file": None,
        "task": {"id": "t4", "title": "Write the page script", "owner": "frontend",
                 "acceptance": ["the list shows each todo's title and priority", "user text is shown safely"]},
        "diff": '''diff --git a/static/app.js b/static/app.js
--- a/static/app.js
+++ b/static/app.js
@@ -1,3 +1,16 @@
+const list = document.getElementById("list");
+
+async function loadTodos() {
+  const res = await fetch("/api/todos");
+  const data = await res.json();
+  list.textContent = "";
+  for (const item of data.items) {
+    const li = document.createElement("li");
+    li.textContent = item.title + " (" + item.priority + ")";
+    list.appendChild(li);
+  }
+}
+
+loadTodos();
''',
    },
]
