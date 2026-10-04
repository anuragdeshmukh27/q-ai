// Q UI kit helpers (locked preset file, loaded on every page before app.js). Everything is on the global `UI`.
//   UI.toast("Saved", "success")      small message in the corner ("success" | "error" | "info")
//   UI.num(1234.5)  UI.money(12.5)    formatted numbers: "1,234.5" and "$12.50"
//   UI.symbol("subtract")             operation word -> symbol ("−"); unknown words come back unchanged
//   UI.loading(box, "Loading…")       spinner inside a container
//   UI.empty(box, "Nothing here yet") empty state inside a container
//   UI.renderList(box, items, build, "No items yet")   a whole list of items in ONE call (empty state included)
//   UI.listItem(item, options)        one list row; options (field names are keys of `item`):
//       title: "title"                main text
//       details: ["description"]      more fields, each on its own muted line
//       badges: ["priority"]          short categorical fields as coloured badges (High red, Medium amber, Low green, To do blue, In progress amber,
//                                     Done green; any other label gets its own steady colour)
//       formats: { amount: "money" }  per-field format: "money" | "num" | "symbol" | "stars" (a 1-5 rating as ★★★☆☆)
//       done: "done"                  boolean field: strikes the row through when true
//       onToggle: (checked) => ...    with `done`: shows a checkbox at the start of the row; called with the new state
//       values: ["amount"]            numbers shown on the right of the row, each captioned with its label (formats applies)
//       labels: { phone: "Phone" }    a detail line reads "Phone: 555-1234"; a value is captioned with its label
//       actions: [{ label: "Delete", kind: "danger", onClick: () => remove(item.id) }]   buttons ("danger" | "secondary" | "ghost")
//   The same options drive every layout; pick one by the shape of the data:
//   UI.renderList(box, items, build, empty)       one row per item (default)
//   UI.renderChecklist(box, items, build, empty)  compact rows to tick off (a yes/no field with onToggle)
//   UI.renderCards(box, items, build, empty)      a grid of cards (title, detail lines, badges, values, buttons)
//   UI.renderTable(box, items, build, empty)      a table; build(item) adds columns: [{ field: "amount", label: "Amount", format: "money", badge: false }]
//   UI.renderFeed(box, items, build, empty)       forum-style posts: a vote column, title, "by author · time ago", "💬 N comments"; extra options:
//       author: "author"  details: ["content"]  score: 3  comments: 2  noun: "comment"  onOpen: () => open(item)  compact: true (a comment row)
//       actions with slot: "up" | "down" are drawn as the vote buttons around the score; the others sit in the footer of the post
//   UI.statStrip(box, items, { noun, plural, sums: [{ field, label, format }], averages: [{ field, label, format }], by: "category", byField: "amount", byFormat: "money" })
//   UI.progress(box, done, total)   a progress bar with its label ("2 of 5 done", computed) inside a container (box is an empty <div id="..."> placed where the bar belongs)
//   UI.count(n, "post", "posts") -> "1 post" / "2 posts"     UI.timeAgo(item.created_at) -> "5 min ago"     UI.label("due_date") -> "Due date"
//   UI.form("Edit task", fields, item, async (values) => {...})   a dialog to edit an item (Edit button). fields:
//       [{ name: "title", label: "Title" }, { name: "priority", label: "Priority", options: ["Low", "Medium", "High"] },
//        { name: "due_date", label: "Due date", type: "date" }, { name: "done", label: "Done", type: "checkbox" }]
//       type: "text" (default) | "number" | "date" | "textarea" | "checkbox"; `options` makes it a select of those labels.
//       `values` has one entry per field (numbers as numbers, checkboxes as true/false). The dialog closes when onSave returns, unless it returns false.
//   `build` is the options object, or a function (item) => options so buttons can use the item.
// All text goes in with textContent, never innerHTML.
window.UI = (() => {
  const SYMBOLS = { add: "+", plus: "+", sum: "+", subtract: "−", minus: "−", multiply: "×", times: "×", divide: "÷", "divided by": "÷", power: "^", modulo: "%", mod: "%" };
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const TONES = { high: "danger", urgent: "danger", critical: "danger", overdue: "danger", blocked: "danger", major: "danger",
                  medium: "warning", normal: "warning", pending: "warning", "in progress": "warning", doing: "warning", reading: "warning", active: "warning",
                  low: "success", minor: "success", done: "success", paid: "success", complete: "success", completed: "success", finished: "success", closed: "success",
                  "to do": "info", todo: "info", open: "info", new: "info", "to read": "info" };
  // Labels without a fixed meaning (categories such as Food or Travel) get one steady colour each, so the same label always looks the same.
  const FREE_TONES = ["info", "accent", "teal", "pink"];
  const tone = (text) => {
    const key = text.toLowerCase();
    if (TONES[key]) return TONES[key];
    let h = 0;
    for (const c of key) h = (h * 31 + c.charCodeAt(0)) % 997;
    return FREE_TONES[h % FREE_TONES.length];
  };
  const stars = (v) => { const n = Math.max(0, Math.min(5, Math.round(Number(v)))); return "★".repeat(n) + "☆".repeat(5 - n); };
  const FORMATS = { money: (v) => api.money(v), num: (v) => api.num(v), symbol: (v) => api.symbol(v), stars };
  const show = (item, field, formats = {}) => {
    const v = item[field];
    if (v === undefined || v === null || v === "") return "";
    const f = FORMATS[formats[field]];
    return f ? f(v) : String(v);
  };
  const pretty = (name) => String(name).replace(/_(value|name)$/, "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const caption = (o, f) => (o.labels && o.labels[f]) || pretty(f);
  const checkbox = (item, o) => {
    const box = el("input", "item-check");
    box.type = "checkbox";
    box.checked = !!item[o.done];
    box.setAttribute("aria-label", "Mark as done");
    box.addEventListener("change", () => o.onToggle(box.checked));
    return box;
  };
  const detailLine = (item, o, f) => {
    const text = show(item, f, o.formats);
    if (!text) return null;
    const line = el("div", "muted small item-detail");
    if (o.labels && o.labels[f]) line.append(el("b", "", o.labels[f] + ": "), document.createTextNode(text));
    else line.textContent = text;
    return line;
  };
  const badgesOf = (item, o) => {
    const badges = el("span", "item-badges");
    for (const f of o.badges ?? []) {
      const text = show(item, f, o.formats);
      if (text) badges.appendChild(el("span", `badge badge-${tone(text)}`, text));
    }
    return badges.childNodes.length ? badges : null;
  };
  const valuesOf = (item, o) => {
    const box = el("span", "item-values");
    for (const f of o.values ?? []) {
      const text = show(item, f, o.formats);
      if (!text) continue;
      const v = el("span", "item-value");
      v.append(el("b", "", text), el("span", "", caption(o, f)));
      box.appendChild(v);
    }
    return box.childNodes.length ? box : null;
  };
  const buttons = (actions) => {
    const box = el("span", "item-actions");
    for (const a of actions) {
      const b = el("button", `btn-sm btn-${a.kind ?? "secondary"}`, a.label);
      b.type = "button";
      b.addEventListener("click", a.onClick);
      box.appendChild(b);
    }
    return box;
  };
  const timeAgo = (ts) => {
    if (!ts) return "";
    const text = String(ts);
    const d = new Date(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(text) ? text.replace(" ", "T") + "Z" : text);  // the database stores UTC without a zone
    if (isNaN(d)) return text;
    const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
    if (s < 45) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    if (s < 30 * 86400) return api.count(Math.round(s / 86400), "day") + " ago";
    return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  };
  const rows = (box, items, build, emptyText, make) => {
    if (!items || !items.length) return api.empty(box, emptyText);
    box.textContent = "";
    make(box, items.map((item) => [item, typeof build === "function" ? build(item) : build]));
  };
  const api = {
    listItem(item, o = {}) {
      const li = el("li", o.done && item[o.done] ? "list-item done" : "list-item");
      if (o.done && o.onToggle) li.appendChild(checkbox(item, o));
      const main = el("span", "item-main");
      if (o.title) main.appendChild(el("div", "item-title", show(item, o.title, o.formats)));
      for (const f of o.details ?? []) {
        const line = detailLine(item, o, f);
        if (line) main.appendChild(line);
      }
      li.appendChild(main);
      const badges = badgesOf(item, o);
      if (badges) li.appendChild(badges);
      const values = valuesOf(item, o);
      if (values) li.appendChild(values);
      if ((o.actions ?? []).length) li.appendChild(buttons(o.actions));
      return li;
    },
    renderList(box, items, build = {}, emptyText = "Nothing here yet.", cls = "list") {
      rows(box, items, build, emptyText, (box, pairs) => {
        const ul = el("ul", cls);
        for (const [item, o] of pairs) ul.appendChild(api.listItem(item, o));
        box.appendChild(ul);
      });
    },
    renderChecklist(box, items, build = {}, emptyText = "Nothing here yet.") {
      api.renderList(box, items, build, emptyText, "list checklist");
    },
    renderCards(box, items, build = {}, emptyText = "Nothing here yet.") {
      rows(box, items, build, emptyText, (box, pairs) => {
        const grid = el("div", "card-grid");
        for (const [item, o] of pairs) {
          const card = el("div", o.done && item[o.done] ? "card-item done" : "card-item");
          if (o.done && o.onToggle) card.appendChild(checkbox(item, o));
          if (o.title) card.appendChild(el("div", "item-title", show(item, o.title, o.formats)));
          for (const f of o.details ?? []) {
            const line = detailLine(item, o, f);
            if (line) card.appendChild(line);
          }
          for (const part of [badgesOf(item, o), valuesOf(item, o)]) if (part) card.appendChild(part);
          if ((o.actions ?? []).length) card.appendChild(buttons(o.actions));
          grid.appendChild(card);
        }
        box.appendChild(grid);
      });
    },
    renderTable(box, items, build = {}, emptyText = "Nothing here yet.") {
      rows(box, items, build, emptyText, (box, pairs) => {
        const cols = pairs[0][1].columns ?? [];
        const wrap = el("div", "table-wrap");
        const table = el("table", "table");
        const head = el("tr");
        for (const c of cols) head.appendChild(el("th", c.format === "money" || c.format === "num" ? "num" : "", c.label ?? pretty(c.field)));
        if ((pairs[0][1].actions ?? []).length) head.appendChild(el("th", "col-actions", ""));
        table.appendChild(el("thead")).appendChild(head);
        const body = el("tbody");
        for (const [item, o] of pairs) {
          const tr = el("tr");
          for (const c of o.columns ?? []) {
            const text = show(item, c.field, { [c.field]: c.format });
            const td = el("td", c.format === "money" || c.format === "num" ? "num" : "");
            if (c.badge && text) td.appendChild(el("span", `badge badge-${tone(text)}`, text));
            else td.textContent = text;
            tr.appendChild(td);
          }
          if ((o.actions ?? []).length) {
            const td = el("td", "col-actions");
            td.appendChild(buttons(o.actions));
            tr.appendChild(td);
          }
          body.appendChild(tr);
        }
        table.appendChild(body);
        wrap.appendChild(table);
        box.appendChild(wrap);
      });
    },
    renderFeed(box, items, build = {}, emptyText = "Nothing here yet.") {
      rows(box, items, build, emptyText, (box, pairs) => {
        const ul = el("ul", "feed");
        for (const [item, o] of pairs) {
          const li = el("li", o.compact ? "feed-post feed-comment" : "feed-post");
          const votes = (o.actions ?? []).filter((a) => a.slot === "up" || a.slot === "down");
          if (votes.length || o.score !== undefined) {
            const col = el("div", "vote-col");
            const vote = (a) => {
              const b = el("button", "", a.label);
              b.type = "button";
              b.setAttribute("aria-label", a.title ?? a.label);
              b.addEventListener("click", a.onClick);
              return b;
            };
            const up = votes.find((a) => a.slot === "up");
            const down = votes.find((a) => a.slot === "down");
            if (up) col.appendChild(vote(up));
            if (o.score !== undefined) col.appendChild(el("span", "vote-score", String(o.score)));
            if (down) col.appendChild(vote(down));
            li.appendChild(col);
          }
          const main = el("div", "feed-main");
          if (o.title) {
            const t = el("h3", o.onOpen ? "feed-title link" : "feed-title", show(item, o.title, o.formats));
            if (o.onOpen) t.addEventListener("click", o.onOpen);
            main.appendChild(t);
          }
          const starred = (o.values ?? []).filter((f) => (o.formats ?? {})[f] === "stars");  // a rating reads inline in the byline
          const by = [o.author && item[o.author] ? "by " + item[o.author] : "", timeAgo(item[o.time ?? "created_at"]), ...starred.map((f) => show(item, f, o.formats))].filter(Boolean).join(" · ");
          if (by) main.appendChild(el("div", "byline", by));
          for (const f of o.details ?? []) {
            const text = show(item, f, o.formats);
            if (!text) continue;
            const p = el("p", "feed-body");
            if (o.labels && o.labels[f]) p.append(el("b", "", o.labels[f] + ": "), document.createTextNode(text));
            else p.textContent = text;
            main.appendChild(p);
          }
          const values = valuesOf(item, { ...o, values: (o.values ?? []).filter((f) => !starred.includes(f)) });
          if (values) main.appendChild(values);
          const foot = el("div", "feed-foot");
          if (o.done && o.onToggle) {  // a yes/no field of a post (certificate, paid): a captioned checkbox that saves at once
            const label = el("label", "feed-check");
            const box = checkbox(item, o);
            box.setAttribute("aria-label", caption(o, o.done));
            label.append(box, document.createTextNode(" " + caption(o, o.done)));
            foot.appendChild(label);
          }
          if (o.comments !== undefined && o.onOpen) {
            const c = el("button", "btn-comments", "💬 " + api.count(o.comments, o.noun ?? "comment"));
            c.type = "button";
            c.addEventListener("click", o.onOpen);
            foot.appendChild(c);
          }
          const badges = badgesOf(item, o);
          if (badges) foot.appendChild(badges);
          const others = (o.actions ?? []).filter((a) => a.slot !== "up" && a.slot !== "down").map((a) => ({ ...a, kind: a.kind ?? "ghost" }));
          if (others.length) foot.appendChild(buttons(others));
          if (foot.childNodes.length) main.appendChild(foot);
          li.appendChild(main);
          ul.appendChild(li);
        }
        box.appendChild(ul);
      });
    },
    progress(box, done, total, label) {
      const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((100 * done) / total))) : 0;
      box.textContent = "";
      box.classList.add("progress");
      box.appendChild(el("div", "progress-label", label ?? `${done} of ${total} done`));
      const track = el("div", "progress-track");
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(pct));
      const fill = el("div", "progress-fill");
      fill.style.width = pct + "%";
      track.appendChild(fill);
      box.appendChild(track);
    },
    statStrip(box, items, o = {}) {
      box.textContent = "";
      box.classList.add("stat-strip");
      const stat = (label, value, cls = "stat") => {
        const s = el("div", cls);
        s.append(el("div", "stat-label", label), el("div", "stat-value", value));
        return s;
      };
      const fmt = (name, v) => (name === "money" ? api.money(v) : name === "num" ? api.num(v) : name === "stars" ? stars(v) + " " + api.num(v, 1) : api.num(v, 1));
      const noun = o.plural ?? (o.noun ? o.noun + "s" : "items");
      box.appendChild(stat(pretty(noun), String(items.length)));
      const sum = (f) => items.reduce((t, i) => t + (Number(i[f]) || 0), 0);
      for (const s of o.sums ?? []) box.appendChild(stat(s.label ?? "Total " + pretty(s.field).toLowerCase(), fmt(s.format ?? "num", sum(s.field))));
      for (const a of o.averages ?? []) {
        const rated = items.filter((i) => i[a.field] !== undefined && i[a.field] !== null && i[a.field] !== "");
        box.appendChild(stat(a.label ?? "Average " + pretty(a.field).toLowerCase(), rated.length ? fmt(a.format ?? "avg", sum(a.field) / rated.length) : "–"));
      }
      if (o.by && items.length) {
        const groups = {};
        for (const i of items) {
          const k = i[o.by];
          if (k === undefined || k === null || k === "") continue;
          groups[k] = (groups[k] ?? 0) + (o.byField ? Number(i[o.byField]) || 0 : 1);
        }
        const wide = el("div", "stat stat-wide");
        wide.appendChild(el("div", "stat-label", "By " + pretty(o.by).toLowerCase()));
        const chips = el("div", "stat-chips");
        for (const [k, v] of Object.entries(groups).sort((a, b) => b[1] - a[1])) chips.appendChild(el("span", `badge badge-${tone(k)}`, `${k} · ${o.byField ? fmt(o.byFormat ?? "num", v) : v}`));
        wide.appendChild(chips);
        if (chips.childNodes.length) box.appendChild(wide);
      }
    },
    count(n, singular, plural) {
      return n + " " + (n === 1 ? singular : plural ?? (/(s|x|z|ch|sh)$/.test(singular) ? singular + "es" : /[^aeiou]y$/.test(singular) ? singular.slice(0, -1) + "ies" : singular + "s"));
    },
    timeAgo,
    label: pretty,
    form(title, fields, values, onSave) {
      const overlay = el("div", "modal-overlay");
      const card = el("form", "card modal stack");
      card.appendChild(el("h2", "card-title", title));
      const inputs = {};
      for (const f of fields) {
        const wrap = el("div", f.type === "checkbox" ? "field field-check" : "field");
        const id = "ui-form-" + f.name;
        const label = el("label", "", f.label ?? f.name);
        label.setAttribute("for", id);
        let input;
        if (f.options) {
          input = el("select");
          for (const o of f.options) input.appendChild(el("option", "", o));
          input.value = values?.[f.name] ?? f.options[0];
        } else if (f.type === "textarea") {
          input = el("textarea");
          input.value = values?.[f.name] ?? "";
        } else {
          input = el("input");
          input.type = f.type ?? "text";
          if (f.type === "checkbox") input.checked = !!values?.[f.name];
          else input.value = values?.[f.name] ?? "";
        }
        input.id = id;
        inputs[f.name] = input;
        if (f.type === "checkbox") wrap.append(input, label);
        else wrap.append(label, input);
        card.appendChild(wrap);
      }
      const row = el("div", "row");
      const save = el("button", "", "Save");
      save.type = "submit";
      const cancel = el("button", "btn-secondary", "Cancel");
      cancel.type = "button";
      row.append(save, cancel);
      card.appendChild(row);
      const close = () => overlay.remove && overlay.remove();
      cancel.addEventListener("click", close);
      card.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const out = {};
        for (const f of fields) {
          const i = inputs[f.name];
          out[f.name] = f.type === "checkbox" ? i.checked : f.type === "number" ? parseFloat(i.value) : i.value;
        }
        if ((await onSave(out)) !== false) close();
      });
      overlay.appendChild(card);
      document.body.appendChild(overlay);
      return overlay;
    },
    toast(message, kind = "info") {
      let box = document.querySelector(".toast-container");
      if (!box) { box = el("div", "toast-container"); document.body.appendChild(box); }
      const t = el("div", `toast toast-${kind}`, message);
      box.appendChild(t);
      setTimeout(() => t.remove(), 3500);
    },
    num(value, maxDigits = 6) {
      const n = Number(value);
      return Number.isFinite(n) ? n.toLocaleString("en-US", { maximumFractionDigits: maxDigits }) : String(value ?? "");
    },
    money(value, currency = "USD") {
      const n = Number(value);
      return Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency }) : String(value ?? "");
    },
    symbol(word) {
      return SYMBOLS[String(word).toLowerCase()] ?? String(word);
    },
    loading(box, text = "Loading…") {
      box.textContent = "";
      const wrap = el("div", "loading");
      wrap.append(el("span", "spinner"), el("span", "", text));
      box.appendChild(wrap);
    },
    empty(box, text, icon = "∅") {
      box.textContent = "";
      const wrap = el("div", "empty-state");
      wrap.append(el("span", "empty-icon", icon), el("span", "", text));
      box.appendChild(wrap);
    },
  };
  return api;
})();
