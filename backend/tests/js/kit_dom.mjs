// Renders UI.renderList against a tiny fake DOM; tests/test_p7.py runs it with node.
import { readFileSync } from 'node:fs'
class N { constructor(t){this.tag=t;this.className='';this.childNodes=[];this._t='';this.l={}} set textContent(v){this._t=v;this.childNodes=[]} get textContent(){return this._t}
  appendChild(c){this.childNodes.push(c);return c} append(...c){c.forEach(x=>this.appendChild(x))} addEventListener(e,f){this.l[e]=f}
  dump(i=0){return ' '.repeat(i)+`<${this.tag} class="${this.className}">${this._t}`+'\n'+this.childNodes.map(c=>c.dump(i+2)).join('')} }
globalThis.document = { createElement: (t) => new N(t), querySelector: () => null, body: new N('body') }
globalThis.window = globalThis
globalThis.setTimeout = () => {}
eval(readFileSync(process.argv[2], 'utf8'))
const box = new N('div'); let clicked = 0
UI.renderList(box, [{ id: 1, title: 'Buy milk', description: 'two litres', priority: 'High', amount: 12.5, done: true }, { id: 2, title: 'Walk', description: '', priority: 'whatever' }],
  (item) => ({ title: 'title', details: ['description'], badges: ['priority'], formats: { amount: 'money' }, done: 'done', actions: [{ label: 'Delete', kind: 'danger', onClick: () => clicked++ }] }), 'None yet')
console.log(box.dump())
box.childNodes[0].childNodes[0].childNodes[2].childNodes[0].l.click(); console.log('clicked', clicked)
const e = new N('div'); UI.renderList(e, [], {}, 'None yet'); console.log(e.dump())
