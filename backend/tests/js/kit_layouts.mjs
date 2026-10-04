// The UI kit's layouts (table, cards, checklist, feed), stat strip, plurals and relative time, against a tiny fake DOM. tests/test_p9b.py runs it with node.
// node kit_layouts.mjs <ui-kit.js>
import { readFileSync } from 'node:fs'
import assert from 'node:assert'

class N {
  constructor(t) { this.tag = t; this.className = ''; this.childNodes = []; this._t = ''; this.l = {}; this.attrs = {}; this.classList = { add: (c) => { this.className += ' ' + c } } }
  set textContent(v) { this._t = v; this.childNodes = [] }
  get textContent() { return this._t + this.childNodes.map((c) => c.textContent).join('') }
  appendChild(c) { this.childNodes.push(c); return c }
  append(...c) { c.forEach((x) => this.appendChild(x)) }
  setAttribute(k, v) { this.attrs[k] = v }
  addEventListener(e, f) { this.l[e] = f }
  find(pred, out = []) { if (pred(this)) out.push(this); this.childNodes.forEach((c) => c.find && c.find(pred, out)); return out }
}
globalThis.document = { createElement: (t) => new N(t), createTextNode: (t) => { const n = new N('#text'); n._t = t; return n }, querySelector: () => null, body: new N('body') }
globalThis.window = globalThis
globalThis.setTimeout = () => {}
eval(readFileSync(process.argv[2], 'utf8'))
const cls = (box, c) => box.find((n) => n.className.split(' ').includes(c))
const texts = (box, c) => cls(box, c).map((n) => n.textContent)
const button = (box, text) => box.find((n) => n.tag === 'button' && n.textContent.startsWith(text))[0]

// plurals, labels, relative time
assert.equal(UI.count(1, 'post', 'posts'), '1 post')
assert.equal(UI.count(2, 'post', 'posts'), '2 posts')
assert.equal(UI.count(0, 'comment'), '0 comments')
assert.equal(UI.count(2, 'category'), '2 categories')
assert.equal(UI.count(1, 'day'), '1 day')
assert.equal(UI.label('due_date'), 'Due date')
assert.equal(UI.label('group_value'), 'Group', 'an SQL-keyword workaround is not part of the name')
const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString().slice(0, 19).replace('T', ' ')  // the database format: UTC, no zone
assert.equal(UI.timeAgo(iso(5 * 1000)), 'just now')
assert.equal(UI.timeAgo(iso(5 * 60 * 1000)), '5 min ago')
assert.equal(UI.timeAgo(iso(3 * 3600 * 1000)), '3 h ago')
assert.equal(UI.timeAgo(iso(2 * 86400 * 1000)), '2 days ago')
assert.equal(UI.timeAgo(iso(86400 * 1000)), '1 day ago')

// table: a header, a cell for every column (numbers formatted), badges, and the row's buttons
let removed = 0
const table = new N('div')
UI.renderTable(table, [{ id: 1, description: 'Lunch', amount: 12.5, category: 'Food' }], (i) => ({
  columns: [{ field: 'description', label: 'Description' }, { field: 'amount', label: 'Amount', format: 'money' }, { field: 'category', label: 'Category', badge: true }],
  actions: [{ label: 'Delete', kind: 'danger', onClick: () => removed++ }],
}))
assert.deepEqual(table.find((n) => n.tag === 'th').map((n) => n.textContent), ['Description', 'Amount', 'Category', ''])
assert.deepEqual(table.find((n) => n.tag === 'td').map((n) => n.textContent).slice(0, 3), ['Lunch', '$12.50', 'Food'], 'the amount is a column of the row')
assert.ok(cls(table, 'badge-teal').length + cls(table, 'badge-info').length + cls(table, 'badge-accent').length + cls(table, 'badge-pink').length >= 1, 'a category is a badge')
button(table, 'Delete').l.click()
assert.equal(removed, 1)

