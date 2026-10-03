// Q UI kit helpers (locked preset file, loaded on every page before app.js). Everything is on the global `UI`.
//   UI.toast("Saved", "success")      small message in the corner ("success" | "error" | "info")
//   UI.num(1234.5)  UI.money(12.5)    formatted numbers: "1,234.5" and "$12.50"
//   UI.symbol("subtract")             operation word -> symbol ("−"); unknown words come back unchanged
//   UI.loading(box, "Loading…")       spinner inside a container
//   UI.empty(box, "Nothing here yet") empty state inside a container
// All text goes in with textContent, never innerHTML.
window.UI = (() => {
  const SYMBOLS = { add: "+", plus: "+", sum: "+", subtract: "−", minus: "−", multiply: "×", times: "×", divide: "÷", "divided by": "÷", power: "^", modulo: "%", mod: "%" };
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  return {
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
})();
