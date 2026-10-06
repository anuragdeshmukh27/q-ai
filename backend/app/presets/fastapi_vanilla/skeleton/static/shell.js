// Q app shell (locked preset file: generated apps use it, they never edit it).
// A multi-page app drawn from a plain description of the app: Q.mount(config, hooks). Everything is built with textContent, never innerHTML.
//   pages (hash router):  #/ dashboard   #/<resource> a list page   #/<resource>/<id> a detail page (tabs for the related resources)   #/about
//   a resource:  { name, singular, label, icon, parent, children, list, create, item, fields, columns, title, filters, search, actions, ... }  (see shell.py)
//   hooks.loaded({ resource, items, data: { items } }) runs after the main list was read, so a request can add something to the page (request-hook:loaded).
(() => {
  "use strict";
  const DARK_SIDEBAR = ["campus", "ledger", "transit", "depot", "academy"];
  const TONES = { high: "danger", urgent: "danger", critical: "danger", overdue: "danger", cancelled: "danger", canceled: "danger", rejected: "danger", failed: "danger", "no show": "danger",
    medium: "warning", normal: "warning", pending: "warning", pledged: "warning", requested: "warning", scheduled: "warning", "in progress": "warning", accepted: "info", "on trip": "info",
    low: "success", done: "success", paid: "success", complete: "success", completed: "success", finished: "success", closed: "success", "checked in": "success", registered: "info",
    "to do": "info", open: "info", new: "info" };
  const FREE = ["info", "accent", "teal", "pink"];
  const SYMBOLS = { upvote: "▲", downvote: "▼", like: "♥", dislike: "▼", vote: "▲", view: "👁" };
  let cfg = null;
  let hooks = {};
  let view = null;
  let sideNav = null;
  let crumbs = null;
  const state = { rows: {}, token: 0, sort: {}, filters: {}, search: {}, tab: {}, view: {} };
  let dragging = null;
  const asksBoard = () => typeof location.search === "string" && /[?&]view=board/.test(location.search);  // ?view=board opens the boards first (for a screenshot or a link)

  // ---- small helpers -----------------------------------------------------------------------------------------------------------------------------------
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const add = (parent, ...kids) => {
    for (const k of kids) if (k) parent.appendChild(typeof k === "string" ? document.createTextNode(k) : k);
    return parent;
  };
  const clear = (n) => { n.textContent = ""; return n; };
  const by = (name) => cfg.resources.find((r) => r.name === name);
  const fill = (url, vars) => url.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(vars[k]));
  const pretty = (s) => String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const tone = (text) => {
    const key = String(text).toLowerCase();
    if (TONES[key]) return TONES[key];
    let h = 0;
    for (const c of key) h = (h * 31 + c.charCodeAt(0)) % 997;
    return FREE[h % FREE.length];
  };
  const money = (v) => { try { return new Intl.NumberFormat(cfg.locale, { style: "currency", currency: cfg.currency, maximumFractionDigits: 0 }).format(Number(v)); } catch { return String(v); } };
  const num = (v, d = 2) => (Number.isFinite(Number(v)) ? Number(v).toLocaleString(cfg.locale, { maximumFractionDigits: d }) : String(v ?? ""));
  const stars = (v) => { const n = Math.max(0, Math.min(5, Math.round(Number(v)))); return "★".repeat(n) + "☆".repeat(5 - n); };
  const dateText = (v) => {
    const d = new Date(/^\d{4}-\d\d-\d\d$/.test(String(v)) ? v + "T00:00:00" : v);
    return isNaN(d) ? String(v) : d.toLocaleDateString(cfg.locale, { day: "numeric", month: "short", year: "numeric" });
  };
  const ago = (ts) => {
    if (!ts) return "";
    const t = String(ts);
    const d = new Date(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(t) ? t.replace(" ", "T") + "Z" : t);
    if (isNaN(d)) return t;
    const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
    if (s < 45) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  };
  const count = (n, one, many) => n + " " + (n === 1 ? one : many);
  const toast = (message, kind = "info") => {
    let box = document.querySelector(".toast-container");
    if (!box) { box = el("div", "toast-container"); document.body.appendChild(box); }
    const t = el("div", `toast toast-${kind}`, message);
    box.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  };

  // ---- data ---------------------------------------------------------------------------------------------------------------------------------------------
  async function call(method, url, body) {
    const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch { /* an empty body */ }
    if (!res.ok) {
      const err = new Error("request failed");
      err.detail = typeof data?.detail === "string" ? data.detail : "Please check your input";
      throw err;
    }
    return data;
  }
  const listUrl = (r, parentId) => {
    const base = r.parent ? fill(r.list, { parent: parentId }) : r.list;
    return r.sorts && r.sorts.length ? base + "?sort=" + (state.sort[r.name + ":server"] || "new") : base;
  };
  async function rows(name) {
    if (state.rows[name]) return state.rows[name];
    const r = by(name);
    let out;
    if (r.parent) {
      const parents = await rows(r.parent);
      const lists = await Promise.all(parents.map((p) => call("GET", listUrl(r, p.id)).catch(() => ({ items: [] }))));
      out = lists.flatMap((res, i) => (res.items || []).map((item) => ({ ...item, _parent: parents[i] })));
    } else {
      out = ((await call("GET", listUrl(r))) || {})[r.listKey || "items"] || [];
    }
    state.rows[name] = out;
    return out;
  }
  const invalidate = () => { state.rows = {}; };
  const primary = () => cfg.resources.find((r) => !r.parent) || cfg.resources[0];
  const titleOf = (r, item) => (item ? String(item[r.title] ?? item.id) : "");
  const valuesOf = (r, item) => Object.fromEntries(r.fields.map((f) => [f.name, item[f.name]]));

  // ---- cells and values ---------------------------------------------------------------------------------------------------------------------------------
  function cell(r, f, item) {
    const v = item[f.name];
    if (v === undefined || v === null || v === "") return el("span", "muted", "–");
    if (f.options && f.options.length) return el("span", `badge badge-${tone(v)}`, String(v));
    if (f.kind === "money") return el("span", "", money(v));
    if (f.kind === "rating") return el("span", "q-stars", stars(v));
    if (f.kind === "number" || f.kind === "integer" || f.kind === "counter") return el("span", "", num(v));
    if (f.kind === "checkbox") return el("span", "", v ? "✓" : "–");
    if (f.kind === "longtext") { const s = el("span", "q-clip", String(v)); s.title = String(v); return s; }
    if (f.kind === "date") return el("span", "", dateText(v));
    if (f.kind === "phone") { const a = el("a", "", String(v)); a.href = "tel:" + String(v); return a; }
    if (f.kind === "email") { const a = el("a", "", String(v)); a.href = "mailto:" + String(v); return a; }
    return el("span", "", String(v));
  }
  const isNum = (f) => ["money", "number", "integer", "counter", "rating"].includes(f.kind);
  const fieldOf = (r, name) => r.fields.find((f) => f.name === name) || (r.extra || []).find((f) => f.name === name);
  // the field a board is made of: the one the status flow is about, else a labelled field called status, stage, state or phase
  const statusField = (r) => {
    const named = r.flow && Object.keys(r.flow)[0];
    const f = named && fieldOf(r, named);
    if (f && f.options && f.options.length >= 2) return f;
    return r.fields.find((x) => x.options && x.options.length >= 2 && x.options.length <= 8 && /status|stage|state|phase/i.test(x.name)) || null;
  };

  // ---- actions ------------------------------------------------------------------------------------------------------------------------------------------
  function allowed(r, a, item) {
    if (a.kind !== "set") return true;
    const now = item[a.field];
    if (now === a.value) return false;
    const flow = r.flow && r.flow[a.field];
    return !flow || (flow[now] || []).includes(a.value);
  }
  async function run(r, a, item) {
    try {
      await call("POST", fill(a.url, { id: item.id }));
      toast(a.kind === "set" ? `${item[r.title] ?? r.singular}: ${a.value}` : "Done", "success");
    } catch (e) {
      toast(e.detail || "Could not do that", "error");
    }
    invalidate();
    await render();
  }
  function actionButton(r, a, item) {
    const label = a.kind === "increment" ? `${SYMBOLS[a.name] || "+"} ${num(item[a.field] ?? 0, 0)}` : a.label;
    const b = el("button", `q-act q-${a.tone || (a.kind === "set" ? "info" : "")}`, label);
    b.type = "button";
    b.title = a.label;
    b.dataset.action = a.name;
    if (!allowed(r, a, item)) b.disabled = true;
    b.addEventListener("click", () => run(r, a, item));
    return b;
  }

  // ---- forms --------------------------------------------------------------------------------------------------------------------------------------------
  function input(f, value) {
    let n;
    if (f.options && f.options.length) {
      n = el("select");
      for (const o of f.options) n.appendChild(el("option", "", o));
      n.value = value ?? f.options[0];
    } else if (f.kind === "longtext") {
      n = el("textarea");
      n.rows = 3;
      n.value = value ?? "";
    } else {
      n = el("input");
      n.type = { number: "number", integer: "number", money: "number", rating: "number", date: "date", time: "time", phone: "tel", email: "email", checkbox: "checkbox" }[f.kind] || "text";
      if (f.kind === "integer" || f.kind === "rating") n.step = "1";
      else if (n.type === "number") n.step = "any";
      if (f.min !== undefined) n.min = String(f.min);
      if (f.max !== undefined) n.max = String(f.max);
      if (f.kind === "checkbox") n.checked = !!value;
      else n.value = value ?? "";
    }
    n.id = "f-" + f.name;
    n.name = f.name;
    return n;
  }
  function openForm({ title, fields, values = {}, parents = null, submit = "Save", onSave }) {
    const overlay = el("div", "q-overlay");
    const form = el("form", "q-modal");
    form.setAttribute("role", "dialog");
    form.appendChild(el("h2", "", title));
    const grid = el("div", "q-form-grid");
    const inputs = {};
    let parentSelect = null;
    const field = (label, control, wide, hint) => {
      const wrap = el("div", `field${wide ? " q-wide" : ""}${control.type === "checkbox" ? " field-check" : ""}`);
      const l = el("label", "", label);
      l.setAttribute("for", control.id || "");
      if (control.type === "checkbox") add(wrap, control, l); else add(wrap, l, control);
      if (hint) wrap.appendChild(el("span", "q-hint", hint));
      grid.appendChild(wrap);
    };
    if (parents) {
      parentSelect = el("select");
      parentSelect.id = "f-parent";
      for (const p of parents.rows) { const o = el("option", "", titleOf(parents.resource, p)); o.value = String(p.id); parentSelect.appendChild(o); }
      parentSelect.value = String(parents.selected ?? (parents.rows[0] && parents.rows[0].id));
      field(pretty(parents.resource.singular), parentSelect, true);
    }
    for (const f of fields) {
      inputs[f.name] = input(f, values[f.name]);
      field(f.label, inputs[f.name], f.kind === "longtext", f.hint);
    }
    form.appendChild(grid);
    const error = el("div", "alert alert-error");
    error.id = "form-error";
    error.style.marginTop = "12px";
    form.appendChild(error);
    const actions = el("div", "q-modal-actions");
    const cancel = el("button", "btn-secondary", "Cancel");
    cancel.type = "button";
    const save = el("button", "", submit);
    save.type = "submit";
    add(actions, cancel, save);
    form.appendChild(actions);
    const close = () => overlay.remove && overlay.remove();
    cancel.addEventListener("click", close);
    overlay.addEventListener("click", (ev) => { if (ev.target === overlay) close(); });
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      error.textContent = "";
      const out = {};
      for (const f of fields) {
        const i = inputs[f.name];
        if (f.kind === "checkbox") { out[f.name] = i.checked; continue; }
        const raw = i.value;
        if (isNum(f)) {
          if (String(raw).trim() === "") { error.textContent = `${f.label} is required`; return; }
          out[f.name] = parseFloat(raw);
        } else {
          out[f.name] = raw;
        }
      }
      save.disabled = true;
      try {
        await onSave(out, parentSelect ? Number(parentSelect.value) : null);
        close();
      } catch (e) {
        error.textContent = e.detail || "Could not save";
        save.disabled = false;
      }
    });
    overlay.appendChild(form);
    document.body.appendChild(overlay);
    const first = grid.querySelector && grid.querySelector("input, select, textarea");
    if (first && first.focus) first.focus();
    return overlay;
  }
  function confirmBox(text, onYes) {
    const overlay = el("div", "q-overlay");
    const box = el("div", "q-modal");
    box.appendChild(el("h2", "", "Are you sure?"));
    box.appendChild(el("p", "muted", text));
    const actions = el("div", "q-modal-actions");
    const no = el("button", "btn-secondary", "Cancel");
    const yes = el("button", "btn-danger", "Delete");
    no.type = yes.type = "button";
    add(actions, no, yes);
    box.appendChild(actions);
    const close = () => overlay.remove && overlay.remove();
    no.addEventListener("click", close);
    yes.addEventListener("click", async () => { close(); await onYes(); });
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  }
  function createForm(r, parentId) {
    const parentRes = r.parent ? by(r.parent) : null;
    const open = async () => {
      const parents = parentRes ? await rows(parentRes.name) : null;
      if (parentRes && !parents.length) { toast(`Add a ${parentRes.singular} first`, "info"); return; }
      openForm({
        title: `New ${r.singular}`, fields: r.fields, submit: `Add ${r.singular}`,
        parents: parentRes && !parentId ? { resource: parentRes, rows: parents, selected: parents[0].id } : null,
        onSave: async (values, chosen) => {
          const pid = parentId ?? chosen;
          await call("POST", r.parent ? fill(r.create, { parent: pid }) : r.create, values);
          toast(`${pretty(r.singular)} added`, "success");
          invalidate();
          await render();
        },
      });
    };
    return open;
  }
  function editForm(r, item) {
    return () => openForm({
      title: `Edit ${r.singular}`, fields: r.fields, values: valuesOf(r, item),
      onSave: async (values) => {
        await call("PUT", fill(r.item, { id: item.id }), values);
        toast("Saved", "success");
        invalidate();
        await render();
      },
    });
  }
  function removeItem(r, item, then) {
    return () => confirmBox(`Delete this ${r.singular}${(r.children || []).length ? ` and its ${r.children.map((c) => c).join(", ")}` : ""}? This cannot be undone.`, async () => {
      try {
        await call("DELETE", fill(r.item, { id: item.id }));
        toast("Removed", "success");
      } catch (e) {
        toast(e.detail || "Could not delete", "error");
      }
      invalidate();
      if (then) then(); else await render();
    });
  }

  // ---- tables -------------------------------------------------------------------------------------------------------------------------------------------
  function sorted(r, items, key) {
    const s = state.sort[key];
    if (!s) return items;
    const f = fieldOf(r, s.field);
    const get = (i) => (s.field === "_parent" ? titleOf(by(r.parent), i._parent) : i[s.field]);
    const numeric = f && isNum(f);
    return [...items].sort((a, b) => {
      const x = get(a), y = get(b);
      const c = numeric ? (Number(x) || 0) - (Number(y) || 0) : String(x ?? "").localeCompare(String(y ?? ""), undefined, { numeric: true, sensitivity: "base" });
      return s.dir === "desc" ? -c : c;
    });
  }
  function table(r, items, key, { showParent = false, onChange } = {}) {
    const wrap = el("div", "q-card q-table-card");
    const scroll = el("div", "q-table-wrap");
    const t = el("table", "q-table");
    const head = el("tr");
    const cols = r.columns.map((n) => fieldOf(r, n)).filter(Boolean);
    const headers = [...(showParent ? [{ name: "_parent", label: pretty(by(r.parent).singular), kind: "text" }] : []), ...cols];
    for (const c of headers) {
      const th = el("th", `q-sortable${isNum(c) ? " q-num" : ""}`, c.label);
      const s = state.sort[key];
      if (s && s.field === c.name) th.setAttribute("aria-sort", s.dir === "asc" ? "ascending" : "descending");
      th.addEventListener("click", () => {
        const cur = state.sort[key];
        state.sort[key] = { field: c.name, dir: cur && cur.field === c.name && cur.dir === "asc" ? "desc" : "asc" };
        onChange && onChange();
      });
      head.appendChild(th);
    }
    head.appendChild(el("th", "", ""));
    t.appendChild(el("thead")).appendChild(head);
    const body = el("tbody");
    for (const item of sorted(r, items, key)) {
      const tr = el("tr");
      if (showParent) {
        const td = el("td");
        const p = by(r.parent);
        const a = el("a", "q-link", titleOf(p, item._parent));
        a.href = `#/${p.name}/${item._parent.id}`;
        td.appendChild(a);
        tr.appendChild(td);
      }
      cols.forEach((c, i) => {
        const td = el("td", isNum(c) ? "q-num" : "");
        if (c.name === r.title) {
          if (r.toggle) {
            const box = el("input");
            box.type = "checkbox";
            box.checked = !!item[r.toggle];
            box.title = "Mark as done";
            box.style.marginRight = "10px";
            box.addEventListener("change", async () => {
              try { await call("PUT", fill(r.item, { id: item.id }), { ...valuesOf(r, item), [r.toggle]: box.checked }); } catch (e) { toast(e.detail || "Could not save", "error"); }
              invalidate();
              await render();
            });
            td.appendChild(box);
          }
          const a = el("a", "q-link", titleOf(r, item));
          a.href = `#/${r.name}/${item.id}`;
          td.appendChild(a);
          const sub = (r.subtitle || []).map((n) => item[n]).filter((x) => x !== undefined && x !== null && x !== "");
          if (sub.length) td.appendChild(el("span", "q-sub", sub.join(" · ")));
        } else {
          td.appendChild(cell(r, c, item));
        }
        tr.appendChild(td);
      });
      const td = el("td", "q-actions");
      for (const a of r.actions) td.appendChild(actionButton(r, a, item));
      const edit = el("button", "q-btn-icon", "✎");
      edit.title = "Edit";
      edit.setAttribute("aria-label", "Edit");
      edit.type = "button";
      edit.addEventListener("click", editForm(r, item));
      const del = el("button", "q-btn-icon", "🗑");
      del.title = "Delete";
      del.setAttribute("aria-label", "Delete");
      del.type = "button";
      del.addEventListener("click", removeItem(r, item));
      add(td, edit, del);
      tr.appendChild(td);
      body.appendChild(tr);
    }
    t.appendChild(body);
    scroll.appendChild(t);
    wrap.appendChild(scroll);
    return wrap;
  }
  // ---- board (kanban): one column per label of the status field; a card moves by drag and drop or by its "Move to" list ---------------------------------------
  function board(r, items, sf, { showParent = false } = {}) {
    const wrap = el("div", "q-board");
    wrap.setAttribute("aria-label", `${r.label} by ${sf.label.toLowerCase()}`);
    const flow = r.flow && r.flow[sf.name];
    const targets = (item) => sf.options.filter((o) => o !== item[sf.name] && (!flow || (flow[item[sf.name]] || []).includes(o)));
    const move = async (item, value) => {
      if (item[sf.name] === value) return;
      if (!targets(item).includes(value)) { toast(`${titleOf(r, item)} cannot go from ${item[sf.name]} to ${value}`, "error"); return; }
      const act = r.actions.find((a) => a.kind === "set" && a.field === sf.name && a.value === value);
      if (act) { await run(r, act, item); return; }
      if (r.noEdit) { toast(`${pretty(r.singular)} cannot be changed`, "error"); return; }
      try {
        await call("PUT", fill(r.item, { id: item.id }), { ...valuesOf(r, item), [sf.name]: value });
        toast(`${titleOf(r, item)}: ${value}`, "success");
      } catch (e) {
        toast(e.detail || "Could not move that", "error");
      }
      invalidate();
      await render();
    };
    const known = new Set(sf.options);
    const columns = [...sf.options.map((o) => [o, o]), ...(items.some((i) => !known.has(i[sf.name])) ? [["", "No " + sf.label.toLowerCase()]] : [])];
    const extra = r.columns.filter((n) => n !== r.title && n !== sf.name).map((n) => fieldOf(r, n)).filter(Boolean).slice(0, 2);
    for (const [value, label] of columns) {
      const mine = items.filter((i) => (value ? i[sf.name] === value : !known.has(i[sf.name])));
      const col = el("section", "q-col");
      col.dataset.value = value;
      const hd = el("header", "q-col-head");
      add(hd, el("span", `badge badge-${tone(label)}`, label), el("span", "q-pill", String(mine.length)));
      col.appendChild(hd);
      const body = el("div", "q-col-body");
      for (const item of mine) {
        const card = el("article", "q-kcard");
        card.draggable = true;
        card.dataset.id = String(item.id);
        card.addEventListener("dragstart", (ev) => {
          dragging = item;
          if (ev.dataTransfer) { try { ev.dataTransfer.setData("text/plain", String(item.id)); ev.dataTransfer.effectAllowed = "move"; } catch { /* a browser without data transfer */ } }
        });
        card.addEventListener("dragend", () => { dragging = null; });
        const a = el("a", "q-kcard-title", titleOf(r, item));
        a.href = `#/${r.name}/${item.id}`;
        card.appendChild(a);
        if (showParent && item._parent) card.appendChild(el("div", "q-kcard-parent", titleOf(by(r.parent), item._parent)));
        for (const f of extra) {
          if (item[f.name] === undefined || item[f.name] === null || item[f.name] === "") continue;
          const line = el("div", "q-kcard-line");
          add(line, el("span", "q-kcard-key", f.label), cell(r, f, item));
          card.appendChild(line);
        }
        const options = targets(item);
        if (options.length && !r.noEdit) {
          const sel = el("select", "q-kcard-move");
          sel.setAttribute("aria-label", `Move ${titleOf(r, item)} to`);
          const keep = el("option", "", "Move to…");
          keep.value = "";
          sel.appendChild(keep);
          for (const o of options) { const op = el("option", "", o); op.value = o; sel.appendChild(op); }
          sel.value = "";
          sel.addEventListener("change", () => { if (sel.value) move(item, sel.value); });
          card.appendChild(sel);
        }
        body.appendChild(card);
      }
      if (!mine.length) body.appendChild(el("div", "q-col-empty", "Nothing here"));
      col.appendChild(body);
      col.addEventListener("dragover", (ev) => { if (dragging && value) { ev.preventDefault(); col.classList.add("q-over"); } });
      col.addEventListener("dragleave", () => col.classList.remove("q-over"));
      col.addEventListener("drop", (ev) => { ev.preventDefault(); col.classList.remove("q-over"); const item = dragging; dragging = null; if (item && value) move(item, value); });
      wrap.appendChild(col);
    }
    return wrap;
  }
  function empty(r, text, onAdd, label) {
    const box = el("div", "q-card q-empty");
    box.appendChild(el("div", "q-empty-icon", r.icon || cfg.icon));
    box.appendChild(el("div", "", text || (cfg.empty[r.name] || cfg.empty.default)));
    if (onAdd) { const b = el("button", "", label || `Add ${r.singular}`); b.type = "button"; b.addEventListener("click", onAdd); box.appendChild(b); }
    return box;
  }
  function matches(r, item, q) {
    if (!q) return true;
    const hay = [...(r.search || []).map((n) => item[n]), item._parent ? titleOf(by(r.parent), item._parent) : ""].join(" ").toLowerCase();
    return hay.includes(q.toLowerCase());
  }
  // a toolbar (search, one select per labelled field, a sort when the API has one) and the table under it; `container` is redrawn when anything changes
  function listBlock(r, items, key, container, { showParent = false, addLabel } = {}) {
    const draw = () => {
      clear(container);
      const q = state.search[key] || "";
      const f = state.filters[key] || {};
      const hit = (i, n, v) => (fieldOf(r, n).kind === "checkbox" ? !!i[n] === (v === "Yes") : i[n] === v);
      const shown = items.filter((i) => matches(r, i, q) && Object.entries(f).every(([n, v]) => !v || hit(i, n, v)));
      const bar = el("div", "q-toolbar");
      if ((r.search || []).length) {
        const wrap = el("div", "q-search");
        const s = el("input");
        s.type = "search";
        s.placeholder = `Search ${r.label.toLowerCase()}`;
        s.value = q;
        s.id = "search-" + key.replace(/\W/g, "-");
        s.addEventListener("input", () => { state.search[key] = s.value; draw(); const again = container.querySelector && container.querySelector("#" + s.id); if (again && again.focus) { again.focus(); try { again.setSelectionRange(s.value.length, s.value.length); } catch { /* not supported for search inputs */ } } });
        wrap.appendChild(s);
        bar.appendChild(wrap);
      }
      for (const name of r.filters || []) {
        const fld = fieldOf(r, name);
        const sel = el("select");
        sel.id = "filter-" + name;
        sel.setAttribute("aria-label", `Filter by ${fld.label.toLowerCase()}`);
        const all = el("option", "", `All ${fld.label.toLowerCase()}`);
        all.value = "";
        sel.appendChild(all);
        for (const o of fld.options || ["Yes", "No"]) { const op = el("option", "", o); op.value = o; sel.appendChild(op); }
        sel.value = f[name] || "";
        sel.addEventListener("change", () => { state.filters[key] = { ...f, [name]: sel.value }; draw(); });
        bar.appendChild(sel);
      }
      if (r.sorts && r.sorts.length) {
        const sel = el("select");
        sel.id = "sort-" + r.name;
        for (const [v, label] of [["new", "Newest first"], ["top", "Top first"]]) { const op = el("option", "", label); op.value = v; sel.appendChild(op); }
        sel.value = state.sort[r.name + ":server"] || "new";
        sel.addEventListener("change", async () => { state.sort[r.name + ":server"] = sel.value; invalidate(); await render(); });
        bar.appendChild(sel);
      }
      const sf = statusField(r);
      const mode = sf && (state.view[key] || (asksBoard() ? "board" : "")) === "board" ? "board" : "table";
      if (sf) {
        const seg = el("div", "q-seg");
        seg.setAttribute("role", "group");
        seg.setAttribute("aria-label", "View");
        for (const [v, label] of [["table", "☰ Table"], ["board", "▥ Board"]]) {
          const b = el("button", "", label);
          b.type = "button";
          b.id = "view-" + v;
          b.dataset.view = v;
          b.setAttribute("aria-pressed", String(v === mode));
          b.addEventListener("click", () => { state.view[key] = v; draw(); });
          seg.appendChild(b);
        }
        bar.appendChild(seg);
      }
      bar.appendChild(el("span", "q-count", count(shown.length, r.singular.replace(/_/g, " "), r.label.toLowerCase())));
      container.appendChild(bar);
      container.appendChild(shown.length && mode === "board" ? board(r, shown, sf, { showParent }) : shown.length ? table(r, shown, key, { showParent, onChange: draw }) : empty(r, items.length ? "Nothing matches. Try another search or filter." : undefined, items.length ? null : createForm(r, null), addLabel));
    };
    draw();
  }

  // ---- pages --------------------------------------------------------------------------------------------------------------------------------------------
  function head(title, sub, ...actions) {
    const h = el("div", "q-page-head");
    const left = el("div");
    left.appendChild(el("h1", "", title));
    if (sub) left.appendChild(el("p", "", sub));
    h.appendChild(left);
    const right = el("div", "q-spacer");
    for (const a of actions) if (a) right.appendChild(a);
    h.appendChild(right);
    return h;
  }
  const button = (text, fn, cls) => { const b = el("button", cls || "", text); b.type = "button"; b.addEventListener("click", fn); return b; };
  function setCrumbs(parts) {
    clear(crumbs);
    parts.forEach((p, i) => {
      if (i) crumbs.appendChild(el("span", "q-sep", "/"));
      if (p.href) { const a = el("a", "", p.text); a.href = p.href; crumbs.appendChild(a); }
      else { const s = el("span", "", p.text); s.setAttribute("aria-current", "page"); crumbs.appendChild(s); }
    });
  }
  const where = (item, w) => !w || Object.entries(w).every(([k, v]) => item[k] === v);
  async function kpi(k) {
    const r = k.resource === "*" ? primary() : by(k.resource);
    if (!r) return null;
    const items = (await rows(r.name)).filter((i) => where(i, k.where));
    let value;
    if (k.agg === "count") value = items.length;
    else if (k.agg === "sum") value = items.reduce((t, i) => t + (Number(i[k.field]) || 0), 0);
    else if (k.agg === "avg") { const v = items.filter((i) => i[k.field] !== undefined && i[k.field] !== null); value = v.length ? v.reduce((t, i) => t + (Number(i[k.field]) || 0), 0) / v.length : null; }
    else if (k.agg === "sumprod") value = items.reduce((t, i) => t + (Number(i[k.field]) || 0) * (Number(i[k.with]) || 0), 0);
    if (value === null || value === undefined) return "–";
    return k.format === "money" ? money(value) : k.format === "stars" ? stars(value) + " " + num(value, 1) : num(value, k.agg === "avg" ? 1 : 0);
  }
  async function chart(c) {
    const r = c.resource === "*" ? primary() : by(c.resource);
    if (!r) return null;
    const items = await rows(r.name);
    let data = [];
    if (c.per === "parent" && r.parent) {
      const p = by(r.parent);
      const parents = await rows(p.name);
      data = parents.map((x) => ({ label: titleOf(p, x), value: items.filter((i) => i._parent && i._parent.id === x.id).length })).sort((a, b) => b.value - a.value).slice(0, 8);
    } else if (c.by) {
      const f = fieldOf(r, c.by);
      if (!f) return null;
      const labels = f.options && f.options.length ? f.options : [...new Set(items.map((i) => i[c.by]).filter((v) => v !== undefined && v !== null && v !== ""))];
      data = labels.map((l) => ({ label: String(l), value: items.filter((i) => i[c.by] === l).reduce((t, i) => t + (c.sum ? Number(i[c.sum]) || 0 : 1), 0) }));
    } else {
      return null;
    }
    if (!data.length) return null;
    const top = Math.max(1, ...data.map((d) => d.value));
    const columns = (cfg.ui || {}).charts === "columns";
    const total = data.reduce((t, d) => t + d.value, 0);
    const box = el("section", "q-card q-chart");
    const hd = el("div", "q-card-head");
    add(hd, el("h2", "", c.title), el("span", "q-chart-total", (c.sum && c.format === "money" ? money(total) : num(total, 0)) + " total"));
    box.appendChild(hd);
    const bars = el("div", columns ? "q-bars q-cols" : "q-bars");
    for (const d of data) {
      const row = el("div", "q-bar");
      const track = el("div", "q-bar-track");
      const fillEl = el("div", "q-bar-fill");
      fillEl.style[columns ? "height" : "width"] = Math.round((100 * d.value) / top) + "%";
      track.appendChild(fillEl);
      add(row, el("span", "q-bar-label", d.label), track, el("span", "q-bar-value", c.sum && c.format === "money" ? money(d.value) : num(d.value, 0)));
      bars.appendChild(row);
    }
    box.appendChild(bars);
    return box;
  }
  async function dashboard() {
    setCrumbs([{ text: "Dashboard" }]);
    const sections = [];
    await Promise.all(cfg.resources.map((r) => rows(r.name)));
    const kpis = el("div", "q-kpis");
    for (const k of cfg.dashboard.kpis) {
      const value = await kpi(k);
      if (value === null) continue;
      const card = el("div", "q-kpi");
      add(card, el("div", "q-kpi-label", k.label), el("div", "q-kpi-value", value));
      const every = await rows((k.resource === "*" ? primary() : by(k.resource)).name);
      if (k.agg === "count" && k.where && every.length) {  // a filtered count shows its share of everything in the module
        const part = every.filter((i) => where(i, k.where)).length;
        const track = el("div", "q-kpi-bar");
        const fillEl = el("div", "q-kpi-bar-fill");
        fillEl.style.width = Math.round((100 * part) / every.length) + "%";
        track.appendChild(fillEl);
        add(card, track, el("div", "q-kpi-note", `${Math.round((100 * part) / every.length)}% of ${every.length}`));
      } else {
        const r = k.resource === "*" ? primary() : by(k.resource);
        add(card, el("div", "q-kpi-note", `from ${count(every.length, r.singular.replace(/_/g, " "), r.label.toLowerCase())}`));
      }
      kpis.appendChild(card);
    }
    const charts = el("div", "q-grid-2");
    for (const c of cfg.dashboard.charts) { const node = await chart(c); if (node) charts.appendChild(node); }
    const recent = [];
    for (const r of cfg.resources) for (const item of await rows(r.name)) recent.push({ r, item });
    recent.sort((a, b) => String(b.item.created_at || "").localeCompare(String(a.item.created_at || "")) || b.item.id - a.item.id);
    const feed = el("section", "q-card");
    feed.appendChild(el("h2", "", "Recent activity"));
    if (!recent.length) feed.appendChild(el("p", "muted", cfg.empty.default));
    const ul = el("ul", "q-recent");
    for (const { r, item } of recent.slice(0, 6)) {
      const li = el("li");
      const main = el("div", "q-recent-main");
      const a = el("a", "q-recent-title", titleOf(r, item));
      a.href = `#/${r.name}/${item.id}`;
      a.style.display = "block";
      a.style.color = "inherit";
      add(main, a, el("div", "q-recent-sub", [pretty(r.singular), ago(item.created_at)].filter(Boolean).join(" · ")));
      add(li, el("span", "q-recent-icon", r.icon || cfg.icon), main);
      ul.appendChild(li);
    }
    feed.appendChild(ul);
    sections.push(head(cfg.title, cfg.subtitle), kpis.childNodes.length ? kpis : null, charts.childNodes.length ? charts : null, feed);
    return sections;
  }
  async function listPage(r) {
    setCrumbs([{ text: "Dashboard", href: "#/" }, { text: r.label }]);
    const items = await rows(r.name);
    const box = el("div", "q-panel");
    box.style.paddingTop = "0";
    listBlock(r, items, r.name, box, { showParent: !!r.parent });
    const addBtn = button(`+ New ${r.singular}`, createForm(r, null));
    const clearBtn = r.clear ? button("Clear all", () => confirmBox(`Remove every ${r.singular}?`, async () => { await call("DELETE", r.clear); invalidate(); await render(); }), "btn-secondary") : null;
    if (hooks.loaded && r.name === primary().name) hooks.loaded({ resource: r.name, items, data: { items } });
    return [head(r.label, count(items.length, r.singular.replace(/_/g, " "), r.label.toLowerCase()), clearBtn, addBtn), box];
  }
  async function detailPage(r, id) {
    const items = await rows(r.name);
    const item = items.find((i) => String(i.id) === String(id));
    const crumbs0 = [{ text: "Dashboard", href: "#/" }];
    if (!item) {
      setCrumbs([...crumbs0, { text: r.label, href: `#/${r.name}` }, { text: "Not found" }]);
      return [head("Not found", `There is no ${r.singular} with that number.`, button(`Back to ${r.label.toLowerCase()}`, () => { location.hash = `#/${r.name}`; })), empty(r, `This ${r.singular} was deleted or never existed.`)];
    }
    const p = r.parent ? by(r.parent) : null;
    setCrumbs([...crumbs0, ...(p ? [{ text: p.label, href: `#/${p.name}` }, { text: titleOf(p, item._parent), href: `#/${p.name}/${item._parent.id}` }] : [{ text: r.label, href: `#/${r.name}` }]), { text: titleOf(r, item) }]);
    const card = el("section", "q-card");
    const dl = el("dl", "q-detail");
    for (const n of r.detail || r.columns) {
      const f = fieldOf(r, n);
      if (!f || n === r.title) continue;
      const dd = el("dd");
      dd.appendChild(cell(r, f, item));
      dl.appendChild(add(el("div"), el("dt", "", f.label), dd));
    }
    if (p) { const dd = el("dd"); const a = el("a", "", titleOf(p, item._parent)); a.href = `#/${p.name}/${item._parent.id}`; dd.appendChild(a); dl.appendChild(add(el("div"), el("dt", "", pretty(p.singular)), dd)); }
    card.appendChild(dl);
    const acts = el("div", "q-spacer");
    for (const a of r.actions) acts.appendChild(actionButton(r, a, item));
    add(acts, button("Edit", editForm(r, item), "btn-secondary"), button("Delete", removeItem(r, item, () => { location.hash = p ? `#/${p.name}/${item._parent.id}` : `#/${r.name}`; }), "btn-secondary"));
    const out = [head(titleOf(r, item), (r.subtitle || []).map((n) => item[n]).filter(Boolean).join(" · ") || pretty(r.singular), acts), card];
    const kids = (r.children || []).map(by).filter(Boolean);
    if (kids.length) {
      const tabs = el("div", "q-tabs");
      tabs.setAttribute("role", "tablist");
      const panel = el("div", "q-panel");
      const current = () => by(state.tab[r.name + ":" + id] || kids[0].name);
      const paint = async () => {
        clear(tabs);
        for (const k of kids) {
          const n = (await rows(k.name)).filter((x) => x._parent && x._parent.id === item.id).length;
          const t = el("button", "q-tab");
          t.type = "button";
          t.setAttribute("role", "tab");
          t.setAttribute("aria-selected", String(k.name === current().name));
          add(t, k.label, el("span", "q-pill", String(n)));
          t.dataset.tab = k.name;
          t.addEventListener("click", () => { state.tab[r.name + ":" + id] = k.name; paint(); });
          tabs.appendChild(t);
        }
        const k = current();
        const mine = (await rows(k.name)).filter((x) => x._parent && x._parent.id === item.id);
        clear(panel);
        const bar = el("div", "q-toolbar");
        if (k.capacity && item[k.capacity.field] !== undefined) {
          const used = mine.filter((x) => !(k.capacity.free || []).includes(x[k.capacity.status])).length;
          const cap = Number(item[k.capacity.field]) || 0;
          const meter = el("div", "q-meter");
          const track = el("div", "q-meter-track");
          const fillEl = el("div", `q-meter-fill${used >= cap ? " q-full" : ""}`);
          fillEl.style.width = Math.min(100, cap ? Math.round((100 * used) / cap) : 0) + "%";
          track.appendChild(fillEl);
          add(meter, `${used} of ${cap} places taken`, track, used >= cap ? el("span", "badge badge-danger", "Full") : null);
          bar.appendChild(meter);
        }
        const spacer = el("span", "q-count");
        bar.appendChild(spacer);
        bar.appendChild(button(`+ New ${k.singular}`, createForm(k, item.id)));
        const list = el("div");
        panel.appendChild(bar);
        listBlock(k, mine, `${k.name}@${item.id}`, list, { addLabel: `Add ${k.singular}` });
        panel.appendChild(list);
      };
      out.push(tabs, panel);
      await paint();
    }
    if (hooks.loaded && r.name === primary().name) hooks.loaded({ resource: r.name, items, data: { items } });
    return out;
  }
  async function about() {
    setCrumbs([{ text: "Dashboard", href: "#/" }, { text: "About" }]);
    const card = el("section", "q-card q-about");
    card.appendChild(el("h2", "", "About this app"));
    card.appendChild(el("p", "muted", cfg.subtitle || cfg.title));
    card.appendChild(el("p", "", `Built by Q: ${cfg.resources.length === 1 ? "one module" : cfg.resources.length + " modules"} (${cfg.resources.map((r) => r.label).join(", ")}).`));
    const left = el("section", "q-card q-about");
    left.appendChild(el("h2", "", "Not in this version"));
    if (cfg.notIncluded.length) { const ul = el("ul"); for (const x of cfg.notIncluded) ul.appendChild(el("li", "", x)); left.appendChild(ul); }
    else left.appendChild(el("p", "muted", "Nothing was left out of the request."));
    return [head("About"), card, left];
  }

  // ---- router and chrome --------------------------------------------------------------------------------------------------------------------------------
  const route = () => { const parts = (location.hash || "").replace(/^#\/?/, "").split("/"); return { name: parts[0] || "", id: parts[1] }; };
  async function render() {
    const token = ++state.token;
    const { name, id } = route();
    for (const a of sideNav.querySelectorAll ? sideNav.querySelectorAll("a") : []) a.removeAttribute("aria-current");
    const current = sideNav.querySelector && sideNav.querySelector(`a[data-route="${name}"]`);
    if (current) current.setAttribute("aria-current", "page");
    let nodes;
    try {
      const r = by(name);
      nodes = name === "about" ? await about() : r ? (id ? await detailPage(r, id) : await listPage(r)) : await dashboard();
      if (!name && hooks.loaded) { const p = primary(); const items = await rows(p.name); hooks.loaded({ resource: p.name, items, data: { items } }); }
    } catch (e) {
      nodes = [head("Something went wrong"), el("div", "alert alert-error", e.detail || "The page could not be loaded. Try again.")];
    }
    if (token !== state.token) return;
    clear(view);
    for (const n of nodes) if (n) view.appendChild(n);
    refreshCounts();
  }
  // the sidebar shows how many there are of everything, also of what this page did not need to read
  function refreshCounts() {
    for (const r of cfg.resources) {
      rows(r.name).then((list) => {
        const badge = sideNav.querySelector && sideNav.querySelector(`[data-count="${r.name}"]`);
        if (badge) badge.textContent = String(list.length);
      }).catch(() => {});
    }
  }
  function chrome(root) {
    const app = el("div", "q-app");
    const side = el("aside", "q-side");
    const brand = el("div", "q-brand");
    const text = el("div");
    add(text, el("h2", "q-brand-name", cfg.title), cfg.subtitle ? el("p", "q-brand-sub", cfg.subtitle) : null);
    add(brand, el("span", "q-brand-icon", cfg.icon), text);
    sideNav = el("nav", "q-nav");
    sideNav.setAttribute("aria-label", "Main");
    const link = (route_, icon, label, count_) => {
      const a = el("a");
      a.href = `#/${route_}`;
      a.dataset.route = route_;
      add(a, el("span", "q-nav-icon", icon), el("span", "", label));
      if (count_) { const c = el("span", "q-nav-count", ""); c.dataset.count = count_; a.appendChild(c); }
      return a;
    };
    add(sideNav, link("", "▦", "Dashboard"), el("div", "q-nav-label", "Modules"), ...cfg.resources.map((r) => link(r.name, r.icon || "•", r.label, r.name)), el("div", "q-nav-label", "App"), link("about", "ⓘ", "About"));
    const foot = el("div", "q-side-foot");
    if (cfg.notIncluded.length) {
      const note = el("aside", "q-scope");
      note.id = "scope-note";
      add(note, el("strong", "", "Not in this version:"), " ", cfg.notIncluded.join(", ") + ".");
      foot.appendChild(note);
    }
    const topNav = (cfg.ui || {}).nav === "top";
    add(side, brand, sideNav, topNav ? null : foot);
    const main = el("div", "q-main");
    const top = el("header", "q-top");
    crumbs = el("nav", "q-crumbs");
    crumbs.setAttribute("aria-label", "Breadcrumb");
    const actions = el("div", "q-top-actions");
    const mode = button("◐", () => {
      const next = document.documentElement.dataset.mode === "dark" ? "light" : "dark";
      document.documentElement.dataset.mode = next;
      try { localStorage.setItem("q-mode", next); } catch { /* private mode */ }
    }, "q-btn-icon");
    mode.title = "Switch between light and dark";
    mode.setAttribute("aria-label", "Switch between light and dark");
    actions.appendChild(mode);
    add(top, crumbs, actions);
    view = el("main", "q-content");
    view.id = "view";
    const hook = document.getElementById && document.getElementById("top-slot");
    add(main, top);
    if (hook && hook.parentNode === root) main.appendChild(hook);
    main.appendChild(view);
    if (topNav) main.appendChild(foot);
    add(app, side, main);
    clear(root);
    root.appendChild(app);
  }
  function mount(config, h = {}) {
    cfg = config;
    hooks = h;
    const html = document.documentElement;
    html.dataset.skin = cfg.skin || "studio";
    const ui = cfg.ui || {};
    html.dataset.nav = ui.nav || "side";  // the layout accent of the skill pack: where the navigation is, how dense the lists are, how charts are drawn
    html.dataset.density = ui.density || "cozy";
    if (DARK_SIDEBAR.includes(html.dataset.skin)) html.dataset.sb = "dark";
    let mode = "";
    try { mode = localStorage.getItem("q-mode") || ""; } catch { /* private mode */ }
    const asked = (typeof location.search === "string" && /[?&]mode=(light|dark)\b/.exec(location.search)) || null;  // ?mode=dark for a screenshot or a link
    html.dataset.mode = (asked && asked[1]) || mode || (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.body.classList.add("q-body");
    chrome(document.getElementById("app"));
    window.addEventListener("hashchange", render);
    return render();
  }
  window.Q = { mount, state, rows, call };
})();
