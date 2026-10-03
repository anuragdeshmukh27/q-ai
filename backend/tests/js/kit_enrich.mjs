// UI.listItem badges / toggle and UI.form against a tiny fake DOM; tests/test_enrich.py runs it with node.
import { readFileSync } from 'node:fs'
import assert from 'node:assert'
class N {
  constructor(t) { this.tag = t; this.className = ''; this.childNodes = []; this._t = ''; this.l = {}; this.attrs = {}; this.value = ''; this.checked = false }
  set textContent(v) { this._t = v; this.childNodes = [] }
  get textContent() { return this._t }
  appendChild(c) { this.childNodes.push(c); c.parent = this; return c }
  append(...c) { c.forEach((x) => this.appendChild(x)) }
  setAttribute(k, v) { this.attrs[k] = v }
  addEventListener(e, f) { this.l[e] = f }
  remove() { this.removed = true }
  find(pred, out = []) { if (pred(this)) out.push(this); this.childNodes.forEach((c) => c.find(pred, out)); return out }
}
const body = new N('body')
globalThis.document = { createElement: (t) => new N(t), querySelector: () => null, body }
globalThis.window = globalThis
globalThis.setTimeout = () => {}
eval(readFileSync(process.argv[2], 'utf8'))

// badges: fixed meanings for priorities / statuses, a steady colour for free labels
const tone = (label) => {
  const box = new N('div')
  UI.renderList(box, [{ id: 1, t: 'x', p: label }], { title: 't', badges: ['p'] })
  return box.find((n) => n.className.startsWith('badge ')).map((n) => n.className)[0]
}
assert.equal(tone('High'), 'badge badge-danger')
assert.equal(tone('Medium'), 'badge badge-warning')
assert.equal(tone('Low'), 'badge badge-success')
assert.equal(tone('To do'), 'badge badge-info')
assert.equal(tone('In progress'), 'badge badge-warning')
assert.equal(tone('Done'), 'badge badge-success')
assert.equal(tone('Food'), tone('Food'))
assert.match(tone('Food'), /^badge badge-(info|accent|teal|pink)$/)

// done toggle: a checkbox that reports its new state
const box = new N('div')
let toggled = null
UI.renderList(box, [{ id: 1, title: 'a', done: true }], { title: 'title', done: 'done', onToggle: (c) => { toggled = c } })
const check = box.find((n) => n.className === 'item-check')[0]
assert.ok(check && check.checked === true && check.type === 'checkbox')
check.checked = false
check.l.change()
assert.equal(toggled, false)
const plain = new N('div')
UI.renderList(plain, [{ id: 1, title: 'a', done: true }], { title: 'title', done: 'done' })
assert.equal(plain.find((n) => n.className === 'item-check').length, 0)

// edit dialog: fields, select of labels, typed values, closes after save
const fields = [{ name: 'title', label: 'Title' }, { name: 'priority', label: 'Priority', options: ['Low', 'Medium', 'High'] },
  { name: 'amount', label: 'Amount', type: 'number' }, { name: 'done', label: 'Done', type: 'checkbox' }]
let saved = null
const overlay = UI.form('Edit task', fields, { title: 'Buy milk', priority: 'High', amount: 2.5, done: true }, async (v) => { saved = v })
assert.ok(body.childNodes.includes(overlay))
const sel = overlay.find((n) => n.tag === 'select')[0]
assert.equal(sel.value, 'High')
assert.deepEqual(sel.childNodes.map((o) => o.textContent), ['Low', 'Medium', 'High'])
const form = overlay.find((n) => n.tag === 'form')[0]
await form.l.submit({ preventDefault() {} })
assert.deepEqual(saved, { title: 'Buy milk', priority: 'High', amount: 2.5, done: true })
assert.equal(overlay.removed, true)
// returning false keeps the dialog open
const o2 = UI.form('x', fields, {}, async () => false)
await o2.find((n) => n.tag === 'form')[0].l.submit({ preventDefault() {} })
assert.ok(!o2.removed)
console.log('OK')
