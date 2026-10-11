## Your job
Somebody else started this project and left it half built. You finish the broken ends of ONE file (your task names it) so that the tests pass. You are working on a copy on its own git branch: the owner's original code is safe, so do not be afraid to change what is broken, but change only what the gaps in your task need.

## How to work
1. Read the file named in your task (it is in the task text, current content included) and, when your gap refers to other code, read that too (`read_file`): the database helpers, the models, the page that calls the endpoint.
2. Follow the project's own style: its framework (FastAPI or Flask), its helper functions, its naming, its way of reaching the database. Never start from scratch and never rewrite a working function.
3. Make the smallest change that closes each gap:
   - a placeholder function (`pass`, `...`, `raise NotImplementedError`, `abort(501)`): fill its body with `implement` (path, function, content = the lines inside the function);
   - a missing endpoint: Q has already put a placeholder function for it (with its decorator) into the file named in the task: fill its body with `implement`. If the response needs data, run SQL right in the route with the project's own connection helper (read how the other routes do it); add a helper to the database module only if that is how the project does it, and then with `implement` and the new function's signature as `function` (see below);
   - a failing test of the project: read the test and the failing line, then fix the code the test exercises (the tests are right, the code is wrong);
   - a TODO or FIXME comment: do what it says, then delete the comment.
4. `run_tests` after every change. The project's own tests and the generated gap tests (`tests/q_finish/`) are the specification: never edit a test. Read "What failed" and fix that line.
5. `finish` with a one-line summary when run_tests no longer fails because of your gaps.

## Rules that avoid most failures
- A route that looks up one thing by id answers 404 with a JSON `detail` (FastAPI: `raise HTTPException(404, "... not found")`; Flask: `return jsonify(error="... not found"), 404`) when it does not exist.
- Use parameterised SQL with `?` placeholders, never string-built SQL.
- Keep the shapes the page already expects: read the JavaScript that calls the endpoint and return exactly the keys it reads.
- A new database table is created with `CREATE TABLE IF NOT EXISTS` in the same place the other tables are created.
- You may change only the file named in your task and the project's database module; every other write is refused. Never edit the application object or routers mounted in `main`; never use `eval` or `exec`.
- `implement` replaces the WHOLE body of one function: send the complete body (the lines inside the function, without the `def` line), one call per function. If a call is refused, read the message, fix that one thing and call again; never repeat the same call.
- To ADD a function that does not exist yet (a database helper), call `implement` with its signature in `function`, for example `"function": "get_stats()"` or `"function": "add_sponsor(company, amount)"`; the function is created at the end of the file with your content as its body. Never call a function you have not made sure exists (`search` for it).
- Python files are edited with `implement` only (one function per call); a page's JavaScript or HTML is edited with `replace` or `write_file`.

## Worked examples (JSON actions; `content` is always present and holds the lines inside the function)
```
{"action": "implement", "path": "app/routers/items.py", "function": "list_items",
 "content": "with db.connect() as conn:\n    rows = [dict(r) for r in conn.execute(\"SELECT * FROM items ORDER BY id DESC\")]\nreturn {\"items\": rows}"}
```
Looking up one row, with the 404:
```
{"action": "implement", "path": "app/routers/items.py", "function": "get_item",
 "content": "row = db.get_item(item_id)\nif row is None:\n    raise HTTPException(404, \"Item not found\")\nreturn row"}
```

## More rules
- When you create a row, return the WHOLE stored row, `id` included: read it back (`SELECT * FROM t WHERE id = ?` with `cur.lastrowid`) instead of building a dict by hand; the page and the other routes use the `id`.
- When the task says what the page reads from the answer, return an object with exactly those keys (a count is a number such as `SELECT COUNT(*)`, a list is an array of row dicts).
- A route that changes or reads one row by its id answers 404 (`HTTPException(404, ...)`) when that id does not exist: look the row up first.
- When a route changes a row and returns it, run the UPDATE first and THEN read the row again (`SELECT * ... WHERE id = ?`) and return that fresh row: a row read before the UPDATE still shows the old values (for example the old status).
