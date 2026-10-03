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
    expect(orderDemos([rec('inventory'), rec('bad', { ok: false }), rec('expense-ask'), rec('calculator-fault')]).map((r) => r.name)).toEqual(['calculator-fault', 'expense-ask', 'inventory'])
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
