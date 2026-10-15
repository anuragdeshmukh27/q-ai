// A small fake browser for the Node tests of the pages (no packages): a DOM with the few calls static/shell.js makes, a stub `fetch`, and `createBrowser`, which loads
// static/ui-kit.js, static/shell.js and static/app.js into it. Used by tests/ui/refusals.mjs. (tests/ui/shell_smoke.mjs keeps its own copy.)
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

class Text { constructor(t) { this.nodeType = 3; this.data = t } get textContent() { return this.data } set textContent(v) { this.data = v } }
export class Node {
  constructor(tag) { this.nodeType = 1; this.tagName = tag.toUpperCase(); this.childNodes = []; this.parentNode = null; this.attrs = {}; this.dataset = {}; this.style = {}; this.listeners = {}; this._cls = new Set(); this.value = ''; this.checked = false; this.disabled = false; this.id = ''; this.type = ''; this.href = '' }
  get className() { return [...this._cls].join(' ') }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)) }
  get classList() { const s = this._cls; return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), contains: (c) => s.has(c), toggle: (c) => (s.has(c) ? s.delete(c) : s.add(c)) } }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1) }
  get textContent() { return this.childNodes.map((c) => c.textContent).join('') + (this._text ?? '') }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; this._text = String(v) }
  appendChild(c) { if (c.parentNode) c.parentNode.childNodes = c.parentNode.childNodes.filter((x) => x !== c); c.parentNode = this; this.childNodes.push(c); return c }
  remove() { if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter((x) => x !== this); this.parentNode = null }
  setAttribute(k, v) { this.attrs[k] = String(v) }
  getAttribute(k) { return this.attrs[k] ?? null }
  removeAttribute(k) { delete this.attrs[k] }
  addEventListener(e, f) { (this.listeners[e] ??= []).push(f) }
  async fire(e, extra = {}) { for (const f of this.listeners[e] ?? []) await f({ preventDefault() {}, target: this, ...extra }) }
  click() { return this.fire('click') }
  focus() {}
  reset() {}
  all(pred, out = []) { for (const c of this.childNodes) if (c.nodeType === 1) { if (pred(c)) out.push(c); c.all(pred, out) } return out }
  querySelectorAll(sel) { return this.all(matcher(sel)) }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null }
  set innerHTML(v) { throw new Error('innerHTML is not allowed') }
}
function compound(s) {
  return { tag: (s.match(/^[a-z][a-z0-9]*/i) ?? [''])[0].toUpperCase(), id: (s.match(/#([\w-]+)/) ?? [])[1], cls: [...s.matchAll(/\.([\w-]+)/g)].map((x) => x[1]), attrs: [...s.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)].map((x) => [x[1], x[2]]) }
}
function is(n, m) {
  return (!m.tag || n.tagName === m.tag) && (!m.id || n.id === m.id) && m.cls.every((c) => n._cls.has(c))
    && m.attrs.every(([k, v]) => { const val = k.startsWith('data-') ? n.dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] : n.attrs[k]; return v === undefined ? val !== undefined : val === v })
}
function matcher(selector) {
  const chains = selector.split(',').map((s) => s.trim().split(/\s+/).map(compound))
  return (n) => chains.some((chain) => {
    if (!is(n, chain[chain.length - 1])) return false
    let up = n.parentNode
    for (let i = chain.length - 2; i >= 0; i--) { while (up && !is(up, chain[i])) up = up.parentNode; if (!up) return false; up = up.parentNode }
    return true
  })
}

/** What a stub `fetch` answers: `{ status, body }` (a JSON body) or `{ status, text }` (a body that is not JSON, like a gateway's HTML page). */
export const answerOf = ({ status, body, text }) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => { if (body === undefined || body === null) throw new SyntaxError(text ? 'Unexpected token < in JSON' : 'Unexpected end of JSON input'); return body },
})

/**
 * Loads the app into the fake browser. `route(method, url, body)` answers every request with `{status, body}` (or `{status, text}`); every request is kept in `calls`.
 * Returns the page's handles: `view()`, `text()`, `go('#/appointments')`, `flush()`, the `calls`, the `toasts()` shown so far and `html`.
 */
export async function createBrowser(route, { root = ROOT } = {}) {
  const html = new Node('html')
  const body = new Node('body')
  html.appendChild(body)
  const app = new Node('div'); app.id = 'app'; body.appendChild(app)
  const slot = new Node('div'); slot.id = 'top-slot'; app.appendChild(slot)
  const listeners = {}
  const location = { hash: '' }
  globalThis.document = { createElement: (t) => new Node(t), createTextNode: (t) => new Text(t), getElementById: (id) => html.all((n) => n.id === id)[0] ?? null, querySelector: (s) => html.querySelector(s), body, documentElement: html }
  globalThis.window = globalThis
  globalThis.location = location
  globalThis.addEventListener = (e, f) => (listeners[e] ??= []).push(f)
  globalThis.localStorage = { getItem: () => null, setItem() {} }
  globalThis.matchMedia = () => ({ matches: false })
  globalThis.setTimeout = () => 0  // a toast stays on the page, so a test can read it
  const calls = []
  globalThis.fetch = async (url, opts = {}) => {
    const method = opts.method ?? 'GET'
    const sent = opts.body ? JSON.parse(opts.body) : undefined
    calls.push({ method, url: String(url), body: sent })
    return answerOf(route(method, String(url), sent))
  }
  const flush = () => new Promise((r) => setImmediate(r))
  const read = (f) => readFileSync(join(root, 'static', f), 'utf8')
  try { vm.runInThisContext(read('ui-kit.js'), { filename: 'ui-kit.js' }) } catch { globalThis.UI = globalThis.UI ?? {} }
  vm.runInThisContext(read('shell.js'), { filename: 'shell.js' })
  vm.runInThisContext(read('app.js'), { filename: 'app.js' })
  await flush(); await flush()
  const view = () => html.querySelector('#view')
  const go = async (hash) => { location.hash = hash; for (const f of listeners.hashchange ?? []) await f(); await flush(); await flush() }
  const toasts = () => html.querySelectorAll('.toast').map((t) => ({ kind: t.className.includes('toast-error') ? 'error' : t.className.includes('toast-success') ? 'success' : 'info', text: t.textContent }))
  return { html, view, text: () => view().textContent, go, flush, calls, toasts }
}
