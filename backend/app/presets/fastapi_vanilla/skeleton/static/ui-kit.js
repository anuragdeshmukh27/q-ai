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
//       formats: { amount: "money" }  per-field format: "money" | "num" | "symbol"
//       done: "done"                  boolean field: strikes the row through when true
//       onToggle: (checked) => ...    with `done`: shows a checkbox at the start of the row; called with the new state
//       actions: [{ label: "Delete", kind: "danger", onClick: () => remove(item.id) }]   buttons ("danger" | "secondary" | "ghost")
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
  const FORMATS = { money: (v) => api.money(v), num: (v) => api.num(v), symbol: (v) => api.symbol(v) };
  const show = (item, field, formats = {}) => {
    const v = item[field];
    if (v === undefined || v === null || v === "") return "";
    const f = FORMATS[formats[field]];
    return f ? f(v) : String(v);
  };
  const api = {
    listItem(item, o = {}) {
      const li = el("li", o.done && item[o.done] ? "list-item done" : "list-item");
      if (o.done && o.onToggle) {
        const box = el("input", "item-check");
        box.type = "checkbox";
        box.checked = !!item[o.done];
        box.setAttribute("aria-label", "Mark as done");
        box.addEventListener("change", () => o.onToggle(box.checked));
        li.appendChild(box);
      }
      const main = el("span", "item-main");
      if (o.title) main.appendChild(el("div", "item-title", show(item, o.title, o.formats)));
      for (const f of o.details ?? []) {
        const text = show(item, f, o.formats);
        if (text) main.appendChild(el("div", "muted small", text));
      }
      li.appendChild(main);
      const badges = el("span", "item-badges");
      for (const f of o.badges ?? []) {
        const text = show(item, f, o.formats);
        if (text) badges.appendChild(el("span", `badge badge-${tone(text)}`, text));
      }
      if (badges.childNodes.length) li.appendChild(badges);
      if ((o.actions ?? []).length) {
        const box = el("span", "item-actions");
        for (const a of o.actions) {
          const b = el("button", `btn-sm btn-${a.kind ?? "secondary"}`, a.label);
          b.type = "button";
          b.addEventListener("click", a.onClick);
          box.appendChild(b);
        }
        li.appendChild(box);
      }
      return li;
    },
    renderList(box, items, build = {}, emptyText = "Nothing here yet.") {
      if (!items || !items.length) return api.empty(box, emptyText);
      box.textContent = "";
      const ul = el("ul", "list");
      for (const item of items) ul.appendChild(api.listItem(item, typeof build === "function" ? build(item) : build));
      box.appendChild(ul);
    },
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
