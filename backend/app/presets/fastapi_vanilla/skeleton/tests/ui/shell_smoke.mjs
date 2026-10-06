// Runs static/shell.js and static/app.js in a small fake browser and visits every page: the dashboard, each list page, a detail page, About, a form, an action.
// `node tests/ui/shell_smoke.mjs` from the project folder; exit code 1 and a message when a page does not draw.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert'
import vm from 'node:vm'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

// ---- a tiny DOM ------------------------------------------------------------------------------------------------------------------------------------
class Text { constructor(t) { this.nodeType = 3; this.data = t } get textContent() { return this.data } set textContent(v) { this.data = v } }
class Node {
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
const html = new Node('html')
const body = new Node('body')
html.appendChild(body)
const app = new Node('div'); app.id = 'app'; body.appendChild(app)
const slot = new Node('div'); slot.id = 'top-slot'; app.appendChild(slot)
{ // what a request added to the slot in index.html (a progress bar, a banner) exists in a real browser: make the same elements here
  const page = readFileSync(join(root, 'static', 'index.html'), 'utf8')
  const inner = (page.match(/<div id="top-slot">([\s\S]*?)<\/div>\s*<\/div>\s*<noscript/) ?? [])[1] ?? ''
  for (const m of inner.matchAll(/id="([\w-]+)"/g)) { const n = new Node('div'); n.id = m[1]; slot.appendChild(n) }
}
const listeners = {}
const location = { hash: '' }
globalThis.document = { createElement: (t) => new Node(t), createTextNode: (t) => new Text(t), getElementById: (id) => html.all((n) => n.id === id)[0] ?? null, querySelector: (s) => html.querySelector(s), body, documentElement: html }
globalThis.window = globalThis
globalThis.location = location
globalThis.addEventListener = (e, f) => (listeners[e] ??= []).push(f)
globalThis.localStorage = { getItem: () => null, setItem() {} }
globalThis.matchMedia = () => ({ matches: false })
globalThis.setTimeout = () => 0
const flush = () => new Promise((r) => setImmediate(r))
const go = async (hash) => { location.hash = hash; for (const f of listeners.hashchange ?? []) await f(); await flush(); await flush() }

// ---- a stub API: sample rows for whatever the description lists ------------------------------------------------------------------------------------
let cfg = null
const calls = []
const sample = (r, i, parentId) => {
  const row = { id: i, created_at: '2026-01-15 10:00:00' }
  if (r.parent) row[r.parent.replace(/s$/, '') + '_id'] = parentId
  for (const f of [...r.fields, ...(r.extra ?? [])]) {
    row[f.name] = f.options ? f.options[(i - 1) % f.options.length] : { money: 1200 * i, rating: 4, integer: 10 * i, number: 2.5 * i, counter: 2, checkbox: false, date: '2026-01-15', time: '10:30', phone: '9876543210', email: `a${i}@example.com` }[f.kind] ?? `${f.label} ${i}`
  }
  return row
}
globalThis.fetch = async (url, opts = {}) => {
  const method = opts.method ?? 'GET'
  calls.push({ method, url: String(url), body: opts.body })
  let data = {}
  if (method === 'GET') {
    const path = String(url).split('?')[0]
    for (const r of cfg.resources) {
      const m = path.match(new RegExp('^' + r.list.replace(/\{parent\}/, '(\\d+)') + '$'))
      if (m) data = { [r.listKey ?? 'items']: [sample(r, 1, Number(m[1] ?? 0)), sample(r, 2, Number(m[1] ?? 0))] }
    }
  }
  return { ok: true, status: 200, json: async () => data }
}

// ---- load the shell and the app ---------------------------------------------------------------------------------------------------------------------
const read = (f) => readFileSync(join(root, 'static', f), 'utf8')
try { vm.runInThisContext(read('ui-kit.js'), { filename: 'ui-kit.js' }) } catch (e) { globalThis.UI = globalThis.UI ?? {} }  // the page loads the kit before the shell: a request may call UI.progress
vm.runInThisContext(read('shell.js'), { filename: 'shell.js' })
const real = window.Q.mount
window.Q.mount = (c, h) => { cfg = c; return real(c, h) }
vm.runInThisContext(read('app.js'), { filename: 'app.js' })
await flush(); await flush()
const view = () => html.querySelector('#view')
const text = () => view().textContent
const failed = (what) => `${what}: ${text().slice(0, 200)}`

assert.ok(cfg && cfg.resources.length, 'app.js must call Q.mount with resources')
assert.equal(html.dataset.skin, cfg.skin, 'the skin is applied')
assert.ok(html.querySelector('#top-slot'), 'the request hook slot survives')
const links = html.querySelectorAll('a[data-route]')
for (const r of cfg.resources) assert.ok(links.some((a) => a.dataset.route === r.name), `the sidebar links to ${r.name}`)
assert.ok(!text().includes('Something went wrong'), failed('the dashboard'))
assert.ok(view().querySelectorAll('.q-kpi').length >= 1, 'the dashboard shows KPI cards')
if (cfg.dashboard.charts.length) assert.ok(view().querySelectorAll('.q-bar').length >= 1, 'the dashboard draws a chart')
const ui = cfg.ui ?? {}
assert.equal(html.dataset.nav, ui.nav ?? 'side', 'the navigation placement of the pack is applied')
assert.equal(html.dataset.density, ui.density ?? 'cozy', 'the density of the pack is applied')
if (cfg.dashboard.charts.length) {
  assert.ok(view().querySelectorAll('.q-chart-total').length >= 1, 'every chart card shows its total')
  if (ui.charts === 'columns') assert.ok(view().querySelectorAll('.q-cols .q-bar').length >= 1, 'column charts are drawn upright')
}
if (cfg.notIncluded.length) assert.ok(html.querySelector('#scope-note'), 'the note on what is left out is on every page, also with the navigation on top')

for (const r of cfg.resources) {
  await go('#/' + r.name)
  assert.ok(!text().includes('Something went wrong'), failed(`the ${r.name} page`))
  assert.ok(text().includes(r.label), `the ${r.name} page has its heading`)
  const rowsOnPage = view().querySelectorAll('tbody tr')
  assert.equal(rowsOnPage.length, r.parent ? 4 : 2, `the ${r.name} table lists the sample rows`)
  for (const a of r.actions) assert.equal(view().querySelectorAll(`button[data-action="${a.name}"]`).length, rowsOnPage.length, `a ${a.name} button on every ${r.singular}`)
  await go(`#/${r.name}/1`)
  assert.ok(!text().includes('Something went wrong') && !text().includes('Not found'), failed(`the ${r.singular} detail page`))
  if (r.children.length) assert.equal(view().querySelectorAll('.q-tab').length, r.children.length, `a tab for every related resource of ${r.name}`)
  for (const a of r.actions) assert.ok(view().querySelectorAll(`button[data-action="${a.name}"]`).length >= 1, `the detail page of ${r.singular} has ${a.name}`)
}
// the board (kanban): a resource with a status field can be switched from its table to columns; cards move by drag and drop or by their Move to list
const statusOf = (r) => {
  const n = r.flow && Object.keys(r.flow)[0]
  const f = r.fields.find((x) => x.name === n && x.options) || r.fields.find((x) => x.options && x.options.length >= 2 && x.options.length <= 8 && /status|stage|state|phase/i.test(x.name))
  return f && f.options.length >= 2 ? f : null
}
let dragged = false
for (const r of cfg.resources) {
  const sf = statusOf(r)
  await go('#/' + r.name)
  const toggle = view().querySelector('#view-board')
  if (!sf) { assert.ok(!toggle, `no board switch on ${r.name}: it has no status field`); continue }
  assert.ok(toggle, `${r.name} can be shown as a board by ${sf.name}`)
  const total = view().querySelectorAll('tbody tr').length
  await toggle.click(); await flush()
  assert.ok(!text().includes('Something went wrong'), failed(`the ${r.name} board`))
  assert.equal(view().querySelectorAll('.q-col').length, sf.options.length, `a column for every label of ${sf.name}`)
  assert.equal(view().querySelectorAll('.q-kcard').length, total, `a card for every ${r.singular} of the table`)
  assert.equal(view().querySelectorAll('tbody tr').length, 0, 'the board replaces the table')
  const movable = view().querySelectorAll('.q-kcard').find((c) => c.querySelector('select'))
  if (movable) {
    const before = calls.length
    const sel = movable.querySelector('select')
    const to = sel.childNodes[1].value
    if (!dragged) {
      dragged = true
      await movable.fire('dragstart', { dataTransfer: { setData() {} } })
      const col = view().querySelectorAll('.q-col').find((c) => c.dataset.value === to)
      await col.fire('dragover', { dataTransfer: {} })
      await col.fire('drop', { dataTransfer: {} })
    } else {
      sel.value = to
      await sel.fire('change')
    }
    await flush(); await flush()
    assert.ok(calls.slice(before).some((c) => (c.method === 'POST' || c.method === 'PUT') && c.url.startsWith('/api')), `moving a ${r.singular} to ${to} writes to the API`)
  }
  await go('#/' + r.name)
  await view().querySelector('#view-table').click(); await flush()
  assert.equal(view().querySelectorAll('tbody tr').length, total, 'the table view comes back')
}
await go('#/about')
assert.ok(text().includes('Not in this version'), 'the About page lists what is left out')
await go('#/')

// a form: New <thing> opens a modal with an input for each field; saving POSTs to the create URL
const first = cfg.resources.find((r) => !r.parent)
await go('#/' + first.name)
const addButton = view().querySelectorAll('button').find((b) => b.textContent.startsWith('+ New'))
assert.ok(addButton, 'every list page has a New button')
await addButton.click(); await flush()
const form = html.querySelector('form')
assert.ok(form, 'New opens a form')
assert.equal(form.querySelectorAll('input, select, textarea').length, first.fields.length, 'the form has an input for every field')
for (const f of first.fields) { const i = form.querySelector('#f-' + f.name); i.value = f.options ? f.options[0] : { money: '10', rating: '4', integer: '5', number: '1.5', date: '2026-02-01', time: '09:00' }[f.kind] ?? 'x'; if (f.kind === 'checkbox') i.checked = true }
await form.fire('submit'); await flush(); await flush()
const posted = calls.find((c) => c.method === 'POST' && c.url === first.create)
assert.ok(posted, `saving the form POSTs to ${first.create}`)
assert.deepEqual(Object.keys(JSON.parse(posted.body)).sort(), first.fields.map((f) => f.name).sort(), 'only the fields of the contract are sent')

// an action button POSTs to its endpoint
for (const r of cfg.resources) {
  const a = r.actions.find((x) => x.kind === 'set' || x.kind === 'increment')
  if (!a) continue
  await go('#/' + r.name)
  const b = view().querySelectorAll(`button[data-action="${a.name}"]`).find((x) => !x.disabled)
  if (!b) continue
  await b.click(); await flush(); await flush()
  assert.ok(calls.some((c) => c.method === 'POST' && c.url === a.url.replace('{id}', '1') || c.url === a.url.replace('{id}', '2')), `${a.name} POSTs to ${a.url}`)
  break
}
console.log('shell smoke ok: ' + cfg.resources.map((r) => r.name).join(', '))
