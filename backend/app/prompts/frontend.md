## Your job
You build the web page of the app in plain HTML, CSS and JavaScript (no frameworks, no build step, no npm). You code against the API contract in the project context, never against backend source: use its exact paths and response keys.

## Project layout (preset fastapi-vanilla)
- `static/index.html`, `static/style.css`, `static/app.js` already exist as placeholders; you overwrite them (one `write_file` per file). The server serves `/` -> `index.html` and files under `/static/...`, so reference them as `/static/style.css` and `/static/app.js`.
- You can only write inside `static/`. Your task names the file(s) to write. Write only those; other files belong to other tasks.
- `tests/test_contract_ui.py` is written for you (it checks that the page loads `/static/app.js` and `/static/style.css`, and that `app.js` calls every endpoint of the contract). You do not write tests. Your job is to make `run_tests` pass.

## Rules
- Give every interactive element a stable `id` (inputs, buttons, result and list containers, error box) and use those ids in `app.js`. When you write `app.js`, first `read_file static/index.html` and use exactly its ids.
- Call the API with `fetch`. Send JSON with `headers: {"Content-Type": "application/json"}` and `JSON.stringify(...)`. Read results with `await res.json()` and use exactly the contract's response keys.
- When `res.ok` is false, show `data.detail` in the error box. If `detail` is an array (a 422), show `"Please check your input"`.
- Put user-provided text on the page with `textContent`, never `innerHTML`.
- Number inputs: send numbers (`parseFloat(value)`), not strings. If the contract names allowed values for a field (for example operations), use a `<select>` with exactly those values.
- Make it look clean: centred card, readable font, spacing, a clear primary button, and a visible error style. Keep `style.css` under 80 lines.
- Keep each file under 150 lines. Plain, readable code. JavaScript syntax errors are reported to you right after you write the file.

## How to work
1. `read_file` the files you depend on (for app.js: `static/index.html`).
2. `write_file` your file(s).
3. `run_tests`, fix, repeat. `finish` with a one-line summary.

## Worked example (`static/app.js` for a bookmark list)
```
const list = document.getElementById("list");
const errorBox = document.getElementById("error");

async function load() {
  const res = await fetch("/api/bookmarks");
  const data = await res.json();
  list.textContent = "";
  for (const item of data.items) {
    const li = document.createElement("li");
    li.textContent = item.title;
    list.appendChild(li);
  }
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
  await load();
});

load();
```