// cards: title, captioned detail lines, badge, numbers captioned with their label
const cards = new N('div')
UI.renderCards(cards, [{ id: 1, name: 'Ada', phone: '555', group: 'Work', quantity: 4 }], () => ({
  title: 'name', details: ['phone'], labels: { phone: 'Phone', quantity: 'Quantity' }, badges: ['group'], values: ['quantity'], formats: { quantity: 'num' }, actions: [{ label: 'Edit', onClick() {} }],
}))
assert.ok(cls(cards, 'card-grid').length && cls(cards, 'card-item').length, 'a grid of cards')
assert.deepEqual(texts(cards, 'item-detail'), ['Phone: 555'])
assert.deepEqual(texts(cards, 'item-value'), ['4Quantity'], 'a number shows with its caption')

// checklist: compact rows with a done box
let toggled = null
const check = new N('div')
UI.renderChecklist(check, [{ id: 1, title: 'Buy milk', done: true }], () => ({ title: 'title', done: 'done', onToggle: (v) => { toggled = v } }))
assert.ok(cls(check, 'checklist').length && cls(check, 'done').length)
check.find((n) => n.tag === 'input')[0].l.change()
assert.equal(toggled, true)
const empty = new N('div')
UI.renderChecklist(empty, [], {}, 'Nothing yet')
assert.ok(cls(empty, 'empty-state').length)

// feed: vote column (up / score / down), title, byline, comment button with a plural-aware count, captioned detail lines
let up = 0
const feed = new N('div')
const item = { id: 3, title: 'Hello', content: 'First post', company: 'Acme', author: 'ada', created_at: iso(120 * 1000) }
UI.renderFeed(feed, [item], () => ({
  title: 'title', author: 'author', details: ['company', 'content'], labels: { company: 'Company' }, score: 4, comments: 1, noun: 'comment', onOpen() {},
  actions: [{ label: '▲', slot: 'up', title: 'Upvote', onClick: () => up++ }, { label: '▼', slot: 'down', onClick() {} }, { label: 'Delete', kind: 'danger', onClick() {} }],
}))
assert.deepEqual(texts(feed, 'vote-score'), ['4'])
assert.equal(feed.find((n) => n.className === 'vote-col')[0].childNodes.map((n) => n.tag).join(), 'button,span,button', 'up, score, down')
button(feed, '▲').l.click()
assert.equal(up, 1)
assert.deepEqual(texts(feed, 'byline'), ['by ada · 2 min ago'])
assert.equal(button(feed, '💬').textContent, '💬 1 comment')
assert.deepEqual(texts(feed, 'feed-body'), ['Company: Acme', 'First post'])
assert.ok(cls(feed, 'feed-foot').length && button(cls(feed, 'feed-foot')[0], 'Delete'), 'the other buttons sit in the footer, not in the vote column')
assert.ok(cls(feed, 'feed-title').length && cls(feed, 'link').length, 'a title with onOpen is a link')
const compact = new N('div')
UI.renderFeed(compact, [{ id: 1, content: 'Nice', author: 'bob', rating: 4 }], () => ({ author: 'author', details: ['content'], values: ['rating'], formats: { rating: 'stars' }, compact: true }))
assert.ok(cls(compact, 'feed-comment').length, 'a comment row is compact')
assert.deepEqual(texts(compact, 'byline'), ['by bob · ★★★★☆'], 'a rating reads as stars in the byline')
assert.equal(cls(compact, 'item-values').length, 0, 'and is not drawn a second time as a value')

// stat strip: the count, the total, the average and the sums per category
const strip = new N('div')
UI.statStrip(strip, [{ amount: 10, category: 'Food' }, { amount: 5.5, category: 'Food' }, { amount: 4, category: 'Fun' }, { rating: 5 }, { rating: 3 }],
  { noun: 'expense', plural: 'expenses', sums: [{ field: 'amount', label: 'Total amount', format: 'money' }], averages: [{ field: 'rating', label: 'Average rating', format: 'stars' }], by: 'category', byField: 'amount', byFormat: 'money' })
assert.deepEqual(texts(strip, 'stat-label').slice(0, 3), ['Expenses', 'Total amount', 'Average rating'])
assert.deepEqual(texts(strip, 'stat-value').slice(0, 3), ['5', '$19.50', '★★★★☆ 4'])
assert.deepEqual(texts(strip, 'badge'), ['Food · $15.50', 'Fun · $4.00'], 'the largest category first')
console.log('kit layouts ok')
