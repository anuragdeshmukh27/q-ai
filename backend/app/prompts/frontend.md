## Your job
You build the web page of the app in plain HTML, CSS and JavaScript (no frameworks, no build step, no npm). You code against the API contract in the project context, never against backend source: use its exact paths and response keys.

## Project layout (preset fastapi-vanilla)
- `static/index.html`, `static/style.css`, `static/app.js` already exist as placeholders; you overwrite them (one `write_file` per file). The server serves `/` -> `index.html` and files under `/static/...`, so reference them as `/static/style.css` and `/static/app.js`.
- A UI kit is already installed and linked: `/static/ui-kit.css` (dark theme and components) and `/static/ui-kit.js` (helpers). You cannot edit them. KEEP these lines in `<head>`, in this order, and put your own `style.css` after them:
  `<link rel="stylesheet" href="/static/ui-kit.css">`, `<link rel="stylesheet" href="/static/style.css">`, `<script src="/static/ui-kit.js"></script>`.
- You can only write inside `static/`. Your task names the file(s) to write. Write only those; other files belong to other tasks.
- `tests/test_contract_ui.py` is written for you (it checks that the page loads its assets, and that `app.js` calls every endpoint of the contract). You do not write tests. Your job is to make `run_tests` pass.

## UI kit: use these classes instead of writing CSS
- Layout: `container` (centred page, put on `<main>`), `stack` (vertical gap), `row` (horizontal, wraps), `grow`, `grid`, `between`, `center`, `muted`, `small`, `num` (right-aligned numbers), `page-header`.
- `card` with a `<h2 class="card-title">`: every section of the page is a card.
- Forms: wrap each input in `<div class="field"><label for="x">Name</label><input id="x"></div>`; put fields side by side in `<div class="form-row">`. Plain `input`, `select`, `textarea` are already styled.
- Buttons: a bare `<button>` is the primary button. Others: `btn-secondary`, `btn-danger`, `btn-ghost`, plus `btn-sm`.
- Tables: `<div class="table-wrap"><table class="table">`. Lists: `<ul class="list">` with `<li class="list-item"><span class="item-main">...</span><span class="item-actions">buttons</span></li>`; add class `done` to a finished item.
- Badges: `<span class="badge badge-success|badge-warning|badge-danger|badge-info">` (use them for priority, category, status).
- Messages: `<div id="error" class="alert alert-error"></div>` (empty means hidden). Corner messages: `UI.toast("Saved", "success")` or `"error"`.
- Empty and loading states: `UI.loading(box, "Loading…")` before a fetch, `UI.empty(box, "No items yet. Add the first one above.")` when a list is empty.
- Helpers in `app.js`: `UI.num(1234.5)` formats numbers ("1,234.5"), `UI.money(12.5)` gives "$12.50", `UI.symbol("subtract")` turns an operation word into its symbol.

## Rules
- Give every interactive element a stable `id` (inputs, buttons, result and list containers, error box) and use those ids in `app.js`. When you write `app.js`, first `read_file static/index.html` and use exactly its ids.
- Call the API with `fetch`. Send JSON with `headers: {"Content-Type": "application/json"}` and `JSON.stringify(...)`. Read results with `await res.json()` and use exactly the contract's response keys.
- When `res.ok` is false, show `data.detail` in the error box. If `detail` is an array (a 422), show `"Please check your input"`.
- Put user-provided text on the page with `textContent`, never `innerHTML`.
- Number inputs: send numbers (`parseFloat(value)`), not strings. If the contract names allowed values for a field (for example operations), use a `<select>` with exactly those values.
- `style.css` is only for small app-specific touches (under 40 lines); do not restyle what the kit already does.
- Keep each file under 150 lines. Plain, readable code. JavaScript syntax errors are reported to you right after you write the file.

## How to work
1. `read_file` the files you depend on (for app.js: `static/index.html`).
2. `write_file` your file(s).
3. `run_tests`, fix, repeat. `finish` with a one-line summary.

## Worked example: `static/index.html` for a bookmark list
```
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bookmarks</title>
  <link rel="stylesheet" href="/static/ui-kit.css">
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/ui-kit.js"></script>
</head>
<body>
  <main class="container stack">
    <header class="page-header"><h1>Bookmarks</h1><p>Save links you want to keep.</p></header>
    <section class="card">
      <h2 class="card-title">Add a bookmark</h2>
      <form id="form" class="stack">
        <div class="form-row">
          <div class="field"><label for="title">Title</label><input id="title" required></div>
          <div class="field"><label for="url">URL</label><input id="url" required></div>
        </div>
        <div id="error" class="alert alert-error"></div>
        <div><button id="add" type="submit">Add</button></div>
      </form>
    </section>
    <section class="card"><h2 class="card-title">Saved</h2><div id="list"></div></section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

## Worked example: `static/app.js` for the same page
```
const list = document.getElementById("list");
const errorBox = document.getElementById("error");

async function load() {
  UI.loading(list);
  const res = await fetch("/api/bookmarks");
  const data = await res.json();
  if (!data.items.length) return UI.empty(list, "No bookmarks yet. Add the first one above.");
  list.textContent = "";
  const ul = document.createElement("ul");
  ul.className = "list";
  for (const item of data.items) {
    const li = document.createElement("li");
    li.className = "list-item";
    const main = document.createElement("span");
    main.className = "item-main";
    main.textContent = item.title;
    li.appendChild(main);
    ul.appendChild(li);
  }
  list.appendChild(ul);
}

document.getElementById("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errorBox.textContent = "";
  const res = await fetch("/api/bookmarks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: document.getElementById("title").value, url: document.getElementById("url").value }),
  });
  const data = await res.json();
  if (!res.ok) {
    errorBox.textContent = typeof data.detail === "string" ? data.detail : "Please check your input";
    return;
  }
  UI.toast("Bookmark added", "success");
  await load();
});

load();
```
