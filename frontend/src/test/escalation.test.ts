import { describe, expect, it } from 'vitest'
import { decidedBy } from '../approvalText'
import { ESCALATION_BUTTONS, explainEscalation } from '../escalation'
import { OfficeModel, type AgentInfo, type QEvent, type Visual } from '../model'

const ROSTER: AgentInfo[] = ['planner', 'backend'].map((id, i) => ({ id, name: id === 'planner' ? 'Priya' : 'Rohan', role: id, desk: [3 + i, 2], sprite: { palette: 'teal', accessory: 'none' } }))
let seq = 0
const ev = (type: string, rest: Record<string, unknown> = {}): QEvent => ({ seq: seq++, ts: 0, type, ...rest })

function setup() {
  const m = new OfficeModel()
  m.setRoster(ROSTER)
  const seen: Visual[] = []
  m.onVisual((v) => seen.push(v))
  return { m, seen }
}

describe('an employee who needs you', () => {
  it('has exactly the three buttons', () => {
    expect(ESCALATION_BUTTONS.map((b) => b.label)).toEqual(['Retry this step', 'Re-plan', 'Stop build'])
  })

  it('is explained in plain words, with no raw reason codes', () => {
    for (const reason of ['max_iterations', 'no_improvement', 'repeated_action', 'invalid_output', 'no_valid_output', 'model_unavailable', 'review_unresolved', 'merge_conflict', 'waiting_human', 'something_new']) {
      const text = explainEscalation({ agent: 'backend', reason, detail: '', task: '' }, 'Rohan')
      expect(text).toContain(reason === 'invalid_output' || reason === 'review_unresolved' || reason === 'merge_conflict' ? '' : 'Rohan')
      expect(text).not.toMatch(/_/)
    }
  })

  it('the toast says what happened and carries the escalation action; the inspector data is kept until the state moves on', () => {
    const { m, seen } = setup()
    m.apply(ev('escalation', { agent: 'planner', reason: 'no_valid_output', detail: 'the plan has a cycle', task: 'planning' }))
    m.apply(ev('agent_state', { agent: 'planner', state: 'waiting_human' }))
    const toast = seen.find((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>
    expect(toast.title).toBe('Priya needs you')
    expect(toast.text).toContain('the plan has a cycle')
    expect(toast.text).toContain('retry this step, re-plan it, or stop the build')
    expect(toast.action).toEqual({ type: 'escalation', agent: 'planner' })
    expect(m.escalations.get('planner')?.reason).toBe('no_valid_output')
    m.apply(ev('agent_state', { agent: 'planner', state: 'thinking' }))
    expect(m.escalations.has('planner')).toBe(false)
  })

  it('an answered escalation rewrites the toast', () => {
    const { m, seen } = setup()
    m.apply(ev('escalation', { agent: 'backend', reason: 'max_iterations', detail: '' }))
    m.apply(ev('escalation_action', { agent: 'backend', action: 'retry', message: 'Rohan tries the step again with fresh attempts.' }))
    expect(m.escalations.has('backend')).toBe(false)
    expect(seen.find((v) => v.kind === 'toast_update')).toMatchObject({ key: 'escalation:backend', title: 'Retrying the step' })
  })
})

describe('approvals in a replay', () => {
  it('only a click is "you"; recorded answers say so', () => {
    expect(decidedBy('human')).toBe('decided by you')
    expect(decidedBy('recording')).toBe('approved during recording')
    expect(decidedBy('recording-auto')).toBe('auto-approved (recording)')
  })

  it('an approval toast carries Approve / Reject, and a rejection keeps its note', () => {
    const { m, seen } = setup()
    m.apply(ev('approval_needed', { id: 'a1', agent: 'backend', kind: 'write', summary: 'write x', details: {} }))
    expect((seen.find((v) => v.kind === 'toast') as Extract<Visual, { kind: 'toast' }>).action).toEqual({ type: 'approval', id: 'a1' })
    m.apply(ev('approval_resolved', { id: 'a1', agent: 'backend', kind: 'write', approve: false, by: 'human', note: 'in the recording this was approved' }))
    expect(m.approvals[0]).toMatchObject({ state: 'denied', note: 'in the recording this was approved' })
    const update = seen.find((v) => v.kind === 'toast_update') as Extract<Visual, { kind: 'toast_update' }>
    expect(update.title).toBe('Rejected')
    expect(update.text).toContain('in the recording this was approved')
  })

  it('auto answers are labelled as such', () => {
    const { m, seen } = setup()
    m.apply(ev('approval_needed', { id: 'a4', agent: 'backend', kind: 'write', summary: 'write y', details: {} }))
    m.apply(ev('approval_resolved', { id: 'a4', agent: 'backend', kind: 'write', approve: true, by: 'recording-auto' }))
    expect((seen.find((v) => v.kind === 'toast_update') as Extract<Visual, { kind: 'toast_update' }>).text).toContain('auto-approved (recording)')
  })
})

describe('skill packs', () => {
  it('the matched pack is kept with the spec, for the Contract tab', () => {
    const { m } = setup()
    m.apply(ev('spec_ready', { title: 'Cab booking app', summary: 'Drivers and rides.', features: [], text: '# x', not_included: [], skill: 'transport', skill_title: 'Transport and cabs' }))
    expect(m.spec?.skill).toBe('Transport and cabs')
    m.apply(ev('spec_ready', { title: 'Todo', summary: 'Tasks.', features: [], text: '# x' }))
    expect(m.spec?.skill).toBe('')
  })
})
