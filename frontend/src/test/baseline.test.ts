import { describe, expect, it } from 'vitest'
import type { BaselineArm, BaselineRun } from '../api'
import { headline, split, sumSplits } from '../baseline'

const arm = (passed: number, runs: number): BaselineArm => ({
  runs, passed, pass_rate: passed / runs, avg_seconds: 0, avg_seconds_passed: 0, tests_passed: 0, tests_failed: 0, test_pass_rate: 0, qa_bugs: 0, review_requests: 0,
  contract_repairs: 0, builds_with_repair: 0, functions: 0, functions_agent: 0, lines: 0, lines_agent: 0, agent_share_functions: 0, agent_share_lines: 0,
})

const run = (fa: number, fg: number, fr: number): BaselineRun => ({
  goal_key: 'a', goal: 'Build a', mode: 'team', rep: 1, ok: true, seconds: 1, tests: '', tests_passed: 1, tests_failed: 0, qa_bugs: 0, review_requests: 0, contract_repairs: 0, problems: [],
  authorship: { app: { functions: fa + fg + fr, functions_agent: fa, functions_generated: fg, functions_repair: fr, lines: 100, lines_agent: 20, lines_generated: 70, lines_repair: 10 } },
})

describe('baseline report helpers', () => {
  it('splits one build into agent, generated and repair', () => {
    expect(split(run(3, 4, 1), 'functions')).toEqual({ agent: 3, generated: 4, repair: 1, total: 8 })
    expect(split(run(3, 4, 1), 'lines')).toEqual({ agent: 20, generated: 70, repair: 10, total: 100 })
    expect(split({ ...run(1, 1, 1), authorship: {} }, 'lines')).toBeNull()
  })

  it('adds the splits of several builds and skips a build with no report', () => {
    const none = { ...run(0, 0, 0), authorship: {} }
    expect(sumSplits([run(3, 4, 1), run(1, 2, 0), none], 'functions')).toEqual({ agent: 4, generated: 6, repair: 1, total: 11 })
  })

  it('states the result as measured, in either direction', () => {
    expect(headline(arm(17, 18), arm(6, 18))).toContain('The team passed more')
    expect(headline(arm(6, 18), arm(12, 18))).toContain('The single agent passed more')
    expect(headline(arm(9, 18), arm(9, 18))).toContain('Both passed the same share')
    expect(headline(undefined, arm(1, 2))).toBe('')
  })
})
