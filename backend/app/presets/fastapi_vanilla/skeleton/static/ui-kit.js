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
//       badges: ["priority"]          short categorical fields as coloured badges (high = red, medium = yellow, low = green, other = blue)
//       formats: { amount: "money" }  per-field format: "money" | "num" | "symbol"
//       done: "done"                  boolean field: strikes the row through when true
//       actions: [{ label: "Delete", kind: "danger", onClick: () => remove(item.id) }]   buttons ("danger" | "secondary" | "ghost")
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
  const TONES = { high: "danger", urgent: "danger", critical: "danger", overdue: "danger", medium: "warning", normal: "warning", pending: "warning",
                  low: "success", done: "success", paid: "success", complete: "success", completed: "success" };
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
        if (text) badges.appendChild(el("span", `badge badge-${TONES[text.toLowerCase()] ?? "info"}`, text));
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
