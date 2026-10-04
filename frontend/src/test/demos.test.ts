import { describe, expect, it } from 'vitest'
import type { RecordingMeta } from '../api'
import { card, duration, orderDemos, pickDefault } from '../demos'

const rec = (name: string, extra: Partial<RecordingMeta> = {}): RecordingMeta => ({ name, goal: 'Build a todo app: title', ok: true, seconds: 185, events: 10, ...extra })

describe('demo picker', () => {
  it('defaults to calculator-fault whatever the listing order is', () => {
    expect(pickDefault([rec('notes-search'), rec('calculator-fault'), rec('todo-approvals')])).toBe('calculator-fault')
  })
  it('falls back to the first good recording, and to nothing when there is none', () => {
    expect(pickDefault([rec('zzz', { ok: false }), rec('notes-search')])).toBe('notes-search')
    expect(pickDefault([])).toBe('')
  })
  it('orders the shipped recordings and hides failed ones', () => {
    expect(orderDemos([rec('inventory'), rec('bad', { ok: false }), rec('ask-employee'), rec('calculator-fault')]).map((r) => r.name)).toEqual(['calculator-fault', 'ask-employee', 'inventory'])
  })
  it('reads durations', () => {
    expect(duration(45)).toBe('45 s')
    expect(duration(185)).toBe('3 min 05 s')
  })
  it('uses the card text from the recording, with a fallback for old recordings', () => {
    expect(card(rec('a', { title: 'Todo app with priorities', app: 'Todo app', feature: 'Approvals' }))).toMatchObject({ title: 'Todo app with priorities', app: 'Todo app', feature: 'Approvals', duration: '3 min 05 s' })
    expect(card(rec('old')).title).toBe('Todo app')
  })
})

describe('the build numbers on a demo card', () => {
  it('reads as one line, and is empty for an older recording', () => {
    const stats = { modules: 4, tables: 4, endpoints: 41, pages: 10, functions: 62, lines: 1240, agent_share_functions: 0.71, agent_share_lines: 0.2 }
    expect(card(rec('flagship', { stats })).stats).toBe('4 modules, 4 tables, 41 endpoints, 10 pages, 62 functions (71% written by agents), 1,240 lines')
    expect(card(rec('old')).stats).toBe('')
    expect(orderDemos([rec('flagship'), rec('instagram'), rec('inventory')]).map((r) => r.name)).toEqual(['inventory', 'instagram', 'flagship'])
  })
})

describe('finish-it card', () => {
  it('says what was found and closed, not the tables of a generated app', () => {
    const c = card(rec('finish-it', { title: 'Finish a half-built app', stats: { modules: 0, tables: 0, endpoints: 0, pages: 0, finish: true, gaps: 6, fixed: 6, files: 2, insertions: 40, deletions: 4 } }))
    expect(c.stats).toBe('6 gaps found, 6 closed in 2 files, +40 −4 on its own branch')
  })
})
