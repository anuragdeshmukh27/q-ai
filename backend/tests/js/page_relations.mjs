// Runs a generated relational page (index.html ids + app.js) against a tiny fake DOM and a stub fetch; tests/test_relations.py runs it with node.
// node page_relations.mjs <ui-kit.js> <index.html> <app.js>
import { readFileSync } from 'node:fs'
import assert from 'node:assert'

class N {
  constructor(t) { this.tag = t; this.className = ''; this.childNodes = []; this._t = ''; this.l = {}; this.attrs = {}; this.value = ''; this.checked = false; this.style = {}; this.classList = { add() {} } }
  set textContent(v) { this._t = v; this.childNodes = [] }
  get textContent() { return this._t }
  appendChild(c) { this.childNodes.push(c); return c }
  append(...c) { c.forEach((x) => this.appendChild(x)) }
  setAttribute(k, v) { this.attrs[k] = v }
  addEventListener(e, f) { this.l[e] = f }
  remove() {}
  reset() { this.resets = (this.resets ?? 0) + 1 }
  find(pred, out = []) { if (pred(this)) out.push(this); this.childNodes.forEach((c) => c.find(pred, out)); return out }
}
const [kit, htmlPath, jsPath] = process.argv.slice(2)
const html = readFileSync(htmlPath, 'utf8')
const ids = {}
for (const m of html.matchAll(/id="([^"]+)"/g)) ids[m[1]] = new N('el')
for (const id of ['sort', 'child-sort']) if (ids[id]) ids[id].value = 'new' // a select shows its first option
globalThis.document = { createElement: (t) => new N(t), getElementById: (id) => ids[id], querySelector: () => null, body: new N('body') }
globalThis.window = globalThis
globalThis.setTimeout = () => {}

const post = { id: 1, title: 'Hello', content: 'First', author: 'ada', upvotes: 2, downvotes: 1, created_at: 'x' }
const comment = { id: 7, post_id: 1, content: 'Nice', author: 'bob', upvotes: 0, downvotes: 0, created_at: 'x' }
const calls = []
globalThis.fetch = async (url, opts = {}) => {
  calls.push({ method: opts.method ?? 'GET', url, body: opts.body })
  let data = {}
  if (url.startsWith('/api/posts?')) data = { items: [post] }
  else if (url.startsWith('/api/posts/1/comments') && (opts.method ?? 'GET') === 'GET') data = { items: [comment] }
  else if (url.endsWith('/upvote') || url.endsWith('/downvote')) data = post
  return { ok: true, json: async () => data }
}
const flush = () => new Promise((r) => setImmediate(r))
const buttons = (box) => box.find((n) => n.tag === 'button')
const labelled = (box, text) => buttons(box).find((b) => b.textContent.startsWith(text))

eval(readFileSync(kit, 'utf8'))
eval(readFileSync(jsPath, 'utf8'))
await flush()
assert.equal(calls[0].url, '/api/posts?sort=new', 'the list loads sorted newest first')
const up = labelled(ids.list, '▲')
assert.ok(up, 'the vote button is drawn in the vote column')
assert.ok(ids.list.find((n) => n.className === 'vote-score' && n.textContent === '1').length, 'the score (upvotes - downvotes) sits between the buttons')
assert.ok(ids.list.find((n) => n.className === 'byline' && n.textContent.startsWith('by ada')).length, 'the byline reads "by author · time ago"')

up.l.click()
await flush()
assert.ok(calls.some((c) => c.method === 'POST' && c.url === '/api/posts/1/upvote'), 'upvote posts to the action endpoint')

assert.ok(calls.some((c) => c.method === 'GET' && c.url === '/api/posts/1/comments'), 'the comment count of every post is fetched')
const open = buttons(ids.list).find((b) => b.textContent.includes('comment'))
assert.ok(open && open.textContent.includes('1 comment') && !open.textContent.includes('1 comments'), 'the footer says "1 comment", not "1 comments"')
open.l.click()
await flush()
assert.equal(ids.detail.style.display, '', 'opening a post shows its own page')
assert.equal(ids['feed-view'].style.display, 'none', 'and hides the feed')
assert.ok(ids.post.find((n) => n.textContent === 'Hello').length, 'the open post is shown at the top')
assert.ok(calls.some((c) => c.method === 'GET' && c.url.startsWith('/api/posts/1/comments')), 'the comments are loaded from the nested path')
assert.ok(ids.children.find((n) => n.textContent === 'Nice').length, 'the comment is listed below the post')
assert.ok(ids['child-count'].textContent === '1 comment', 'singular count')

ids['child-content'].value = 'Thanks'
ids['child-author'].value = 'eve'
await ids['child-form'].l.submit({ preventDefault() {} })
await flush()
const added = calls.find((c) => c.method === 'POST' && c.url === '/api/posts/1/comments')
assert.ok(added, 'a comment is posted to the nested path')
assert.deepEqual(JSON.parse(added.body), { content: 'Thanks', author: 'eve' }, 'only the comment fields are sent, never the post id or counters')

ids.title.value = 'New'; ids.content.value = 'Body'; ids.author.value = 'zed'
await ids.form.l.submit({ preventDefault() {} })
await flush()
assert.deepEqual(JSON.parse(calls.find((c) => c.method === 'POST' && c.url === '/api/posts').body), { title: 'New', content: 'Body', author: 'zed' })

ids.sort.value = 'top'
await ids.sort.l.change()
await flush()
assert.ok(calls.some((c) => c.url === '/api/posts?sort=top'), 'the sort select reloads the list')

labelled(ids.list, 'Delete').l.click()
await flush()
assert.ok(calls.some((c) => c.method === 'DELETE' && c.url === '/api/posts/1'))
assert.equal(ids.detail.style.display, 'none', 'deleting the open post closes its page')
assert.equal(ids['feed-view'].style.display, '', 'and shows the feed again')
console.log('page ok')
